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

### 1. My job in one paragraph
I built the "brain" of the system. My part reads the product description and finds the right tariff heading, the way a trade-compliance analyst does. It names the rule it used and gives quotes from the tariff as proof. The hard part is **knowing when not to answer**. My part checks its own answer against the text it found. If the answer is not supported, it searches again. If it still cannot support the answer, it hands the case to a human (this is called **escalation**). It never files anything.

### 2. What I built
- **Agents** (`services/agent_worker/agent_worker/agents/`). Three agents (small AI workers, each with one job). Each one has its own prompt, its own tools and its own limits:
  - **Intake agent** (`intake.py`). It reads the request and writes down what the thing is (the "article"), what it is for, and what it is made of.
  - **Classifier agent** (`classifier.py`). It searches the tariff like an analyst. It decides by itself which search tool to call next. It then proposes a heading, the rule used, and quotes.
  - **Verifier agent** (`verifier.py`). It checks the classifier's answer **before** anyone sees it. Normal code (not the AI) checks that every quote really appears in a passage we found in this run. After that, an AI check asks: "do these passages really support the answer?"
- **Router** (`agents/router.py`). It looks up the export policy and chooses one of the three routes. Normal code decides the route, not the AI. So a user cannot trick the AI into saying "clear-for-filing".
- **The graph** (`graph.py`). LangGraph (a library that connects agents like boxes and arrows) joins the agents. It also sends a failed answer back for a second try.
- **Tools** (`tools.py`). These are read-only searches of Member 2's retriever: search, get a clause by its ID, get the notes for a heading, and get the export policy.
- **LLM client** (`llm/`). This is the one door to the AI model (LLM = large language model). It has a time limit on every call. It retries with growing waits. A **circuit breaker** (like a fuse in a house) stops calling a broken provider for 30 seconds. Then a backup provider is tried, and then a "degraded" answer is given. It also records tokens and cost for every call.
- **Guardrails** (`guardrails.py`). Safety checks:
  - It blocks prompt injection (text that tries to give orders to the AI).
  - It checks for toxic language with a small local model called detoxify.
  - It removes words the system is not allowed to say, like "final" or "filed", or a duty amount.
- **Prompts** (`prompts/`). The AI instructions are kept as versioned files. `classifier@v1` lets the model reason freely. `classifier@v2` gives it a strict step-by-step list of the rules. Every result records which version was used.
- **LLM stub** (`services/llm_stub/stub.py`). A fake AI server for load tests. It answers in the same format as a real one after 1.5–4 seconds, so a full run works with no real AI.
- **Fake retriever** (`services/agent_worker/tests/fake_retriever.py`). A small stand-in for Member 2's search service, used only in tests. Its text is copied from the official Customs Tariff Act PDF.

### 3. How a request moves through my part
1. A worker takes the job from the queue. It loads the request from the database and marks it "running".
2. **Input guard:** it checks every text field for injection and toxic words. If a check fires, it stops and escalates.
3. **Intake agent:** it extracts the article, its use and its materials.
4. **Classifier agent:** it searches, reads the notes, searches again, and applies the rules (the GRI, the General Rules for Interpretation) in order. Then it submits a draft with quotes.
5. **Verifier agent:** it checks every quote and every rule. If a check fails, the classifier tries again with a different search plan (at most 2 more times).
6. **Router:** it gets the export policy and picks the route. It also cleans the text and adds the disclaimer.
7. The final result is saved. **Every step** (each AI call, each search, each check) is saved as one row. So the whole run can be rebuilt later.

### 4. The vacuum flask example
For *"Stainless steel vacuum flask with a moulded plastic outer body."*:
- The intake agent says: the article is a "vacuum flask", made of stainless steel and plastic.
- The first search finds **Chapter 73** (articles of steel, heading 7323). A simple system would stop here.
- The classifier reads the notes for Chapter 73. **Section XV Note 1(m)** says this section does not cover "articles of Chapter 96".
- It searches for a heading that **names** the thing. It finds **heading 9617, "Vacuum flasks and other vacuum vessels"**.
- **GRI 1** says: decide by the words of the headings and the notes. So the answer is 9617.
- The verifier checks that the quotes from GRI 1, heading 9617 and Note 1(m) really appear in the found text.
- Then there is a catch. In the official tariff, 9617 splits by size: **9617 00 11** is for flasks up to 0.75 litre, and **9617 00 12** for bigger ones. The description gives no size. So the route is **seek-product-clarification**: "please tell us the capacity". If you add "Capacity 1 litre.", the route becomes **clear-for-filing** with **96170012**.

### 5. How to run and show it
```bash
docker compose build agent-worker llm-stub
docker compose run --rm agent-worker python -m pytest -q tests      # all my tests
docker compose -f docker-compose.yml -f services/agent_worker/tests/compose.fake-retriever.yml up -d --build
docker compose exec redis redis-cli SET ecs:chaos:llm_fail all   # make the AI "break" (demo #8)
docker compose exec redis redis-cli DEL ecs:chaos:llm_fail       # fix it again
```
With the fake retriever running, submit the flask in the web page at http://localhost:8000/ui. You should see heading 9617, the citations, and the route. `GET /runs/{id}/trace` shows every step. The exact demo steps are in `docs/agent_design.md`, section 8.

### 6. Which requirements I covered
- **F3**: the intake agent (`agents/intake.py`).
- **F4**: the classifier tools, including the name search and the notes lookup (`tools.py`, `agents/classifier.py`).
- **F5**: a draft with the heading, the GRI rule and quotes, checked by the verifier.
- **F6 / F7**: the router rules in `agents/router.py`. It escalates for: out of scope, two equal headings after GRI 3, failed checks, the AI being down, or a limit being hit.
- **A1**: LangGraph, 5 tools, and limits on steps, tool calls and time (`recorder.Budget`).
- **A2**: 3 agents with a typed hand-off. `docs/agent_design.md` explains what happens when each one fails.
- **A3**: the verifier, with code checks, an AI check and up to 2 retries.
- **A5**: timeouts, retries, the shared circuit breaker, a backup provider and degraded mode (`llm/`).
- **A6**: the worker sends its numbers to Prometheus on port 9100 (`metrics.py`).
- **L2**: the prompt files with versions, two classifier versions, and the version saved on every step.
- **L4**: injection, toxicity and output filtering (`guardrails.py`).
- **L5**: tokens and cost for every step and every run. The report is in `docs/cost_report.md`.

### 7. Viva questions
1. **Why is this an agent and not a pipeline?** The classifier decides by itself which search to run next. The verifier can send the answer back to search again. A pipeline always runs the same fixed steps.
2. **Why are there two (three) agents and not one prompt?** Each agent has its own job, prompt, tools and limits. For example, only the classifier can search, and only the router can look up policy. When one fails, the others react in a defined way.
3. **How do you know a citation is real?** Normal code checks that the quote appears, letter by letter, in a passage that was found during this run. The AI cannot fake this check.
4. **What happens if the AI provider is down?** We retry with growing waits. Then the circuit breaker opens, so we stop calling it. Then we try the backup provider. If all of that fails, we return a "degraded" result: candidate headings only, no code, sent to a specialist.
5. **What does the circuit breaker store, and where?** It stores the failure count and the "open until" time in Redis (a fast memory store that all workers share). So all 3 workers see the same state.
6. **How do you stop prompt injection?** We check every text field for order-like text. Customer text is placed inside `<product_data>` tags and called "data". The route is decided by normal code. If injection is found, the run goes to a human.
7. **Why not just strip the bad text and continue?** Removing only part of an attack can leave some of it behind for an AI that holds tools. Sending it to a human is safer and cheap.
8. **Where does the cost come from?** The classifier is 93% of the cost. In a tool loop, every search result is sent back to the model again on every turn. So the prompt grows from about 700 to 3,500 tokens over one attempt. Each AI call stores its tokens and cost in its own step row. With the stub, 100 runs cost about $1.04 at our notional prices.

### 8. What did not work / limits
- Member 2's real retriever is not merged yet. So far I tested with my fake retriever (real tariff text, but only a handful of passages).
- I could not reach an official DGFT export-policy file for heading 9617. The "Free" rows in the fake retriever are marked UNCONFIRMED.
- The injection check uses patterns (a list of known attack phrases). A new kind of attack worded differently could get past it. The delimiters and the code-based routing are the second line of defence.
- The real-AI cost per 100 runs is not measured yet. The numbers in `docs/cost_report.md` come from the stub ($1.04 per 100 runs). A real provider also bills the tool descriptions, so expect about 1.5–2× more.
- What I did test for real, through the API: the flask (about 21 s with the stub), the capacity case, the laptop, injection, and the circuit breaker opening and closing again. With 3 workers (`--scale agent-worker=3`), all 3 shared the jobs and Prometheus saw all 3.
