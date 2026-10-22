"""Load test for a COMPLETE run (D6): submit, then poll until a final status.

Each simulated analyst has its own X-Client-Id, so the per-client rate limit does not distort the test.
CACHE_MODE=unique (default) adds a unique token to every description, so the run cache never hits;
CACHE_MODE=repeat reuses a small fixed set, so the run cache can hit (to measure D7).
"""
import os
import random
import time
import uuid

from locust import HttpUser, between, events, task

FINAL = {"completed", "escalated", "degraded", "failed"}
CACHE_MODE = os.environ.get("CACHE_MODE", "unique")
RUN_TIMEOUT_S = float(os.environ.get("LOCUST_RUN_TIMEOUT_S", "300"))
POLL_S = float(os.environ.get("LOCUST_POLL_S", "1.0"))

SCENARIOS = [
    {"product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
     "materials": [{"name": "stainless steel", "share_pct": 70}, {"name": "plastic", "share_pct": 30}],
     "destination_country": "AE", "quantity": 500, "unit": "PCS"},
    {"product_description": "Zinc-plated steel wood screws, 40 mm, packed in boxes of 100", "destination_country": "US"},
    {"product_description": "Stainless steel kitchen sink, single bowl", "destination_country": "GB"},
    {"product_description": "Ball-point pen with refillable plastic body", "destination_country": "DE"},
    {"product_description": "Plastic hair comb", "destination_country": "SG"},
    {"product_description": "Cast iron anchor chain links for small boats", "destination_country": "NL"},
]


class Analyst(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client_id = f"locust-{uuid.uuid4().hex[:10]}"

    @task
    def classify(self):
        body = dict(random.choice(SCENARIOS))
        if CACHE_MODE == "unique":
            body["product_description"] = f"{body['product_description']} (ref {uuid.uuid4().hex[:8]})"
        start = time.perf_counter()
        with self.client.post("/runs", json=body, headers={"X-Client-Id": self.client_id},
                              name="POST /runs", catch_response=True) as resp:
            if resp.status_code != 202:
                resp.failure(f"submit returned {resp.status_code}")
                return
            run_id = resp.json()["run_id"]
        status, error = None, None
        while time.perf_counter() - start < RUN_TIMEOUT_S:
            r = self.client.get(f"/runs/{run_id}", name="GET /runs/[id]")
            if r.ok and (status := r.json()["status"]) in FINAL:
                break
            time.sleep(POLL_S)
        else:
            error = TimeoutError(f"run not final after {RUN_TIMEOUT_S}s")
        if status == "failed" and error is None:
            error = RuntimeError("run failed")
        events.request.fire(request_type="RUN", name="complete_run",
                            response_time=(time.perf_counter() - start) * 1000, response_length=0,
                            exception=error, context={})
