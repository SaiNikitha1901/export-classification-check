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
I look after the *knowledge* of the system. The system must give a tariff code (an HS code, a number that says what kind of goods something is) and say if the goods can be exported. To do that, the agents must read the real legal texts. My job is to collect those texts, cut them into small legal pieces, and run a search service (the "retriever") that the agents call. Later I also measure with numbers whether the answers really come from the texts. The texts and the search service are built and working. The evaluation part is not built yet.

### 2. What I built
- **The corpus** (the set of legal documents), `corpus/raw/`. 8 official PDFs from CBIC (customs) and DGFT (exports). `corpus/SOURCES.md` lists each file's web address, version and sha256 (a fingerprint that proves the file did not change). `corpus/sources.json` tells the program which pages to read.
- **The parser**, `services/retriever/retriever/ingest/parsers.py`. It cuts the PDFs into **legal units**, not fixed-size pieces: each rule, each note, each heading, each 8-digit tariff line and each export-policy row. Each piece gets an ID, like `HDG-9617` (heading 9617) or `SEC-XV-NOTE-1` (Section XV, Note 1). The result is 438 pieces ("chunks").
- **The text repair**, `ingest/textnorm.py`. The PDFs come out with broken words ("V ACUUM"). It joins them back only if the whole word appears elsewhere in the same documents, so it never invents text.
- **The ingestion tool** (a command-line program), `ingest/pipeline.py`. It turns every chunk into an embedding (a list of numbers that captures the meaning) with a free local model, and stores them in **Chroma** (a vector database) through **LangChain**. Running it twice changes nothing. It can switch to a new model without re-reading the PDFs.
- **The search service**, `retriever/app.py` and `retriever/index.py`, on port 8001. It searches by words (BM25) and by meaning (embeddings), and mixes the two lists. It also finds the notes for a heading, and the export policy for a code.
- **The cache**, `retriever/cache.py`. It keeps recent search results and query embeddings in Redis (a very fast shared memory store), so repeated questions are answered at once.
- **Tests**, `services/retriever/tests/`. 18 automatic tests, all passing.
- **Documents:** `docs/retrieval_design.md` (why the design solves the flask problem), `docs/eval1_corpus_confirmation.md` (passages and expected answers for Evaluation 1), two real problems in `docs/incident_log.md` (#4, #5), and proposal #7 in `docs/contract_changes.md`.

### 3. How a request moves through my part
1. When the container starts, it checks the index. If there is none, it reads the PDFs and builds the index (about 50 seconds the first time).
2. Until the index is ready, `/health` says "not ready", so the other services wait.
3. An agent sends a question to `POST /search`, for example "vacuum flask".
4. If the same question was asked before, the answer comes from the cache.
5. If not, the service searches by words and by meaning, mixes the two rankings, and returns the best pieces with their IDs.
6. The agent can then ask for one piece by its ID (`/clause/HDG-9617`), for the notes that apply to a heading (`/notes/applicable/HDG-7323`), or for the export policy (`/policy/96170011`).

### 4. The vacuum flask example
*"Stainless steel vacuum flask with a moulded plastic outer body."*
- The search returns **heading 9617 first** ("VACUUM FLASKS AND OTHER VACUUM VESSELS"). This works because each heading is its own piece and starts with its own words, and because the word search matches "vacuum flask" exactly.
- A material-first answer would be heading 7323 (household articles of steel). `/notes/applicable/HDG-7323` returns **Section XV Note 1**, which says that section "does not cover … other articles of Chapter 96". So 7323 is out.
- `/clause/GRI-1` gives the rule: classify by the words of the headings and the notes.
- `/policy/96170011` says **Free**. 9617 is not in DGFT's export list, so General Note 1 applies.
- The 8-digit code depends on the size: up to 0.75 litre is 9617 00 11, bigger is 9617 00 12.

### 5. How to run and show it
```
docker compose up -d --build --wait
docker compose run --rm retriever python -m retriever.ingest status
curl -s -X POST localhost:8001/search -H "Content-Type: application/json" -d '{"query":"vacuum flask","mode":"keyword","k":3}'
docker compose run --rm retriever python -m pytest -q tests
```
You should see: the status shows 438 chunks; the search shows `HDG-9617` first; the tests say `18 passed`. Run `ingest build` a second time and it says `"embedded_chunks": 0` (nothing changed).

### 6. Which requirements I covered
- **§3 corpus:** done. `corpus/raw/`, `corpus/SOURCES.md`.
- **D2:** done. Idempotent `ingest build`, `manifest.json`, `/index/info`, metrics `ecs_index_chunks`, `ecs_index_built_timestamp`, `ecs_ingest_chunks_per_second`.
- **L1:** done. LangChain + Chroma, structure-aware chunks, `ingest reembed --model X` with an atomic switch.
- **D7 (my part):** done. Embedding and search cache in Redis. The effect on p95 is not measured yet (needs the load test).
- **F4 (retriever side):** done. Headings that name the article, plus the notes that apply to them.
- **Evaluation 1 corpus confirmation:** done (`docs/eval1_corpus_confirmation.md`). The PDF export is still to do.
- **L3, L2, L6 (scoring):** not started.

### 7. Viva questions
1. *Why not cut the PDFs into equal pieces?* A legal rule must stay whole. The heading's own words must sit in one piece, so a search for "vacuum flask" finds heading 9617 directly.
2. *Why search by words and by meaning?* Meaning-search mixes up similar things ("steel flask" looks like other steel goods). Word-search finds the exact name. We use both and mix the rankings.
3. *How does the agent find a note the question never mentions?* Notes are linked to headings by their chapter and section, not by similarity. `/notes/applicable/HDG-7323` always returns the Section XV notes.
4. *What does "idempotent" mean here?* Running `build` again does nothing new. Each piece's ID is a fingerprint of its text, so only new or changed pieces are embedded.
5. *How do you change the embedding model?* `ingest reembed --model X` fills a new collection next to the old one, then switches with one file swap. The service picks it up without a restart.
6. *What do you cache, and when does the cache become wrong?* Query embeddings and search results. The key includes the index build time, the collection and a ranker version, so a rebuild or a code change gives new keys.
7. *Why is the export policy "Free" when there is no row for 9617?* DGFT General Note 1 says goods not listed in the schedule are freely exportable.
8. *Where does the model run? Does it cost money?* On our own CPU, inside the container. It is free and needs no API key.

### 8. What did not work / limits
- The old CBIC website no longer works. I used the new site's own download address.
- The newest full DGFT export list I found is marked "ITC (HS) 2018". The faculty must confirm it is acceptable.
- The PDFs break some words. My repair is a careful guess, and tests protect the important passages.
- The cache once served old results after a code change (incident #4). `reembed` once crashed on a long model name (incident #5). Both are fixed.
- The first start needs internet to download the model (about 90 MB).
- The evaluation set, the batch runner, the quality metrics and live scoring are not built yet.

## Member 3 — Agents & LLM

_(Member 3 writes this section.)_
