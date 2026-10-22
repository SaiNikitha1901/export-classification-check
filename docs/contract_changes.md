# Contract changes

Proposals and agreed changes to the shared team contract (Part A of the prompts). Do not change the contract alone. Write the proposal here, and all three members agree before it is merged.

| # | Date | Proposed by | Change | Affects | Status |
|---|---|---|---|---|---|
| 1 | 2026-10-22 | M1 | **Additive DB columns on `runs`:** `cache_key`, `cache_stored`, `cached_from` (whole-run cache), `trace_context` (W3C traceparent of the submit span), `callback_url`, `callback_state`, `callback_attempts`, `callback_next_at`. Plus `UNIQUE (run_id)` on `feedback`. Existing A.8 columns are unchanged. | M1 only. Workers may ignore them | in skeleton, please ack |
| 2 | 2026-10-22 | M1 | **Trace propagation:** the worker reads `runs.trace_context` and continues the trace with `opentelemetry.propagate.extract(trace_context)`. The job kwargs stay exactly `run_id, correlation_id` (A.6), so no worker signature change is needed. | M3 | proposed |
| 3 | 2026-10-22 | M1 | **`ecs_agent_runs_total` outcome label values:** `success`, `escalated`, `degraded`, `failed`. The Grafana success-rate panel uses `outcome="success"`. | M3 | proposed |
| 4 | 2026-10-22 | M1 | **Host ports configurable** via `*_HOST_PORT` in `.env` (defaults unchanged). Container ports and service names are unchanged. | everyone (local only) | in skeleton |
| 5 | 2026-10-22 | M1 | **Container metrics** come from `docker-exporter` (`ecs_container_*`) instead of cAdvisor. Adds one compose service. | M1 only | in skeleton |
| 6 | 2026-10-22 | M1 | **`ecs_run_e2e_seconds`** is measured from `runs.created_at` (submission) to when the worker writes the final result, so it matches the SLO definition. | M3 | proposed |
