# Demo script: the 10 items from §9

Run top to bottom at Evaluation 2. Steps are from Members 2 and 3 (`docs/demo_steps_member2.md`, `docs/agent_design.md` §8). Real-model runs take 2–4 min on the Groq free tier, so start item 2 and item 10 early, and run items 4, 7 and 8 while they finish.

Before the demo: `docker compose down -v`, so item 1 really starts from nothing.

---

### 1. `docker compose up` from a clean clone (M1)
```bash
git clone <repo-url> ecs-demo && cd ecs-demo
docker compose up -d --build --wait      # everything healthy
docker compose ps
```
Open http://localhost:8000/ui, Grafana http://localhost:3000 (or your `GRAFANA_HOST_PORT`), Jaeger http://localhost:16686.

### 2. Valid request → routed recommendation with citations that resolve to retrieved text (M3, M2)
In the UI, click **Load demo case**, add " Capacity 500 ml." to the description, then **Submit**.
- **Expect:** route `clear-for-filing`, HS **96170011**, heading 9617, GRI-1 + GRI-6, policy Free (`EXP-GN-1`), verification passed.
- Show that every citation's quote is real text from the corpus:
  ```bash
  curl -s localhost:8001/clause/HDG-9617
  curl -s localhost:8001/clause/TL-96170011
  curl -s localhost:8001/clause/SEC-XV-NOTE-1
  ```
- The verifier enforces this before anything is returned (`services/agent_worker/agent_worker/agents/verifier.py`, `check_citations`).

### 3. One run traced end to end (M1 + M3)
```bash
curl -s localhost:8000/runs/<run_id>/trace | python3 -m json.tool | less
```
- Show: every `tool` step (query and passages), every `llm` step (`prompt_version`, `prompt_tokens`, `cost_usd`, `latency_ms`), and the `verify` steps.
- In Jaeger (http://localhost:16686), service `api`: search tag `run_id=<run_id>`. One trace covers the API, the worker and the retriever calls.

### 4. Malformed request rejected and quarantined, with evidence no run started (M1)
```bash
curl -s localhost:8000/admin/stats                                   # note runs_total
curl -s -X POST localhost:8000/runs -H 'Content-Type: application/json' \
  -d '{"product_description":"flask","destination_country":"xx","quantity":-3,"rogue":1}' | python3 -m json.tool
curl -s localhost:8000/admin/stats                                   # runs_total unchanged, quarantine_total +1
curl -s 'localhost:8000/quarantine?limit=1' | python3 -m json.tool   # stored with field-level errors
```
Or in the UI: **Load malformed request** → **Submit**.

### 5. A case the corpus cannot answer → escalation, not fabrication (M3, M2)
Submit `"Laptop computer with aluminium casing, 14 inch screen."` (scenario S22).
- **Expect:** `specialist-classification-review`, no HS code, basis "does not fall under Customs Tariff Chapters 73 or 96".
- `curl -s localhost:8001/policy/84713010` returns 404: the retriever won't answer out of scope either.

### 6. Self-verification catches an unsupported answer → further search or escalation (M3)
For a reliable demo, use the test that plants a fabricated quote in the classifier's answer:
```bash
docker compose run --rm agent-worker python -m pytest -q tests/test_graph.py -k fabricated -s
```
- **Expect:** `verifier / deterministic_checks` fails ("quote is not exact text from passage …"), the classifier runs attempt 2 with a different strategy, then verification passes.
- The companion test `-k persistent` shows a fabrication that never goes away ending in escalation, never an answer.

### 7. A prompt injection attempt and the guardrail response (M3)
UI: **Load injection attempt** → **Submit**.
- **Expect:** `guardrails.injection_detected = true`, status `escalated`, route `specialist-classification-review`, and **no `llm` steps** in the trace: the text never reached a model.

### 8. The circuit breaker opens when the provider is unavailable; degradation path (M3)
```bash
docker compose exec redis redis-cli SET ecs:chaos:llm_fail all      # provider "goes down"
# submit 2 runs in the UI
curl -s localhost:9090/api/v1/query --data-urlencode 'query=max(ecs_circuit_breaker_state)'   # 1 = open
docker compose exec redis redis-cli DEL ecs:chaos:llm_fail          # heal; after CB_OPEN_S a probe closes it
```
- **Expect:** the runs come back `degraded`, route specialist, "Retrieval-only result … Candidate headings found: …", with no HS code.
- Grafana *ECS · Agents*: "Circuit breaker state" goes 0 → 1 → 2 → 0.
- A rate limit (HTTP 429) is **not** an outage: the client waits for the provider's Retry-After and the breaker stays closed (incident 9).

### 9. Locust against the declared target, the failing concurrency, the effect of `--scale` (M1)
Show `loadtest/SLO.md` (and its commit date), then `loadtest/RESULTS.md`. Live:
```bash
docker compose up -d --scale agent-worker=3
RUN_TIME=60s loadtest/sweep.sh live-demo 10
```
Show the Grafana *Service health* dashboard during the run (queue depth, p95, CPU per container).

### 10. The §4.1 case handled correctly (M3, M2)
Reference answer: `docs/decisions.md` D1.
1. **Exact sentence** (UI: **Load demo case**): *"Stainless steel vacuum flask with a moulded plastic outer body."* → heading **9617** by **GRI-1**. Cites `GRI-1`, `HDG-9617` and `SEC-XV-NOTE-1` (the note that excludes Chapter 96 articles from base-metal chapters, so not 7323). Route **seek-product-clarification**: capacity decides 9617 00 11 vs 9617 00 12.
2. **Follow-up:** add "Capacity 500 ml." → **96170011** by GRI-1 + **GRI-6**, `clear-for-filing` (verified), export policy **Free** (`EXP-GN-1`).
3. Open `/runs/{id}/trace` to show that the first search hit Chapter 73, and that the agent then found the heading that names the article.
