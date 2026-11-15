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

### 4. Retriever served stale rankings from the Redis cache after a ranking fix (2026-11-12, Member 2)
- **Seen:** after changing how BM25 scores tariff lines (so heading 9617 outranks its own tariff lines on "vacuum flask"), a one-off script showed the new ranking, but the API test `test_keyword_search_vacuum_flask_top3` still failed with the old ranking.
- **Found:** the test response had `cache_hit: true`. The search-cache key contained the index `built_at`, the collection and the query parameters, but nothing about the ranking *code*. The index had not been rebuilt, so the key was unchanged and Redis returned the result computed by the old code.
- **Root cause:** the cache key did not cover every input that decides the result.
- **Fix:** a `RANKER_VERSION` constant is now part of every search-cache key (`services/retriever/retriever/index.py`). It must be bumped whenever ranking logic changes. A rebuild or re-embed still invalidates the cache through `built_at` and the collection.
- **Prevention / lesson:** a cache key must include the code version as well as the data version. When a test fails right after a fix, check `cache_hit` before debugging the logic.

### 5. `ingest reembed` crashed: Chroma rejected the collection name (2026-11-12, Member 2)
- **Seen:** `python -m retriever.ingest reembed --model sentence-transformers/paraphrase-MiniLM-L3-v2` exited with `ValueError: Expected collection name that … starts and ends with an alphanumeric character`. The default model had worked.
- **Found:** the collection name was the model slug cut at 40 characters. For this longer model name, the cut ended on a `-`.
- **Root cause:** truncating without re-checking Chroma's naming rules. The default model was short enough to hide the bug.
- **Fix:** the name is now `chunks-<slug up to 32 chars, dashes trimmed>-<8-char sha256 of the model name>`. It is always valid, and two long model names can no longer collide. Re-embedding then took 3.5 s for 438 chunks, and the running service switched to the new collection without a restart.
- **Prevention:** after any change to the pipeline, run `reembed` by hand with a second, longer model name (not yet an automated test). The steps are in `docs/retrieval_design.md` §5.

### 6. `/clause/GRI-3(b)` returned 404 (2026-11-12, Member 2)
- **Seen:** validating `eval/scenarios.jsonl` against the corpus (every supporting clause must resolve) failed for `GRI-3(a)`, `GRI-3(b)` and `GRI-3(c)`. `/clause/GRI-3` (prefix) and `/clause/GRI-1` worked.
- **Found:** `/clause` upper-cased the whole ID, turning `GRI-3(b)` into `GRI-3(B)`, which matches nothing. The existing tests only used IDs without a sub-rule letter.
- **Impact if missed:** Member 3's verifier calls `/clause` to check citations, so any answer citing GRI 3(b) (composite goods and sets) would have failed verification and escalated.
- **Fix:** `Index.normalise_clause_id` upper-cases the ID but keeps sub-rule letters lower case. A regression test (`test_clause_with_sub_rule_letter`) covers `GRI-3(b)`, `gri-3(b)` and `GRI-2(a)`.
- **Lesson:** validate test data against the real service. The scenario check found a bug that 18 passing tests did not.

### 7. Evaluation metrics: two code bugs and one misleading definition, caught before reporting (2026-11-12, Member 2)
- **Seen:** (a) a unit test on a hand-made run showed the lexical judge rejecting the correct claim "Tariff item 96170011 covers vacuum flasks". (b) Another showed "Verified; policy Free." not being split into two claims. (c) The first real batch reported groundedness **0.03**, which was implausibly low.
- **Found:** (a) the 8-digit code counted as a "word", but the corpus prints codes as "9617 00 11", so the word never matched and pushed correct claims under the 60% threshold. (b) The splitter only split before a capital letter. (c) 23 of 25 runs were escalations with no citations, whose summaries are process statements ("No verified classification. The agent hit a loop limit…"). Scored against no passages, they were always 0.
- **Fix:** (a) codes are checked separately (spacing-insensitive) and no longer counted as words. (b) Split on every `;`. (c) Groundedness is now *not applicable* to runs without citations and is reported with its coverage (`groundedness_runs`); the definition is in `eval/METRICS.md`. A `--rescore` mode re-scores finished batches from their stored traces, so every compared batch uses identical metric code.
- **Lesson:** test the metric code like product code, and sanity-check every metric's first real number before believing it.

### 8. Real retriever exited on start: an inline comment became a setting's value (2026-11-15)
- **Seen:** PR #3's `integration` CI job failed: the retriever exited with `FORCE_SEARCH_MODE must be dense, keyword or hybrid, not '# leave empty; "dense" only for the L3 before/after batch'`.
- **Found:** `docker compose config` showed `FORCE_SEARCH_MODE` and `LLM_FORCE_FAIL` set to their comment text.
- **Root cause:** in PR #2, Member 1 wrote empty values with an inline comment (`X=    # note`). Compose reads that as the value `# note`, not as empty. `main`'s CI missed it because the placeholder services never read those settings.
- **Fix:** PR #4. The comments moved to their own lines, and `scripts/check_no_secrets.sh` (run in CI) now rejects the pattern.
- **Prevention:** that CI check, and testing a feature branch merged with `main` before relying on `main`'s green CI.

### 9. Every real-model run degraded: the free tier's 8k tokens/minute tripped the circuit breaker (2026-11-15)
- **Seen:** the first runs on Groq `gpt-oss-120b` (decision D2) all came back `degraded`. Worker traces showed `HTTP 429` on the third classifier turn, then `primary: circuit open`.
- **Found:** Groq's response headers: `x-ratelimit-limit-tokens: 8000` per minute and `retry-after: 9`. Each classifier turn re-sends the conversation (~3.3k tokens), so three turns use up the minute.
- **Root cause:** the LLM client treated 429 like an outage. It retried after 0.5–8 s (ignoring Retry-After) and counted every 429 as a breaker failure, so the breaker opened after five.
- **Fix:** 429 now waits for the provider's Retry-After within the run's time budget and does not count against the breaker (contract #16). The time limits were raised to fit 2–4 minute real runs.
- **Also found in the same test:** the verifier rejected a *correct* answer because the model quoted a passage's title and shortened a long note with "...". Quotes from titles, and exact fragments joined by "...", are now accepted. Invented or out-of-order fragments are still rejected (tests in `test_guardrails_verifier.py`).
