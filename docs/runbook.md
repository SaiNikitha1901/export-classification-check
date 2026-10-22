# Runbook (D8)

The two most likely failure modes. Commands assume you are in the repo root.

---

## 1. LLM provider unavailable or rate-limited (circuit breaker open)

**Symptom**
- Grafana *ECS · Agents*: "Circuit breaker state" at 2 (open). Retry rate rising. Success rate falling.
- Runs finish as `degraded` with route `specialist-classification-review` and an escalation reason mentioning the provider.
- Worker logs show `429`/`5xx`/timeouts from the LLM client.

**Confirm**
```bash
docker compose logs --tail 100 agent-worker | grep -i -E "breaker|retry|429|timeout"
curl -s 'localhost:9090/api/v1/query?query=ecs_circuit_breaker_state'
# is the provider itself reachable from a worker?
docker compose exec agent-worker python -c "import os,urllib.request;print(urllib.request.urlopen(os.environ['LLM_BASE_URL'].rstrip('/')+'/models',timeout=5).status)"
```

**Recover**
1. Free-tier quota exhausted: wait for the window to reset, or set `LLM_FALLBACK_*` in `.env` to a second provider, then `docker compose up -d agent-worker`.
2. Wrong key/URL after a config change: fix `.env`, then `docker compose up -d agent-worker`.
3. Demo/load test: switch to the stub with `LLM_BASE_URL=http://llm-stub:8002/v1` in `.env`, then `docker compose up -d agent-worker`.
4. The breaker half-opens by itself and closes after a successful probe. Watch the panel return to 0.
5. Runs that came back `degraded` are not answers. Re-submit them once the breaker is closed.

---

## 2. Retriever unhealthy or index missing/corrupt

**Symptom**
- `GET /health` on the API shows `"status": "degraded"` with `checks.retriever` not `ok`.
- Runs escalate because "no passages retrieved", or the worker logs connection errors to `retriever:8001`.
- Grafana *Quality & cost*: "Index chunks" is 0 or missing, and "Index age" is stale.

**Confirm**
```bash
curl -s localhost:8000/health
curl -s localhost:8001/health
curl -s localhost:8001/index/info          # built_at, chunk_count, sources
docker compose logs --tail 100 retriever
```

**Recover**
1. Container down/unhealthy: `docker compose up -d retriever`. It builds the index on start if the volume is empty, and stays unhealthy until the index loads.
2. Index corrupt or built from wrong documents: rebuild in the container:
   `docker compose run --rm retriever python -m retriever.ingest build`, then `docker compose restart retriever`.
3. Last resort, a clean index: `docker compose down retriever && docker volume rm ecs_index_data && docker compose up -d retriever`.
4. After a rebuild, `built_at` changes, which automatically invalidates the run cache and the retrieval cache.

---

## Other quick checks

| Symptom | Check | Fix |
|---|---|---|
| Runs stuck in `queued` | Grafana "Queue depth / live workers". `curl localhost:8000/admin/stats` | `docker compose up -d --scale agent-worker=N`. Check worker logs |
| Runs end `failed` with "did not reach a final status" | The watchdog fired; see the worker logs for that `run_id` | Usually a worker crash or `RUN_TIMEOUT_S` too low |
| `docker compose up` fails with "ports are not available … address already in use" | `lsof -nP -iTCP:<port> -sTCP:LISTEN` | Set e.g. `GRAFANA_HOST_PORT=3001` in `.env` (incident 1) |
| Many 429s | `ecs_rate_limited_total` | Expected for a looping client. Raise `RATE_LIMIT_PER_MIN` only deliberately |
