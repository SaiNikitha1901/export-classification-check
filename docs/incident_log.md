# Incident log (D8)

Real failures from development only. Add an entry when something actually breaks: date, what we saw, how we found the cause, the fix, and how we prevent it next time.

---

### 1. `docker compose up` failed: port 3000 already in use (2026-10-22)
- **Seen:** the first `docker compose up` on Member 1's Mac stopped for Grafana with `ports are not available: exposing port TCP 0.0.0.0:3000 -> 127.0.0.1:0: listen tcp 0.0.0.0:3000: bind: address already in use`. All other services had started.
- **Found:** `lsof -nP -iTCP:3000 -sTCP:LISTEN` showed a local Node.js dev server on port 3000.
- **Root cause:** fixed host ports in `docker-compose.yml` collide with whatever else the developer runs.
- **Fix:** every host port is now `${X_HOST_PORT:-default}`, and a developer can override it in `.env` (Member 1 uses `GRAFANA_HOST_PORT=3001`). Container ports are unchanged, so nothing inside the stack is affected.
- **Prevention:** documented in `.env.example`, the README troubleshooting section and the runbook.

### 2. cAdvisor showed no per-container metrics on Docker Desktop (2026-10-22)
- **Seen:** the "CPU per container" and "Memory per container" panels were empty. Prometheus had only one `container_memory_usage_bytes` series, for `id="/"`.
- **Found:** cAdvisor logs showed the containerd/podman/crio factories failing, with no Docker factory registered (`DockerVersion:` empty). cAdvisor v0.49.1 cannot talk to the Docker Desktop (engine 29) VM layout, so it only sees the VM root cgroup.
- **Root cause:** a tool/platform mismatch. cAdvisor expects a Linux host's Docker layout.
- **Fix:** replaced cAdvisor with `ops/docker_exporter` (about 120 lines, stdlib + prometheus_client). It reads the Docker Engine API through the socket and exposes `ecs_container_cpu_cores`, `ecs_container_memory_bytes`, `ecs_container_uptime_seconds` and `ecs_container_up`, labelled by compose service. It works the same on Mac and Linux.
- **Prevention:** checked by querying `ecs_container_cpu_cores` after `docker compose up`.

### 3. Every placeholder job marked failed in RQ: `float += Decimal` (2026-10-22)
- **Seen:** during the `--scale agent-worker=3` test, worker logs showed `TypeError: unsupported operand type(s) for +=: 'float' and 'decimal.Decimal'` for every job. The runs still showed `escalated`, because the result was written before the error, so the API looked healthy.
- **Found:** the traceback pointed at `run_e2e.observe(...)`. Postgres `extract(epoch …)` returns `numeric`, which psycopg maps to `Decimal`, and prometheus_client only accepts floats.
- **Root cause:** a type mismatch between the DB driver and the metrics library. The end-to-end latency histogram silently never recorded anything.
- **Fix:** convert with `float(...)` before observing.
- **Prevention / lesson:** a run being correct in the DB does not mean the job succeeded. The load-test checklist in `loadtest/RESULTS.md` now includes checking worker logs for `"level": "ERROR"` after every run. An empty "Complete run time" panel while runs are finishing is the visible signal of this bug.
