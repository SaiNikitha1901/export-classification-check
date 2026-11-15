"""Integration tests against the running stack.

Run inside the compose network:  docker compose run --rm api python -m pytest -q tests
"""
import os
import time
import uuid

import pytest
import redis
import requests

from contracts import ProductRequest, Result

API = os.environ.get("API_URL", "http://api:8000")
FLASK = {
    "product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
    "materials": [{"name": "stainless steel", "share_pct": 70}, {"name": "plastic", "share_pct": 30}],
    "destination_country": "AE",
    "quantity": 500,
    "unit": "PCS",
}


def client(name=None):
    return {"X-Client-Id": name or f"test-{uuid.uuid4().hex[:8]}"}


def submit(body, headers=None):
    return requests.post(f"{API}/runs", json=body, headers=headers or client(), timeout=10)


def wait_final(run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = requests.get(f"{API}/runs/{run_id}", timeout=5).json()
        if run["status"] in ("completed", "escalated", "degraded", "failed"):
            return run
        time.sleep(0.5)
    pytest.fail(f"run {run_id} did not finish in {timeout}s")


def stats():
    return requests.get(f"{API}/admin/stats", timeout=5).json()


def test_health():
    body = requests.get(f"{API}/health", timeout=5).json()
    assert body["checks"]["postgres"] == "ok" and body["checks"]["redis"] == "ok"


def test_malformed_request_is_quarantined_and_starts_no_run():
    before = stats()
    resp = submit({"product_description": "flask", "destination_country": "xx", "quantity": -3, "rogue": 1})
    after = stats()
    assert resp.status_code == 422
    body = resp.json()
    assert {"product_description", "destination_country", "quantity", "rogue"} <= {e["field"] for e in body["errors"]}
    assert after["quarantine_total"] == before["quarantine_total"] + 1
    assert after["runs_total"] == before["runs_total"], "a rejected request must not create a run"
    assert after["queue_length"] <= before["queue_length"], "a rejected request must not enqueue a job"
    stored = [q for q in requests.get(f"{API}/quarantine", timeout=5).json() if q["id"] == body["quarantine_id"]]
    assert stored and stored[0]["errors"] == body["errors"]


def test_cross_field_rule_rejected():
    resp = submit({**FLASK, "materials": [{"name": "steel", "share_pct": 40}]})
    assert resp.status_code == 422
    assert "materials" in {e["field"] for e in resp.json()["errors"]}


def test_invalid_json_is_quarantined():
    resp = requests.post(f"{API}/runs", data="{not json", headers={**client(), "Content-Type": "application/json"})
    assert resp.status_code == 422 and resp.json()["errors"][0]["field"] == "__root__"


def test_valid_request_runs_to_a_contract_result():
    resp = submit(FLASK, headers={**client(), "X-Correlation-ID": "it-corr-1"})
    assert resp.status_code == 202
    assert resp.headers["X-Correlation-ID"] == "it-corr-1"
    run_id = resp.json()["run_id"]
    run = wait_final(run_id)
    if run["result"] is not None:
        result = Result.model_validate(run["result"])
        assert result.run_id == run_id
        assert result.route != "clear-for-filing" or result.verification.passed
    trace = requests.get(f"{API}/runs/{run_id}/trace", timeout=5).json()
    assert trace["run"]["correlation_id"] == "it-corr-1"
    assert ProductRequest.model_validate(trace["run"]["request"])


def test_unknown_run_is_404():
    assert requests.get(f"{API}/runs/{uuid.uuid4()}", timeout=5).status_code == 404
    assert requests.get(f"{API}/runs/not-a-uuid", timeout=5).status_code == 404


def test_feedback_once_per_finished_run():
    run_id = submit(FLASK).json()["run_id"]
    wait_final(run_id)
    url = f"{API}/runs/{run_id}/feedback"
    assert requests.post(url, json={"satisfactory": True, "reason": "looks right"}, timeout=5).status_code == 201
    assert requests.post(url, json={"satisfactory": False, "reason": "again"}, timeout=5).status_code == 409
    assert requests.post(url, json={"satisfactory": True}, timeout=5).status_code == 422
    summary = requests.get(f"{API}/feedback/summary", timeout=5).json()
    assert summary["total"] >= 1


def test_rate_limit_per_client():
    limit = int(os.environ["RATE_LIMIT_PER_MIN"])
    headers = client()
    bad = {"product_description": "x"}  # quarantined requests still count against the limit
    codes = [submit(bad, headers).status_code for _ in range(limit)]
    assert 429 not in codes
    over = submit(bad, headers)
    assert over.status_code == 429 and int(over.headers["Retry-After"]) >= 1
    assert submit(bad, client()).status_code == 422, "another client is not affected"


def test_run_cache_key_normalisation():
    from app.runcache import cache_key

    a = ProductRequest.model_validate(FLASK)
    b = ProductRequest.model_validate({**FLASK, "product_description": "  STAINLESS steel vacuum flask with a "
                                                                        "moulded plastic   outer body. ",
                                       "materials": list(reversed(FLASK["materials"]))})
    assert cache_key(a, "v1", "t1") == cache_key(b, "v1", "t1")
    assert cache_key(a, "v1", "t1") != cache_key(a, "v2", "t1"), "prompt change must change the key"
    assert cache_key(a, "v1", "t1") != cache_key(a, "v1", "t2"), "index rebuild must change the key"
    assert cache_key(a, "v1", "unknown") is None
    import os
    before = cache_key(a, "v1", "t1")
    old_model = os.environ.get("LLM_MODEL", "")
    os.environ["LLM_MODEL"] = old_model + "-other"
    try:
        assert cache_key(a, "v1", "t1") != before, "switching the LLM must change the key"
    finally:
        os.environ["LLM_MODEL"] = old_model


def test_ratelimit_window_unit():
    from app import ratelimit

    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    cid = f"unit-{uuid.uuid4().hex}"
    assert all(ratelimit.check(r, cid, 3)[0] for _ in range(3))
    allowed, retry = ratelimit.check(r, cid, 3)
    assert not allowed and 1 <= retry <= 60
    assert r.zcard(f"rl:{cid}") == 3, "rejected attempts are not counted"
