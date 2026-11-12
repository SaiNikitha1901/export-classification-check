"""Prometheus metrics emitted by the worker (names agreed in contract A.9).
RQ SimpleWorker runs jobs in-process (no fork), so a plain registry is enough."""
from prometheus_client import Counter, Gauge, Histogram

runs_total = Counter("ecs_agent_runs_total", "Agent outcomes per run", ["agent", "outcome"])
steps_per_run = Histogram("ecs_agent_steps_per_run", "Recorded steps per run, by agent", ["agent"],
                          buckets=(1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 30))
tool_calls = Counter("ecs_agent_tool_calls_total", "Tool calls", ["agent", "tool"])
step_latency = Histogram("ecs_agent_step_latency_seconds", "Latency of one agent step", ["agent", "step"],
                         buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30))
run_e2e = Histogram("ecs_run_e2e_seconds", "Run time from submission to final result",
                    buckets=(1, 2, 5, 10, 20, 30, 45, 60, 90, 120, 180))
llm_retries = Counter("ecs_llm_retries_total", "LLM call retries", ["agent"])
llm_tokens = Counter("ecs_llm_tokens_total", "LLM tokens", ["agent", "kind"])
llm_cost = Counter("ecs_llm_cost_usd_total", "Notional LLM cost in USD", ["agent"])
breaker_state = Gauge("ecs_circuit_breaker_state", "0 closed, 1 open, 2 half-open", ["provider"])
