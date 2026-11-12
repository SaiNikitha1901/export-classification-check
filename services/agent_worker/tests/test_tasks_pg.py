"""The RQ task against the real Postgres: run_steps rows per step, cost per step and per run, result row."""
import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

import conftest
from agent_worker import tasks
from agent_worker.recorder import StepRecorder


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(os.environ["POSTGRES_DSN"], autocommit=True, connect_timeout=3)
    except Exception:  # noqa: BLE001
        pytest.skip("Postgres not reachable")
    yield c
    c.close()


def new_run(conn, description=conftest.FLASK):
    run_id = str(uuid.uuid4())
    conn.execute("INSERT INTO runs (run_id, correlation_id, status, request, prompt_version) "
                 "VALUES (%s, 'test-cid', 'queued', %s, 'classifier@v2')",
                 (run_id, Jsonb({"product_description": description, "destination_country": "AE"})))
    return run_id


def fake_build(run_id, cid, request, pv, sink):
    ctx = conftest.make_ctx(request=request, prompt_version=pv)
    ctx.run_id, ctx.recorder = run_id, StepRecorder(run_id, sink)
    return ctx


def test_task_writes_every_step_and_the_result(conn, monkeypatch):
    monkeypatch.setattr(tasks, "build_context", fake_build)
    run_id = new_run(conn)
    try:
        assert tasks.run_classification(run_id, "test-cid") == "completed"
        status, result = conn.execute("SELECT status, result FROM runs WHERE run_id=%s", (run_id,)).fetchone()
        rows = conn.execute("SELECT agent, kind, name, prompt_tokens, cost_usd, prompt_version, input, output "
                            "FROM run_steps WHERE run_id=%s ORDER BY step_no", (run_id,)).fetchall()
        assert status == "completed" and result["route"] == "seek-product-clarification"
        assert len(rows) == result["usage"]["steps"]
        assert {r[1] for r in rows} == {"guardrail", "tool", "llm", "verify", "route"}
        llm = [r for r in rows if r[1] == "llm"]
        assert all(r[3] > 0 and r[4] > 0 and r[5] for r in llm)            # tokens, cost, prompt version per step
        assert float(sum(r[4] for r in rows)) == pytest.approx(result["usage"]["cost_usd"], abs=1e-6)
        tool = [r for r in rows if r[1] == "tool" and r[2] == "search_corpus"]
        assert tool[0][6]["query"] and tool[0][7]["passages"][0]["text"]     # query + passage text kept (D5)
    finally:
        conn.execute("DELETE FROM runs WHERE run_id=%s", (run_id,))


def test_crash_is_stored_as_failed_escalation(conn, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("cannot build context")
    monkeypatch.setattr(tasks, "build_context", broken)
    run_id = new_run(conn)
    try:
        assert tasks.run_classification(run_id, "test-cid") == "failed"
        status, result, error = conn.execute("SELECT status, result, error FROM runs WHERE run_id=%s",
                                             (run_id,)).fetchone()
        assert status == "failed" and result["route"] == "specialist-classification-review"
        assert result["proposed_hs_code"] is None and "cannot build context" in error
    finally:
        conn.execute("DELETE FROM runs WHERE run_id=%s", (run_id,))


def test_run_not_queued_is_skipped(conn, monkeypatch):
    monkeypatch.setattr(tasks, "build_context", fake_build)
    run_id = new_run(conn)
    conn.execute("UPDATE runs SET status='failed' WHERE run_id=%s", (run_id,))   # e.g. the watchdog gave up
    try:
        assert tasks.run_classification(run_id, "test-cid") == "failed"
        assert conn.execute("SELECT count(*) FROM run_steps WHERE run_id=%s", (run_id,)).fetchone()[0] == 0
    finally:
        conn.execute("DELETE FROM runs WHERE run_id=%s", (run_id,))
