# Retrieval design (Member 2): corpus, chunking, embedding, search, caching

Requirements covered: §3 corpus difficulty, **L1** (LangChain + Chroma, chunking/embedding strategy, re-embedding without a full rebuild), **D2** (idempotent pipeline, freshness, throughput), **D7** (embedding + retrieval cache), **F4** (retrieval side).

## 1. The difficulty (spec §3) and why plain similarity search fails

Some headings describe goods by **material** ("7323 … household articles … *of iron or steel*"). Others name **what the article is** ("9617 *vacuum flasks* and other vacuum vessels"). GRI 1 says to classify by the terms of the headings and the Section/Chapter notes, so the heading that *names* the article has to be found first. A dense embedding of "stainless steel vacuum flask" sits close to the steel headings, because "stainless steel" dominates the vector. The note that settles the case (Section XV Note 1(m): Section XV "does not cover … other articles of Chapter 96") never mentions flasks at all. A single top-k similarity search therefore tends to return Chapter 73 and miss the provision that decides the case.

## 2. Design: four answers to that difficulty

| Problem | What the retriever does |
|---|---|
| The heading that names the article must be findable by its name | **One chunk per 4-digit heading** whose text *starts with the heading wording*, followed by its 8-digit lines. Keyword search on "vacuum flask" therefore hits `HDG-9617` directly. |
| Exact article names get blurred by embeddings | **Hybrid search**: BM25 keyword ranking + dense ranking, merged with reciprocal-rank fusion (k = 60). `mode=keyword` lets the agent search by name only. |
| The note that decides the case is never similar to the query | **Notes are linked by metadata, not similarity.** `GET /notes/applicable/HDG-7323` returns every Section XV note and Chapter 73 note, so the agent sees Note 1(m) even though the query never mentions it. |
| Citations must resolve to exact text (A3) | **Every chunk is one legal unit with a stable clause ID** (A.7 scheme), and `GET /clause/{id}` returns its exact text. A quote can be checked as a substring of that text. |

## 3. Chunking: structure-aware, by legal unit

Parsers live in `services/retriever/retriever/ingest/parsers.py`; the document registry is `corpus/sources.json`.

| Unit | Clause ID | Count | Notes |
|---|---|---|---|
| GRI rule / sub-rule | `GRI-1`, `GRI-2(a)` … `GRI-6` | 10 | Sub-rules repeat their rule's lead-in ("3. When by application of rule 2(b) …"), so each chunk stands alone |
| Section note | `SEC-XV-NOTE-n` | 9 | Section XX has **no** section notes (checked in the PDF) |
| Chapter note | `CH73-NOTE-n`, `CH96-NOTE-n` | 6 | Notes over 1,500 chars are split at their lettered items, keep the note number, and repeat the lead-in |
| Heading | `HDG-7323`, `HDG-9617` | 45 | Heading wording + its tariff lines |
| Tariff item | `TL-96170011` | 364 | Its own label + its "Under:" path of parent sub-headings + the heading wording + unit. Duty rates are stripped (spec §13) |
| Export policy | `EXP-96020030` (Schedule 2 row), `EXP-GN-n` (General Notes) | 4 | Chapter 73 has no Schedule 2 rows; Chapter 96 has one. Everything else falls back to General Note 1 ("Free"). See contract change #13 |

Every chunk carries `clause_id, kind, section, chapter, heading, title, doc_id, doc_version, page`.

**Text repair without invention** (`textnorm.py`). pypdf splits words in the CBIC PDFs ("classific ation", "V ACUUM", "W O RK ED"). A run of tokens is rejoined only when the joined word occurs elsewhere in the corpus and at least one piece is rarer than the joined word. A drop-cap fallback handles all-caps headings. Nothing is added that is not already in the documents. Duty-related appendices printed after the Chapter 73 table (Additional Duty Rules, safeguard and countervailing duty notices) are excluded.

## 4. Embedding and index (L1)

- **Embeddings:** local sentence-transformers via `langchain_huggingface.HuggingFaceEmbeddings`, model from `EMBED_MODEL` (default `all-MiniLM-L6-v2`, normalised vectors, CPU). No paid API. The dense text is `title + passage`, so a heading's wording is always embedded.
- **Index:** **Chroma** (persistent, cosine) through `langchain_chroma.Chroma`, in the `index_data` volume. One **collection per embedding model** (`chunks-<model-slug>`).
- **Keyword:** BM25 (`rank_bm25`) over title + text + clause ID + compact 8-digit codes, with stop-words removed and a light plural stemmer ("flasks" → "flask").

## 5. Pipeline: idempotent, incremental, re-embeddable (D2, L1)

`docker compose run --rm retriever python -m retriever.ingest build|status|reembed|chunks`

- **Chunk ID** = `sha256(doc_id | doc_version | clause_id | text)[:20]`. Parsing the same PDFs always gives the same IDs.
- **`build`** parses, writes `chunks.jsonl`, then *syncs* the active collection: it embeds only IDs the collection does not have and deletes IDs no longer produced. A second `build` embeds 0 chunks and keeps `built_at` unchanged (only `last_checked_at` moves). A changed document re-embeds only its changed chunks.
- **`reembed --model X`** reads the stored `chunks.jsonl` (no re-parsing), fills collection `chunks-x` next to the old one, then switches `active.json` with an atomic `os.replace`. The running service notices the change and reloads. The old collection stays for rollback.
- **On container start**, `build --if-missing` runs before the server starts. `/health` returns 503 until the index is loaded, so the compose healthcheck stays unhealthy until then.
- **Freshness (D2):** `manifest.json` records `built_at`, `last_checked_at`, sources (doc_id, version, sha256), `chunk_count`, chunks by kind, `embed_model`, collection, duration and chunks/second. It is served at `GET /index/info` and exported as `ecs_index_chunks`, `ecs_index_built_timestamp` and `ecs_ingest_chunks_per_second`.

## 6. Caching (D7, Member 2 part)

Both caches live in Redis with TTL `RETRIEVAL_CACHE_TTL_S`. Redis being down never fails a request; it is counted in `ecs_cache_errors_total`.

| Cache | Key | Why |
|---|---|---|
| `embedding` | model + query text | Query embedding is the CPU-bound step of a dense search. The same queries repeat across agent retries, the verifier's re-searches and repeated runs of the same product. |
| `retrieval` | `built_at` + collection + query + k + kinds + chapters + mode | The same tool calls repeat within and across runs. Because the key includes the index `built_at` and the collection, a rebuild or re-embed invalidates old results automatically. |

Hits and misses are counted in `ecs_cache_hits_total{cache}` / `ecs_cache_misses_total{cache}`. The measured effect on p95 and cost is reported with the load test (D7).

## 7. Endpoints (A.7)

`POST /search`, `GET /clause/{id}` (a prefix such as `GRI-3` returns its sub-rules), `GET /notes/applicable/{id}`, `GET /policy/{hs_code}` (8 → 6 → 4 digits, then General Note 1; also reports `tariff_item_exists` so a made-up 8-digit code can be caught), `GET /index/info`, `/health`, `/metrics`. All read and echo `X-Correlation-ID`. If the caller sends `X-Run-ID`, it is added to logs and spans.

## 8. Known limits

- The DGFT Schedule 2 file is the ITC (HS) 2018 consolidated edition (see `corpus/SOURCES.md`).
- Text repair is heuristic. The parser tests pin the passages the demo depends on.
- The first start needs internet access to download the embedding model into the volume. Later starts reuse it.
