# Load test results (D6, A7, D7)

**Target (declared earlier in `SLO.md`):** p95 of a complete run ≤ 60 s at 10 concurrent clients, failures < 1 %.

> Not measured yet. The agents are still placeholders. Real numbers will be filled in once `feature/agents` (real graph + `llm-stub` responses) and `feature/retrieval` are merged. Numbers from the placeholder would measure nothing.

## How to run
```bash
# stack up, LLM pointed at the stub (default in .env.example)
docker compose up -d --build
loadtest/sweep.sh workers1 1 5 10 20 40 80            # 1 worker
docker compose up -d --scale agent-worker=3
loadtest/sweep.sh workers3 1 5 10 20 40 80            # 3 workers (A7)
CACHE_MODE=repeat loadtest/sweep.sh cache-on 10       # run cache can hit (D7)
CACHE_MODE=unique loadtest/sweep.sh cache-off 10      # run cache never hits
```
Checklist after each sweep: save Grafana screenshots (queue depth, worker CPU, retriever p95, run p95) to `results/`, and check `docker compose logs agent-worker | grep '"level": "ERROR"'` is empty (incident 3).

## Results: 1 worker
_(paste the table printed by `summarize.py`)_

## Results: 3 workers
_(table)_. Effect of scaling on throughput and p95:

## First concurrency where the SLO fails, and why
_(component + evidence from Grafana)_

## Run cache on vs off (D7)
| mode | p95 (s) | cost per run (USD) |
|---|---|---|
