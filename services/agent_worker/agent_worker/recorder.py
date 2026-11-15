"""Per-run bookkeeping: one run_steps row per LLM call / tool call / verification / guardrail /
routing decision (D5, L5), written the moment the step ends so a crash keeps every earlier step.
Also the loop budget (A1): LLM steps, tool calls and wall-clock time per run."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from contextlib import contextmanager
from functools import partial
from typing import Any, Iterator

from opentelemetry.trace import Status, StatusCode

from agent_worker.metrics import step_latency, tool_calls
from agent_worker.telemetry import tracer
from ecs_common import bind

log = logging.getLogger("agent_worker.steps")
_dumps = partial(json.dumps, default=str)


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, max_steps: int, max_tool_calls: int, max_wall_s: float):
        self.max_steps, self.max_tool_calls, self.max_wall_s = max_steps, max_tool_calls, max_wall_s
        self.t0 = time.monotonic()
        self.deadline = self.t0 + max_wall_s
        self.steps = 0        # LLM calls
        self.tool_calls = 0

    def check(self, kind: str) -> None:
        """Raise before starting an LLM step ("llm") or a tool call ("tool") that would break a bound."""
        if time.monotonic() >= self.deadline:
            raise BudgetExceeded(f"wall-clock limit of {self.max_wall_s:g}s reached")
        if kind == "llm" and self.steps >= self.max_steps:
            raise BudgetExceeded(f"step limit of {self.max_steps} LLM calls reached")
        if kind == "tool" and self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool-call limit of {self.max_tool_calls} reached")
        if kind == "llm":
            self.steps += 1
        elif kind == "tool":
            self.tool_calls += 1


class StepRecorder:
    """sink(row: dict) persists a step. tasks.py passes a Postgres writer; tests pass list.append."""

    def __init__(self, run_id: str, sink=None):
        self.run_id, self.sink = run_id, sink
        self.rows: list[dict] = []
        self.prompt_tokens = self.completion_tokens = 0
        self.cost_usd = 0.0
        self.tool_calls = 0
        self.per_agent: Counter[str] = Counter()
        self.t0 = time.perf_counter()

    @contextmanager
    def step(self, agent: str, kind: str, name: str, input: Any = None,
             prompt_version: str | None = None) -> Iterator[dict]:
        rec: dict[str, Any] = {"output": None, "status": "ok", "prompt_tokens": 0, "completion_tokens": 0,
                               "cost_usd": 0.0, "prompt_version": prompt_version}
        start = time.perf_counter()
        with bind(agent=agent, step=name), tracer.start_as_current_span(f"{agent}.{name}") as span:
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("agent", agent)
            span.set_attribute("step.kind", kind)
            try:
                yield rec
            except Exception as exc:
                rec["status"] = "error"
                rec["output"] = rec["output"] or {"error": f"{type(exc).__name__}: {exc}"}
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                latency = time.perf_counter() - start
                self._write(agent, kind, name, input, rec, latency, span)

    def _write(self, agent, kind, name, input, rec, latency, span) -> None:
        row = {"run_id": self.run_id, "step_no": len(self.rows) + 1, "agent": agent, "kind": kind, "name": name,
               "input": input, "output": rec["output"], "status": rec["status"],
               "latency_ms": int(latency * 1000), "prompt_tokens": rec["prompt_tokens"],
               "completion_tokens": rec["completion_tokens"], "cost_usd": rec["cost_usd"],
               "prompt_version": rec["prompt_version"]}
        self.rows.append(row)
        self.per_agent[agent] += 1
        self.prompt_tokens += rec["prompt_tokens"]
        self.completion_tokens += rec["completion_tokens"]
        self.cost_usd += rec["cost_usd"]
        span.set_attribute("latency_ms", row["latency_ms"])
        if rec["prompt_tokens"]:
            span.set_attribute("llm.prompt_tokens", rec["prompt_tokens"])
            span.set_attribute("llm.completion_tokens", rec["completion_tokens"])
            span.set_attribute("llm.cost_usd", rec["cost_usd"])
        step_latency.labels(agent=agent, step=name).observe(latency)
        if kind == "tool":
            self.tool_calls += 1
            tool_calls.labels(agent=agent, tool=name).inc()
        log.info("%s %s %s", kind, name, rec["status"],
                 extra={"event": f"step_{kind}", "latency_ms": row["latency_ms"], "status": rec["status"]})
        if self.sink:
            try:
                self.sink(row)
            except Exception:  # noqa: BLE001 - losing a trace row must not kill the run
                log.exception("could not persist step", extra={"event": "step_persist_error"})

    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def pg_sink(conn):
    from psycopg.types.json import Jsonb

    def write(row: dict) -> None:
        conn.execute(
            "INSERT INTO run_steps (run_id, step_no, agent, kind, name, input, output, status, latency_ms, "
            "prompt_tokens, completion_tokens, cost_usd, prompt_version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (row["run_id"], row["step_no"], row["agent"], row["kind"], row["name"],
             Jsonb(row["input"], dumps=_dumps), Jsonb(row["output"], dumps=_dumps), row["status"],
             row["latency_ms"], row["prompt_tokens"], row["completion_tokens"], row["cost_usd"],
             row["prompt_version"]))
    return write
