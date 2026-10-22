# Service level objective (D6) — declared BEFORE any measurement

**Declared:** 2026-10-22, in the skeleton commit, before any load test was run. The git history of this
file is the proof that the target was not chosen after seeing the results.

## The target

> **p95 of a complete run ≤ 60 seconds, with 10 concurrent clients, and fewer than 1 % of runs failing or timing out.**

"Complete run" means **from `POST /runs` until `GET /runs/{id}` returns a final status**
(`completed | escalated | degraded | failed`), not just the submission call. Locust records it
as the custom request `RUN complete_run` (see `locustfile.py`).

## Why this number (justified against §1 of the spec)

- The user is a trade-compliance analyst classifying a shipment **before** it is booked and declared.
  Customs holds and penalties come from *wrong* classification, not from waiting a minute for a
  proposal. So accuracy and escalation matter more than speed, and seconds-level latency is not needed.
- But the analyst submits a case and waits for it while working. Beyond about one minute they
  switch tasks and the tool stops being useful in the workflow. That gives the 60 s ceiling.
- A run makes several model calls (extraction, classification with retrieval loops, verification,
  possibly a retry with a different strategy). At the stub's 1.5–4 s per call (`STUB_DELAY_*`), a
  normal run takes roughly 10–25 s, so 60 s at p95 leaves room for one verification retry.
- 10 concurrent clients is a realistic peak for a compliance desk of a mid-size exporter.
- The 1 % failure budget covers provider blips. Any run that does not complete must come back
  `degraded`/`failed`, never as a confident answer (A5).

## How it is measured

- Locust drives the full API with the LLM replaced by `llm-stub` (fixed responses after a realistic
  delay), so the test measures **our system**, not the provider's free-tier rate limits.
- Concurrency sweep: 1, 5, 10, 20, 40, 80 users. Report RPS, p50 and p95 against the target. Find the
  first concurrency at which the target fails, and the component responsible (Grafana: queue depth,
  worker CPU, retriever latency, DB).
- Repeat at `--scale agent-worker=3`, and with the run cache on vs off (D7).
