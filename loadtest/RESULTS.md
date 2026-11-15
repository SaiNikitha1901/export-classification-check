# Load test results (D6, A7, D7)

**Target (declared 2026-10-22 in `SLO.md`, before any measurement):** p95 of a complete run (submission → final result) **≤ 60 s at 10 concurrent clients**, failures < 1%.

**Setup (2026-11-15):** full stack under Docker Compose on one MacBook (Apple Silicon, 10 cores, 16 GB; Docker VM 7.75 GB), LLM replaced by `llm-stub` (fixed, parseable responses after a uniform 1.5–4 s delay; about 8 LLM calls per run). Locust closed loop: each simulated analyst submits, polls every 1 s until the run is final, then waits 1–3 s. Each step runs 3 minutes. The queue is drained before each step, and in-flight runs finish after the stop (`--stop-timeout`). `CACHE_MODE=unique` (cache never hits) unless stated. Raw CSVs are in `results/`.

**Every one of the 627 load-test runs ended `completed` or `escalated`** (checked in Postgres): none failed or degraded, and no worker logged an error. "Cut off" means a run still in progress when Locust stopped that finished just after; it is reported, not counted as a failure.

## 1 worker
| users | runs finished | runs/s | p50 (s) | p95 (s) | cut off | failed | SLO |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 0.044 | 20 | 25 | 1 | 0% | ✅ |
| 2 | 10 | 0.049 | 34 | 44 | 1 | 0% | ✅ |
| 5 | 13 | 0.050 | 89 | 99 | 1 | 0% | ❌ |
| 10 | 18 | 0.051 | 171 | 184 | 1 | 0% | ❌ |

## 3 workers (`docker compose up --scale agent-worker=3`)
| users | runs finished | runs/s | p50 (s) | p95 (s) | cut off | failed | SLO |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 0.041 | 23 | 26 | 1 | 0% | ✅ |
| 5 | 30 | 0.146 | 31 | 40 | 1 | 0% | ✅ |
| **10** | 35 | 0.150 | 60 | **71** | 1 | 0% | ❌ |
| 20 | 46 | 0.155 | 111 | 129 | 1 | 0% | ❌ |

## 5 workers
| users | runs finished | runs/s | p50 (s) | p95 (s) | cut off | failed | SLO |
|---|---|---|---|---|---|---|---|
| **10** | 53 | 0.244 | 36 | **46** | 1 | 0% | ✅ |

## Verdict
- **The target is not met with 1 or 3 workers.** With 1 worker it first fails at **5 users** (p95 99 s); with 3 workers at **10 users** (p95 71 s, against 60 s).
- **It is met with 5 workers:** p95 **46 s** at 10 users.
- **The effect of `--scale`:** throughput is capped at **0.05 runs/s per worker** and grows linearly: 1 worker 0.051 → 3 workers 0.155 (**3.0×**) → 5 workers 0.244 (**4.8×**). Under load, p95 is queueing time: runs wait for a free worker.

## The bottleneck: one run in flight per worker
- **Evidence:**
  - Throughput tracks the worker count almost exactly.
  - With 5 workers at 10 users, `docker stats` shows each worker at **under 1% CPU** and about 330 MB, the retriever at 1% CPU, and Postgres at 0.7% (`results/workers5_u10_docker_stats.txt`).
  - Nothing is CPU- or memory-bound. Each worker is idle, waiting on its LLM call, and an RQ worker runs one job at a time.
- **Component responsible:** the agent-worker pool size. A single run is about 22 s of serial LLM waits, so each worker completes at most ~0.045 runs/s.
- **Fixes:** more replicas (shown above, cheap at ~330 MB each), or concurrent jobs per worker (async LLM calls). Either way, the next limit in production is the **LLM provider's rate limit**: Groq's free tier allows 8,000 tokens/minute and 200,000/day per model, so it caps real throughput long before our workers do.

## Run cache on vs off (D7), 3 workers, 5 users
| mode | runs finished | runs/s | p95 (s) | mean cost per run |
|---|---|---|---|---|
| cache off (`CACHE_MODE=unique`) | 28 | 0.13 | 43 | $0.0083 (13.4k prompt tokens) |
| cache on (`CACHE_MODE=repeat`, after one warm-up pass) | 184 | **1.00** | **17** | **$0** on a hit (0 tokens); the mean depends on the hit rate |

- **p95 −60%, throughput 7.5×.** A hit is answered from Redis in milliseconds, and the remaining p95 comes from the few misses.
- **Rate limiting worked as cost control:** with answers this fast, one simulated client exceeded **20 submissions/minute** and got 3 × HTTP 429 with `Retry-After`.
- **Cost per 100 runs with the stub:** $0.83, against $1.04 before the token cut (PR #7).

## How to reproduce
```bash
docker compose up -d --build --wait                      # LLM_BASE_URL must point at llm-stub (the .env.example default)
loadtest/sweep.sh workers1 1 2 5 10
docker compose up -d --scale agent-worker=3 && loadtest/sweep.sh workers3 1 5 10 20
docker compose up -d --scale agent-worker=5 && loadtest/sweep.sh workers5 10
CACHE_MODE=unique loadtest/sweep.sh cache-off 5
CACHE_MODE=repeat loadtest/sweep.sh cache-warm 5 && CACHE_MODE=repeat loadtest/sweep.sh cache-on 5
```
Afterwards, check that every run ended well and that the workers logged nothing at ERROR (incident 3):
```bash
docker compose exec postgres psql -U ecs -d ecs -c "select status, count(*) from runs where client_id like 'locust-%' group by 1"
docker compose logs agent-worker | grep -c '"level": "ERROR"'      # 0
```
