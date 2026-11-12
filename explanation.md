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
I look after the *knowledge* of the system. The system must give a tariff code (an HS code, a number that says what kind of goods something is) and say if the goods can be exported. To do that, it must read the real legal texts. My job is to get those texts, cut them into small legal pieces, and let the agents search them. I also measure with numbers whether the answers really come from the texts. Right now, only the first step is done: the legal texts are collected and checked.

### 2. What I built
- **The corpus** (the set of legal documents), in `corpus/raw/`. These are 8 official PDF files from CBIC (the customs department) and DGFT (the export department). They hold the classification rules (GRI), the Section XV notes, Chapters 73 and 96, and the export policy.
- **The source list**, `corpus/SOURCES.md`. For each file it gives the title, who published it, the web address, the version and a sha256 hash (a fingerprint that proves the file did not change).
- **The Evaluation 1 paper**, `docs/eval1_corpus_confirmation.md`. It quotes the exact passages the vacuum flask case needs, and gives the test requests and the expected answers.
- **A change proposal**, `docs/contract_changes.md`. It asks the team to agree on a name for the export-policy "default rule" passage.
- **Not built yet:** the ingestion tool, the search service, the cache, the evaluation set and the live scoring.

### 3. How a request moves through my part
Today no request reaches my part yet, because the search service is not built. Later it will work like this:
1. The agent sends my search service a question, for example "vacuum flask".
2. My service searches the legal pieces by words and by meaning.
3. It sends back the best pieces, each with its ID (for example `HDG-9617`).
4. The agent can ask for one piece by its ID, or for the notes that apply to a heading.

### 4. The vacuum flask example
The product is a "stainless steel vacuum flask with a moulded plastic outer body". It is mostly steel, so a simple search finds Chapter 73 (things made of iron or steel), heading 7323. That is wrong. I found the passages that show why:
- **GRI 1** says: classify by the words of the headings and the notes, not by the chapter title.
- **Heading 9617** in Chapter 96 says "Vacuum flasks and other vacuum vessels". It names the article directly.
- **Section XV Note 1(m)** says the steel section "does not cover … other articles of Chapter 96". So heading 7323 is out.
- **Tariff items**: 9617 00 11 is for flasks up to 0.75 litre, and 9617 00 12 is for bigger flasks. The sentence does not give the size, so we must ask for it, or test with "500 ml".
- **Export policy**: 9617 is not in DGFT's export list, so General Note 1 makes it "Free" (no licence needed).

### 5. How to run and show it
Nothing runs yet. To check that a corpus file is the original one, compare its fingerprint with `corpus/SOURCES.md`:
```
sha256sum corpus/raw/cbic_tariff_ch96.pdf
```
You should see `7cb3a012…43ac`, the same value as in the table.

### 6. Which requirements I covered
- **§3 corpus**: done. The files are in `corpus/raw/`, with `corpus/SOURCES.md`.
- **Evaluation 1 corpus confirmation**: draft done in `docs/eval1_corpus_confirmation.md`.
- **D2, L1, D7, L3, L2, L6**: not started yet.

### 7. Viva questions
1. *Where did the documents come from?* From the official CBIC and DGFT websites. The links and fingerprints are in `corpus/SOURCES.md`.
2. *Did you need OCR (turning a picture of text into real text)?* No. Every PDF already has a text layer. I checked every page.
3. *Why is the vacuum flask not in Chapter 73?* Section XV Note 1(m) says the steel section does not cover articles of Chapter 96, and heading 9617 names vacuum flasks.
4. *Which GRI rules decide it?* GRI 1 picks the heading. GRI 6 picks the 8-digit line inside the heading. GRI 3 is not needed, because only one heading is left.
5. *What is the export policy and why?* "Free". 9617 is not listed in DGFT Schedule 2, and General Note 1 says goods not listed are freely exportable.
6. *Why two test requests for the flask?* The 8-digit code depends on the size (up to or over 0.75 litre), and the sentence does not say the size. A careful system asks instead of guessing.

### 8. What did not work / limits
- The old CBIC website (`old.cbic.gov.in`) no longer works. I had to use the new site's hidden download address.
- The course Google Drive folder had no corpus files, only the project papers.
- The newest full DGFT export list I could find is marked "ITC (HS) 2018". The faculty must confirm it is fine.
- The search service and the evaluation are not built yet.

## Member 3 — Agents & LLM

_(Member 3 writes this section.)_
