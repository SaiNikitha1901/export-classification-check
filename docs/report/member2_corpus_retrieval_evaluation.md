# Report section (Member 2): corpus, retrieval and evaluation

## 1. Corpus
Eight official PDFs, all with a text layer (no OCR needed), committed in `corpus/raw/` with URL, version and sha256 in `corpus/SOURCES.md`:
- the CBIC Customs Tariff (as on 30.06.2025): the General Rules for Interpretation, the Section XV notes, Chapters 73 and 96, and the Section XX opening (which shows Section XX has no notes);
- the DGFT ITC (HS) Schedule 2 export policy, its General Notes, and the "how to read" note.

The course Drive held no corpus files, and the old CBIC site is gone, so the tariff came from the new CBIC site's own document API.

Two corpus facts shape the system:
1. **Heading 9617 splits by capacity** (≤ 0.75 l → 9617 00 11, > 0.75 l → 9617 00 12), so the §4.1 sentence alone cannot give an 8-digit code (Evaluation 1, `docs/eval1_corpus_confirmation.md`).
2. **DGFT Schedule 2 has no row for Chapter 73 and only one for Chapter 96** (9602 00 30), so for almost every code the export policy is "Free" under General Note 1. We cite that passage as `EXP-GN-1` (contract change #13).

## 2. Chunking and embedding, and how they address §3
§3: some headings describe goods by material ("7323 … of iron or steel"), others by what the article is ("9617 vacuum flasks"). The rules require finding the heading that names the article first, and the note that settles the flask (Section XV Note 1(m)) never mentions flasks.
- **Structure-aware chunks, one per legal unit** (438 chunks): 10 GRI rules, 9 Section XV notes, 6 chapter notes, 45 headings, 364 tariff items, 4 export-policy passages. Each has its contract clause ID. Heading chunks start with the heading's own wording; tariff-item chunks repeat their parent path and heading wording. Duty rates are stripped (out of scope).
- **Hybrid retrieval:** BM25 (tariff items indexed by their own label only) plus dense embeddings (local sentence-transformers via LangChain, Chroma index), merged with reciprocal-rank fusion.
- **Notes by metadata, not similarity:** `/notes/applicable/HDG-7323` returns every Section XV and Chapter 73 note, so the agent sees Note 1(m) without searching for it.
- **Exact citations:** `/clause/{id}` returns the exact passage text, so every quote can be checked as a substring.
- **Text repair without invention:** split words in the PDFs are rejoined only into words that occur elsewhere in the corpus.

Details: `docs/retrieval_design.md`.

## 3. Pipeline and data freshness (D2, L1, D7)
- `python -m retriever.ingest build|status|reembed` runs inside the container. The chunk ID is a hash of document, version, clause and text.
- **Idempotent:** a second build embedded **0** chunks and kept `built_at`.
- **Re-embedding without a rebuild:** `reembed --model X` filled a new Chroma collection in **3.5 s** from the stored chunks, and the running service switched to it without a restart.
- **Freshness:** `manifest.json`, `GET /index/info` and `ecs_index_chunks`, `ecs_index_built_timestamp`, `ecs_ingest_chunks_per_second` report it. The first build took 38 s including the model download (~12 chunks/s overall, ~36 chunks/s for embedding).
- **On a clean clone:** the retriever builds its index on first start, about 50 s, and stays unhealthy until then.
- **Redis caches** hold query embeddings and search results. The keys include the index `built_at`, the collection and a ranker version, so a rebuild or a ranking change cannot serve stale results (incident #4).

## 4. Evaluation method (L3)
- **Evaluation set:** 28 scenarios in `eval/scenarios.jsonl`, each with expected route, heading and code, escalation, and supporting clause IDs taken from the corpus. They cover:
  - the §4.1 flask (no capacity, 500 ml, 1 l);
  - 6 plain Chapter 73 cases and 4 plain Chapter 96 cases;
  - 4 material-vs-named-article traps;
  - 2 vague, 2 GRI 3 (a set, and a tie that must escalate), 2 out of scope, 2 injection;
  - the one Schedule 2 row;
  - 2 malformed requests.
- **Batch runner:** `eval/run_eval.py` sends every scenario to the public API, reads each run's trace, and scores it.
- **Metrics:** groundedness, context relevance and recall, faithfulness, and hallucination rate, computed exactly as written in `eval/METRICS.md`. A TruLens-style LLM judge (versioned prompt `judge@v1`, cached) is used where judgement is needed, with deterministic checks everywhere else. Task accuracy, escalation precision and recall, and cost are reported too.
- **Model:** a **local `qwen2.5:7b`** (Ollama) for both agents and judge.

## 5. Results: one deliberate change, before and after (`eval/BEFORE_AFTER.md`)
Change: dense-only retrieval (before) vs hybrid (after); everything else identical.

| Metric | Before (dense) | After (hybrid) |
|---|---|---|
| Groundedness | 0.625 (n = 2) | 0.157 (n = 5): too few runs to compare |
| Context relevance | 0.217 | 0.196 |
| Context recall | 0.637 | **0.735** |
| Faithfulness | 0.994 | 0.973 |
| Hallucination rate | 0 | 0 |
| Heading accuracy | 0.053 | **0.158** |

A retrieval-only check (no LLM) agrees: dense already finds the right heading first in 19/19 scenarios, thanks to the structure-aware chunks, and hybrid raises recall of the supporting clauses from 0.724 to 0.829. We keep hybrid.

## 6. Prompt comparison (L2, `eval/PROMPT_COMPARISON.md`)
`classifier@v1` (free reasoning) vs `classifier@v2` (explicit GRI checklist), same set:
- **v2 is cheaper and faster:** latency −41%, cost per 100 runs −18% ($3.13 → $2.58), context relevance +0.086, faithfulness 1.000 vs 0.973.
- **v1 does better on the task:** heading accuracy 0.158 vs 0.053, route accuracy 0.269 vs 0.231.
- **Both are equally safe:** 0 hallucinations, 100% clear-for-filing precision, 100% escalation recall.

## 7. Live quality monitoring (L6)
The retriever runs a background scorer:
- it samples about 10% of finished real runs (deterministic hash, skipping cache hits and batch-evaluation clients);
- it scores them with the same metric code;
- it writes `eval_scores` with `source='live'`;
- it exports `ecs_eval_score{metric,source}` for both the live hourly mean and the latest batch, which Grafana charts.

## 8. What did not work
- **A 7B local model rarely finishes.** 92–96% of runs escalated (loop budget or verifier rejection), including the §4.1 flask. That is the designed safe failure, since no wrong confident answer came out, but the demo needs a stronger model. One run (S01) escalated because the model listed the same heading twice as "competing", which the router should deduplicate (reported to Member 3).
- **Small samples.** Groundedness rests on 1–5 cited runs per batch, so groundedness deltas are not claimed.
- **The judge is the same small model,** so context relevance and groundedness are only indicative.
- **Fixed-size chunking was not tested end to end:** fixed chunks have no clause IDs, so the citation contract would break.
- **Bugs found and fixed during development** (incidents #4–#7): stale cached rankings, an invalid Chroma collection name, `/clause` failing on `GRI-3(b)`, and three metric bugs or definition problems.
