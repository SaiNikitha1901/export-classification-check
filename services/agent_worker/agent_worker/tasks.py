"""PLACEHOLDER task (Member 1 skeleton; Member 3 replaces it with the LangGraph agents).

Honours the queue contract (A.6) so the platform can be tested end to end before the agents exist:
loads the run, marks it running, writes one run_steps row, then stores an escalated Result.
It never claims a classification, so it always escalates to specialist review.
"""
import logging
import os
import time

import psycopg
from prometheus_client import Counter, Histogram
from psycopg.types.json import Jsonb

from contracts import Escalation, Result, Usage
from ecs_common import bind

log = logging.getLogger("agent_worker")
runs_total = Counter("ecs_agent_runs_total", "Agent runs", ["agent", "outcome"])
run_e2e = Histogram("ecs_run_e2e_seconds", "Run time from submission to final result",
                    buckets=(1, 2, 5, 10, 20, 30, 45, 60, 90, 120, 180))


def run_classification(run_id: str, correlation_id: str, **_: object) -> str:
    with bind(run_id=run_id, correlation_id=correlation_id, agent="placeholder"), \
            psycopg.connect(os.environ["POSTGRES_DSN"], autocommit=True) as conn:
        row = conn.execute("SELECT created_at, prompt_version FROM runs WHERE run_id=%s", (run_id,)).fetchone()
        if row is None:
            log.error("run not found")
            return "missing"
        created_at, prompt_version = row
        conn.execute("UPDATE runs SET status='running', updated_at=now() WHERE run_id=%s", (run_id,))
        log.info("placeholder run started", extra={"event": "run_started"})
        start = time.perf_counter()
        time.sleep(float(os.environ.get("PLACEHOLDER_DELAY_S", "1.0")))
        latency_ms = int((time.perf_counter() - start) * 1000)
        conn.execute(
            "INSERT INTO run_steps (run_id, step_no, agent, kind, name, input, output, status, latency_ms, "
            "prompt_tokens, completion_tokens, cost_usd, prompt_version) "
            "VALUES (%s, 1, 'placeholder', 'route', 'placeholder_escalate', %s, %s, 'ok', %s, 0, 0, 0, %s)",
            (run_id, Jsonb({}), Jsonb({"route": "specialist-classification-review"}), latency_ms, prompt_version),
        )
        result = Result(
            run_id=run_id,
            status="escalated",
            route="specialist-classification-review",
            route_basis="Skeleton placeholder: the agent system is not built yet, so every case is escalated.",
            escalation=Escalation(escalated=True, reason="agent system not yet implemented"),
            prompt_version=prompt_version or "none",
            usage=Usage(steps=1, latency_ms=latency_ms),
        )
        conn.execute(
            "UPDATE runs SET status=%s, result=%s, updated_at=now() WHERE run_id=%s",
            (result.status, Jsonb(result.model_dump(mode="json")), run_id),
        )
        runs_total.labels(agent="placeholder", outcome="escalated").inc()
        run_e2e.observe(float(conn.execute("SELECT extract(epoch FROM now() - %s)", (created_at,)).fetchone()[0]))
        log.info("placeholder run finished", extra={"event": "run_finished"})
        return result.status
