# Demo script: the 10 items from §9

Run top to bottom at Evaluation 2. Owners send their exact steps to Member 1, who keeps this file. Items marked ⏳ depend on teammates' work and will be filled in when it is merged.

Before the demo: `docker compose down -v`, so item 1 really starts from nothing.

---

### 1. `docker compose up` from a clean clone (M1)
```bash
git clone <repo-url> ecs-demo && cd ecs-demo
docker compose up -d --build --wait      # everything healthy
docker compose ps
```
Open http://localhost:8000/ui, Grafana http://localhost:3000 (or your `GRAFANA_HOST_PORT`), Jaeger http://localhost:16686.

### 2. Valid request → routed recommendation with citations that resolve to retrieved text (M3, M2) ⏳
In the UI, click **Load demo case** → **Submit**. Show the route, the citations, and then `GET /runs/{id}/trace` showing the same quotes inside the retrieved passages.

### 3. One run traced end to end (M1 + M3)
```bash
curl -s localhost:8000/runs/<run_id>/trace | python3 -m json.tool | less
```
In Jaeger, open the trace for the run (search tag `run_id=<run_id>`). Show every tool call, query, passage, prompt version, per-step latency and cost.

### 4. Malformed request rejected and quarantined, with evidence no run started (M1)
```bash
curl -s localhost:8000/admin/stats                                   # note runs_total
curl -s -X POST localhost:8000/runs -H 'Content-Type: application/json' \
  -d '{"product_description":"flask","destination_country":"xx","quantity":-3,"rogue":1}' | python3 -m json.tool
curl -s localhost:8000/admin/stats                                   # runs_total unchanged, quarantine_total +1
curl -s 'localhost:8000/quarantine?limit=1' | python3 -m json.tool   # stored with field-level errors
```
Or in the UI: **Load malformed request** → **Submit**.

### 5. A case the corpus cannot answer → escalation, not fabrication (M3, M2) ⏳
Submit e.g. `"Laptop computer with aluminium casing"` (outside chapters 73/96). Expect `specialist-classification-review` with an escalation reason and no HS code.

### 6. Self-verification catches an unsupported answer → further search or escalation (M3) ⏳

### 7. Prompt injection attempt and the guardrail response (M3) ⏳
UI: **Load injection attempt** → **Submit**. Show `guardrails.injection_detected = true` and the route.

### 8. Circuit breaker opens when the provider is unavailable; degradation path (M3) ⏳

### 9. Locust against the declared target, the failing concurrency, the effect of `--scale` (M1)
Show `loadtest/SLO.md` (and its commit date), then `loadtest/RESULTS.md`. Live:
```bash
docker compose up -d --scale agent-worker=3
RUN_TIME=60s loadtest/sweep.sh live-demo 10
```
Show the Grafana *Service health* dashboard during the run (queue depth, p95, CPU per container).

### 10. The §4.1 case handled correctly (M3, M2) ⏳
Vacuum flask → heading 9617 found even though the first search hits chapter 73. The rule and the heading are cited, and the excluding note is cited.
