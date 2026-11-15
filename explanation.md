# Export Classification Check — How It Works (simple explanation)

Each member writes only in their own section below.

## Member 1 — Platform, API & Ops

### 1. My job in one paragraph
I built the "body" of the system: everything around the agents. My part takes the request from the user and checks it carefully. It puts the work in a waiting line, and it keeps track of every run. It also lets us watch the whole system while it runs. Without my part, the agents would have no way to receive work, no safe way to reject bad input, and nobody could see if something breaks. My part also decides if the project starts at the demo. If `docker compose up` does not work, the project gets zero marks.

### 2. What I built
- **The API** (`services/api/app/main.py`). This is the front door. People send a product description here. It answers at once with a run ID (a ticket number). It does not make you wait for the full answer.
- **Input checking and quarantine** (`shared/contracts/request.py`). Every request is checked before any work starts. Examples: the description must be 10 to 2000 characters. The country must be a real 2-letter code in capital letters. Material shares must add up to 100. If anything is wrong, the request goes to a "quarantine" table (a holding area for rejected requests) with the exact field and the reason. **No agent run starts for a bad request.**
- **The waiting line (queue)** (Redis + RQ). Good requests become "jobs" in a line. Worker containers take jobs from the line one by one. Redis is a very fast memory store that all containers can share.
- **The database** (`db/init.sql`, Postgres). It stores every run, every step of every run, the rejected requests, feedback and evaluation scores.
- **Rate limiting** (`app/ratelimit.py`). Each client can send only 20 runs per minute. This protects our money and our free LLM quota, because one run makes many LLM calls.
- **Run cache** (`app/runcache.py`). If the exact same product was already answered, and the prompt and the document index have not changed, we reuse the old answer. That is faster and costs nothing. Only good, finished answers are reused.
- **Watchdog and callbacks** (`app/background.py`). Every 2 seconds it checks for runs that died or got stuck, and marks them "failed", so nobody waits forever. If a client gave a callback URL, it sends them the answer and tries again if that fails.
- **The web page** (`services/api/static/index.html`, at `/ui`). A simple form. You type a product, press Submit, and see the route, HS code, citations, escalation path and a feedback button.
- **Docker Compose** (`docker-compose.yml`). One file that starts all 10 containers in the right order. Each container has a health check (a small test that says "I am working").
- **Monitoring**:
  - **Prometheus** (a tool that collects numbers from every service every 5 seconds).
  - **Grafana** (a tool that draws those numbers as charts). I made 3 dashboards: service health, agents, and quality and cost.
  - **Jaeger** (a tool that shows the path of one request through all services, like a timeline).
  - **docker-exporter** (`ops/docker_exporter/exporter.py`). My own small program that measures the CPU, memory and uptime of each container.
- **Load test kit** (`loadtest/`). A tool called Locust pretends to be many users at the same time. It measures how long a full run takes. Before testing, I wrote down the target in `SLO.md` (a promise: 95% of runs finish within 60 seconds with 10 users).
- **Documents**: README, architecture, design decisions, data contract, runbook (what to do when things break), incident log (real problems we had), demo script.

### 3. How a request moves through my part
1. The user sends a product description to `POST /runs`.
2. The API looks at who is sending (`X-Client-Id`). Too many requests in one minute → answer "429, try again later".
3. The API checks the input. Bad input → it is saved in quarantine, and the user gets the list of errors. Stop here.
4. The API checks the run cache. Same question answered before → give the old answer at once.
5. The API saves a new run in the database with status "queued".
6. The API puts a job in the waiting line and replies with the run ID.
7. A worker takes the job and does the agent work (Member 3's part). It saves each step and the final answer in the database.
8. The user asks `GET /runs/{id}` every few seconds until the status is final.
9. The user can see every step with `GET /runs/{id}/trace`, and can give feedback.

### 4. The vacuum flask example
For *"Stainless steel vacuum flask with a moulded plastic outer body."*, my part:
- checks that the description is long enough, the country "AE" is valid, and 70% steel + 30% plastic = 100%;
- creates the run, puts it in the line, and gives back a run ID at once;
- shows the answer on the web page when it is ready (the route, the HS code, the rule and the heading cited), with the full trace;
- records how long it took, so Grafana can show it.

If someone sends "flask" with country "xx" instead, my part rejects it, puts it in quarantine, and **no run is created**.

### 5. How to run and show it
```bash
docker compose up -d --build --wait     # start everything
open http://localhost:8000/ui           # the web page; click "Load demo case"
docker compose run --rm api python -m pytest -q tests     # 10 automatic tests
curl -s localhost:8000/admin/stats      # count of runs and quarantined requests
docker compose up -d --scale agent-worker=3               # three workers instead of one
```
On my laptop, port 3000 was busy, so Grafana is at http://localhost:3001 (set in `.env`).

### 6. Which requirements I covered
- **F1**: REST API with a published contract (`docs/data_contract.md`, `/docs`).
- **F2 / D1**: checks for type, range, category and cross-field rules. Quarantine with field errors. Tests prove no run starts.
- **F8**: `/health` and `/metrics` on every service. JSON logs everywhere.
- **A4**: async runs. The API returns the run ID at once, with polling plus an optional callback. RQ queue in between. The reasons are in `docs/design_decisions.md`.
- **A6**: Grafana agents dashboard (success rate, steps, tool calls, latency, retries, uptime). Member 3's worker sends the numbers.
- **A7**: `--scale agent-worker=3` works. Prometheus finds all 3 workers by itself, and jobs are shared 3/3/3.
- **A8**: the web page at `/ui`.
- **D3**: 10 services, one `docker compose up`, health checks. Boundaries explained in `docs/architecture.md`.
- **D4**: no keys or model names in code. Everything comes from `.env`. `scripts/check_no_secrets.sh` checks this.
- **D5**: JSON logs with a correlation ID, Jaeger traces, Prometheus, Grafana, and run rebuild with `/trace`.
- **D6**: SLO written first. Locust kit ready. *Real numbers come after the agents are merged.*
- **D7**: rate limiting and run cache. *The before/after measurement comes after the agents are merged.*
- **D8**: runbook with 2 failure modes, and an incident log with 3 real problems.
- **L6**: feedback endpoint and summary. Grafana panel for quality over time.

### 7. Viva questions
1. **Why not just wait for the answer in the same HTTP request?** A run takes tens of seconds. Long open requests break behind proxies and are lost if the user disconnects. So we return a run ID at once, and the user checks back.
2. **Why polling and not only callbacks?** Polling works for every client, even ones behind a firewall. Callbacks need the client to accept calls from us. We support both, but polling is the main way.
3. **How do you prove a bad request did not start a run?** `/admin/stats` shows the run count does not change and the queue does not grow. An automatic test checks this.
4. **Why a separate container for workers?** So we can add more workers without adding more of everything else. And if one worker crashes, the API still works.
5. **What does the rate limit protect?** Money and the free LLM quota. One looping client could use it all in minutes.
6. **When is the cache not used?** When the prompt version or the document index changes, and for answers that were escalated, degraded or failed.
7. **What is p95?** The time within which 95 out of 100 runs finish. We fixed our target (60 s) before testing, and git history proves it.
8. **What if a worker dies in the middle of a run?** The watchdog sees that the job is dead and marks the run "failed". The user never gets a half answer.

### 8. What did not work / limits
- **cAdvisor** (a common tool for container CPU and memory) could not see containers on Docker Desktop for Mac. I wrote my own small exporter instead (incident 2).
- The real load test numbers and the cache before/after numbers are **not measured yet**. The agents are still a placeholder that always escalates, so measuring now would mean nothing.
- Callbacks have no signing or allow-list yet. That is fine for a local project, but not safe on the internet.
- Cross-field checks (like "shares must add up to 100") run only after each field is valid on its own. So a user may fix one error and then see the next one.

## Member 2 — Corpus, Retrieval & Evaluation

### 1. My job in one paragraph
I look after the *knowledge* of the system and I check its *quality*. The system must give a tariff code (an HS code, a number that says what kind of goods something is) and say if the goods can be exported. To do that, the agents must read the real legal texts. I collected those texts, cut them into small legal pieces, and built a search service (the "retriever") that the agents call. Then I built a test set and tools that measure with numbers whether the answers really come from the texts. All of my part is built and working.

### 2. What I built
- **The corpus** (the set of legal documents), `corpus/raw/`. 8 official PDFs from CBIC (customs) and DGFT (exports), listed with web address, version and sha256 (a fingerprint that proves a file did not change) in `corpus/SOURCES.md`.
- **The parser**, `services/retriever/retriever/ingest/`. It cuts the PDFs into **legal units** (each rule, note, heading, tariff line and export rule), 438 pieces in total. Each piece gets an ID like `HDG-9617`. It repairs broken words, but only with words that already exist in the documents.
- **The ingestion tool** (a command-line program). It turns each piece into an embedding (numbers that capture the meaning) with a free local model and stores them in **Chroma** (a vector database) through **LangChain**. Running it twice changes nothing. It can switch to a new model without re-reading the PDFs.
- **The search service**, `retriever/app.py`, on port 8001. It searches by words and by meaning and mixes the two. It also finds the notes for a heading (`/notes/applicable`) and the export rule for a code (`/policy`).
- **The cache**, in Redis (a very fast shared memory store). Repeated questions are answered at once.
- **The test set**, `eval/scenarios.jsonl`. 28 test products with the correct answer taken from the PDFs, for example the flask, steel bolts, a plastic comb, a laptop (out of scope) and a prompt-injection trick.
- **The batch runner**, `eval/run_eval.py`. It sends all 28 to the system, waits, and scores every answer. The scores are explained in `eval/METRICS.md`.
- **The reports:** `eval/BEFORE_AFTER.md` (one change, measured before and after) and `eval/PROMPT_COMPARISON.md` (two prompt versions).
- **The live scorer**, `retriever/live_scoring.py`. It scores about 1 in 10 real answers automatically, saves the scores, and sends them to Grafana (charts).
- **Tests:** 29 automatic tests, all passing.

### 3. How a request moves through my part
1. At start-up, the retriever builds its index if there is none (about 50 seconds the first time). Until then, `/health` says "not ready".
2. An agent sends a question to `/search`, for example "vacuum flask".
3. The cache answers if it saw the question before. If not, the service searches, mixes the rankings and returns the best pieces with their IDs.
4. The agent asks for exact pieces (`/clause/HDG-9617`), the notes for a heading, or the export rule.
5. When the answer is finished, my live scorer may pick it (1 in 10), check it against the pieces, and save the scores.

### 4. The vacuum flask example
*"Stainless steel vacuum flask with a moulded plastic outer body."*
- Search returns **heading 9617 first** ("VACUUM FLASKS AND OTHER VACUUM VESSELS"), not the steel chapter.
- `/notes/applicable/HDG-7323` returns **Section XV Note 1**: the steel section "does not cover … other articles of Chapter 96". So the steel heading 7323 is out.
- `/policy/96170011` says **Free** (DGFT General Note 1).
- The 8-digit code depends on the size: up to 0.75 litre is 9617 00 11, bigger is 9617 00 12. The sentence gives no size, so the right answer is to ask.

### 5. How to run and show it
```
docker compose up -d --build --wait
curl -s -X POST localhost:8001/search -H "Content-Type: application/json" -d '{"query":"vacuum flask","mode":"keyword","k":3}'
docker compose run --rm retriever python -m pytest -q tests eval/test_metrics.py
docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/run_eval.py --label myrun --fresh
```
You should see: `HDG-9617` first; `29 passed`; and a new folder in `eval/results/` with `summary.md`.

### 6. Which requirements I covered
- **§3 corpus:** `corpus/raw/`, `corpus/SOURCES.md`.
- **D2:** idempotent `ingest build`, `manifest.json`, `/index/info`, freshness metrics.
- **L1:** LangChain + Chroma, legal-unit chunks, `reembed --model X`.
- **D7 (my part):** embedding and search cache in Redis.
- **L3:** 28 scenarios, batch runner, four metrics, before/after report.
- **L2 (running the comparison):** `eval/PROMPT_COMPARISON.md`.
- **L6 (automatic scoring):** the live scorer, `eval_scores` rows, `ecs_eval_score` for Grafana.
- **Evaluation 1:** `docs/eval1_corpus_confirmation.md` and the `.pdf`.

### 7. Viva questions
1. *Why legal-unit pieces, not equal pieces?* A rule must stay whole, and the heading's own words must be in one piece. Then "vacuum flask" finds 9617 directly.
2. *Why search by words and by meaning?* We measured it. Words plus meaning found more of the needed pieces (recall 0.64 → 0.74), and the agent got the right heading 3 times as often.
3. *How is a note found that the question never mentions?* By metadata: every heading knows its chapter and section, so `/notes/applicable` returns all their notes.
4. *What is groundedness?* The share of the answer's claims that the cited texts support. A model (the "judge") checks each claim. It only counts answers that cite something.
5. *What is a hallucination here?* A quote that is not word-for-word in the retrieved text, or a code or rule that does not exist. We found 0 in all 3 test runs.
6. *Which prompt was better?* Version 2 was 41% faster and 18% cheaper. Version 1 found the right heading more often. Both made no wrong confident answers.
7. *Why do most test answers escalate?* We used a small free local model (7B). It often runs out of steps, so the system sends the case to a human instead of guessing. That is safe, but the demo needs a stronger model.
8. *How does live scoring work?* A loop in the retriever picks about 1 in 10 finished real runs, scores them with the same code as the test runs, and saves the scores for Grafana.

### 8. What did not work / limits
- With the small local model, 92–96% of test runs escalated, even the flask. The numbers are honest, but they rest on few answered runs.
- Groundedness was measured on only 1–5 answers per test run, too few to compare.
- The judge is the same small model, so some scores are only rough.
- I did not test equal-size pieces end to end: they have no IDs, so citations would break.
- I found and fixed 4 real bugs (incidents #4–#7 in `docs/incident_log.md`).
- The newest full DGFT list is from 2018. The faculty must confirm it.

## Member 3 — Agents & LLM

_(Member 3 writes this section.)_
