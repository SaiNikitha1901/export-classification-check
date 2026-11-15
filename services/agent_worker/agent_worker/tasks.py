"""RQ job entry point (contract A.6): agent_worker.tasks.run_classification(run_id, correlation_id).

Loads the request from Postgres, marks the run running, runs the agent graph (every step is written
to run_steps as it happens), then stores the Result. Any crash stores a failed, escalated Result:
an unfinished run is never returned as a confident answer (A5).
"""
from __future__ import annotations

import logging
import time

import psycopg
from psycopg.types.json import Jsonb
from redis import Redis

from agent_worker import config, graph, prompts, telemetry
from agent_worker.llm import LLMClient
from agent_worker.metrics import run_e2e, runs_total
from agent_worker.recorder import Budget, StepRecorder, pg_sink
from agent_worker.state import RunContext
from agent_worker.tools import RetrieverTools
from contracts import Escalation, Result, Usage
from ecs_common import bind

log = logging.getLogger("agent_worker.tasks")
_clients: dict = {}   # per-process HTTP/Redis clients (connection pools); no run state lives here


def _shared(settings):
    if not _clients:
        import httpx
        _clients["redis"] = Redis.from_url(settings.redis_url)
        _clients["http"] = httpx.Client()
    return _clients["redis"], _clients["http"]


def build_context(run_id: str, correlation_id: str, request: dict, prompt_version: str, sink) -> RunContext:
    s = config.load()
    redis, http = _shared(s)
    return RunContext(run_id=run_id, request=request, settings=s,
                      llm=LLMClient(s, redis, http=http),
                      tools=RetrieverTools(s.retriever_url, correlation_id, http=http),
                      recorder=StepRecorder(run_id, sink),
                      budget=Budget(s.max_steps, s.max_tool_calls, s.max_wall_s),
                      prompts=prompts.resolve(prompt_version), prompt_version=prompt_version)


def _failed_result(run_id: str, prompt_version: str, reason: str, steps: int = 0, latency_ms: int = 0) -> Result:
    return Result(run_id=run_id, status="failed", route="specialist-classification-review",
                  route_basis=f"The run failed before a verified answer ({reason}). Nothing is proposed.",
                  escalation=Escalation(escalated=True, reason=reason), prompt_version=prompt_version,
                  usage=Usage(steps=steps, latency_ms=latency_ms))


def run_classification(run_id: str, correlation_id: str, **_: object) -> str:
    s = config.load()
    with bind(run_id=run_id, correlation_id=correlation_id), \
            psycopg.connect(s.postgres_dsn, autocommit=True) as conn:
        row = conn.execute("SELECT request, prompt_version, created_at, trace_context, status FROM runs "
                           "WHERE run_id=%s", (run_id,)).fetchone()
        if row is None:
            log.error("run not found", extra={"event": "run_missing"})
            return "missing"
        request, prompt_version, created_at, trace_context, status = row
        prompt_version = prompt_version or s.prompt_version
        if status != "queued":   # duplicate delivery, or the watchdog already gave up on it
            log.warning("run is %s, not queued; skipping", status, extra={"event": "run_skipped"})
            return status
        conn.execute("UPDATE runs SET status='running', updated_at=now() WHERE run_id=%s", (run_id,))
        log.info("run started", extra={"event": "run_started", "prompt_version": prompt_version})

        ctx = None
        with telemetry.tracer.start_as_current_span("run_classification",
                                                    context=telemetry.extract(trace_context)) as span:
            span.set_attribute("run_id", run_id)
            span.set_attribute("correlation_id", correlation_id)
            span.set_attribute("prompt_version", prompt_version)
            try:
                ctx = build_context(run_id, correlation_id, request, prompt_version, pg_sink(conn))
                result = graph.run(ctx)
            except Exception as exc:  # noqa: BLE001
                log.exception("run crashed", extra={"event": "run_crashed"})
                steps = len(ctx.recorder.rows) if ctx else 0
                result = _failed_result(run_id, prompt_version, f"{type(exc).__name__}: {exc}"[:300], steps,
                                        ctx.recorder.latency_ms() if ctx else 0)
                runs_total.labels(agent="run", outcome="failed").inc()
            span.set_attribute("status", result.status)
            span.set_attribute("route", result.route)

        conn.execute("UPDATE runs SET status=%s, result=%s, error=%s, updated_at=now() "
                     "WHERE run_id=%s AND status='running'",
                     (result.status, Jsonb(result.model_dump(mode="json")),
                      result.escalation.reason if result.status == "failed" else None, run_id))
        e2e = float(conn.execute("SELECT extract(epoch FROM now() - %s)", (created_at,)).fetchone()[0])
        run_e2e.observe(e2e)
        log.info("run finished: %s / %s", result.status, result.route,
                 extra={"event": "run_finished", "status": result.status, "route": result.route,
                        "e2e_s": round(e2e, 2), "cost_usd": result.usage.cost_usd})
        return result.status


if __name__ == "__main__":  # handy for a manual check: python -m agent_worker.tasks <run_id>
    import sys
    t = time.time()
    print(run_classification(sys.argv[1], "manual"), f"{time.time() - t:.1f}s")
