# Export Classification Check Service

Mini Project 07 · UE24AM342AA5 ML System Design and AgentOps · PES University

A multi-agent service that takes a product description, validates it, proposes an **HS tariff classification** (Customs Tariff chapters 73 and 96) with the **GRI rule** it applied and **citations**, states the **DGFT export policy**, and routes the case to `clear-for-filing`, `seek-product-clarification` or `specialist-classification-review`.

> It never files a declaration. It produces a proposed classification with evidence, and a licensed customs broker decides. When it cannot support an answer, it escalates instead of guessing.

Spec: [`docs/spec/MiniProject_07_Export_Classification_Check.pdf`](docs/spec/MiniProject_07_Export_Classification_Check.pdf) · Architecture: [`docs/architecture.md`](docs/architecture.md) · Plain-English explanation: [`explanation.md`](explanation.md)

## Run it

**You need:** Docker Desktop (or Docker Engine + Compose v2.24+), about 6 GB free RAM, and git. Nothing else runs on your machine. Everything runs in containers.

```bash
git clone <repo-url> export-classification-check
cd export-classification-check
docker compose up -d --build --wait
```

That's all. With no `.env`, the system uses the defaults in `.env.example`, which point the LLM at the local stub, so it starts without any account.

Then open:

| What | URL |
|---|---|
| Web client | http://localhost:8000/ui |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Grafana dashboards | http://localhost:3000 (anonymous view; admin login in `.env.example`) |
| Jaeger traces | http://localhost:16686 |
| Prometheus | http://localhost:9090 |

In the web client, click **Load demo case (§4.1)** → **Submit**.

### Using a real LLM (what we demo on: Groq, decision D2 in `docs/decisions.md`)
Create a free key on Groq's console, then create a file called `.env` next to `docker-compose.yml` with the six `LLM_*` lines from **decision D2 in [`docs/decisions.md`](docs/decisions.md)** (base URL, key, model, and the same three for the fallback), with your key filled in.
Then `docker compose up -d`. `.env` is git-ignored, so never commit keys. Any other OpenAI-compatible endpoint works the same way.

**Free-tier expectations:** Groq allows 8,000 tokens/minute and 200,000 tokens/day per model. A run uses about 10–25k tokens, so a real run takes **2–4 minutes**: the client waits for the provider's Retry-After instead of failing. Each model handles about 8–15 runs a day. When both models' daily quota is spent, runs come back `degraded` (an honest "model unavailable" result, never a guess).

### From the command line
```bash
curl -s -X POST localhost:8000/runs -H 'Content-Type: application/json' -H 'X-Client-Id: me' -d '{
  "product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
  "materials": [{"name": "stainless steel", "share_pct": 70}, {"name": "plastic", "share_pct": 30}],
  "destination_country": "AE", "quantity": 500, "unit": "PCS"}'
# -> {"run_id": "...", "status": "queued", "poll_url": "/runs/..."}
curl -s localhost:8000/runs/<run_id>          # poll until status is final
curl -s localhost:8000/runs/<run_id>/trace    # every step, tool call, prompt version, cost
```
The request format is in [`docs/data_contract.md`](docs/data_contract.md).

## Services

| Service | Port | Owner | Role |
|---|---|---|---|
| `api` | 8000 | Member 1 | Gateway: validation + quarantine, rate limit, run cache, status/trace/feedback, web client |
| `agent-worker` | metrics 9100 | Member 3 | LangGraph agents (scalable: `--scale agent-worker=3`) |
| `retriever` | 8001 | Member 2 | Corpus index and retrieval tools |
| `llm-stub` | 8002 | Member 3 | Fake OpenAI-compatible LLM for load tests |
| `postgres`, `redis` | internal | Member 1 | Run state, queue, caches |
| `prometheus`, `grafana`, `jaeger`, `docker-exporter` | 9090, 3000, 16686 | Member 1 | Metrics, dashboards, traces, per-container resources |

## Common tasks

```bash
docker compose run --rm api python -m pytest -q tests        # API integration tests (stack must be up)
docker compose up -d --scale agent-worker=3                  # more workers
loadtest/sweep.sh workers1 1 5 10 20                          # load test (see loadtest/SLO.md first)
python3 ops/grafana/build_dashboards.py                       # regenerate dashboards after editing
bash scripts/check_no_secrets.sh                              # D4 check
docker compose logs -f api agent-worker                       # JSON logs (filter by run_id / correlation_id)
docker compose down -v                                        # stop and delete all data
```
**Corpus and index (D2).** The retriever builds its index on first start (about 50 s). To rebuild or inspect it:
```bash
docker compose run --rm retriever python -m retriever.ingest build     # idempotent: a second run embeds 0 chunks
docker compose run --rm retriever python -m retriever.ingest status
docker compose run --rm retriever python -m retriever.ingest reembed --model <sentence-transformers model>
curl -s localhost:8001/index/info                                      # built_at, sources + sha256, chunk count
```
Design: [`docs/retrieval_design.md`](docs/retrieval_design.md). Sources: [`corpus/SOURCES.md`](corpus/SOURCES.md).

**Evaluation batch (L3, L2).** 28 scenarios in `eval/scenarios.jsonl`, run through the public API:
```bash
docker compose run --rm retriever python eval/run_eval.py --label my-run          # all scenarios
docker compose run --rm retriever python eval/run_eval.py --label quick --only S01,S02,S22
```
Results go to `eval/results/<timestamp>_<label>/`. How each metric is computed: [`eval/METRICS.md`](eval/METRICS.md). Before/after: [`eval/BEFORE_AFTER.md`](eval/BEFORE_AFTER.md). Prompt v1 vs v2: [`eval/PROMPT_COMPARISON.md`](eval/PROMPT_COMPARISON.md).

**Agent tests (A1–A5, L4).** `docker compose run --rm agent-worker python -m pytest -q tests`. Agent design: [`docs/agent_design.md`](docs/agent_design.md). Demo steps for all 10 items: [`docs/demo_script.md`](docs/demo_script.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| `ports are not available … address already in use` | Another app uses that port. Add e.g. `GRAFANA_HOST_PORT=3001` or `API_HOST_PORT=8080` to `.env` (all names are listed at the top of `.env.example`) |
| `api` shows `"status":"degraded"` in `/health` | The retriever is not ready (it may still be building its index). See the runbook |
| Runs stay `queued` | No worker running: `docker compose ps agent-worker`, then `docker compose logs agent-worker` |
| Runs come back `degraded` | The LLM provider is failing or its daily quota is spent (Groq: 200k tokens/day/model). See the runbook |
| Runs take 2–4 minutes | Normal on a free tier: the client waits out the per-minute token limit |

More: [`docs/runbook.md`](docs/runbook.md) · [`docs/incident_log.md`](docs/incident_log.md)

## Repository map

```
services/api            gateway + web client (M1)           services/retriever     retrieval (M2)
services/agent_worker   agents (M3)                         services/llm_stub      LLM stub (M3)
shared/contracts        request/result/passage models       db/init.sql            schema
ops/                    prometheus, grafana, docker-exporter loadtest/             Locust, SLO, results
eval/                   evaluation set + runner (M2)        prompts/               versioned prompts (M3)
corpus/raw              source PDFs (M2)                    docs/                  architecture, decisions, runbook, report
```

## Team

| Member | Area |
|---|---|
| Member 1: Sai Nikitha Perumalla (PES2UG24AM142) | Platform, API & Ops |
| Member 2 (satwik-0110) | Corpus, Retrieval & Evaluation |
| Member 3 (Sanshray10) | Agents & LLM |
