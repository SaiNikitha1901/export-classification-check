# Demo steps from Member 2 (for `docs/demo_script.md`)

These are the exact steps for the §9 demo items that rely on the corpus and retriever: **#2**, **#5** and **#10**, plus a short retrieval and evaluation segment. Run from the repo root after `docker compose up -d --build --wait`. Expected outputs are what we measured. Run IDs will differ.

## #10 The §4.1 case (and the retrieval half of it)
1. Show that the naive search lands in steel, and that our search finds the named heading:
   ```
   curl -s -X POST localhost:8001/search -H "Content-Type: application/json" -d '{"query":"Stainless steel vacuum flask with a moulded plastic outer body.","mode":"dense","k":5,"kinds":["heading"]}'
   curl -s -X POST localhost:8001/search -H "Content-Type: application/json" -d '{"query":"vacuum flask","mode":"keyword","k":3}'
   ```
   Expected: the keyword search returns `HDG-9617` first.
2. Show the note that excludes the steel heading. The note is found by metadata, not similarity:
   ```
   curl -s localhost:8001/notes/applicable/HDG-7323
   ```
   Point at `SEC-XV-NOTE-1`, item (m): "… other articles of Chapter 96 …".
3. Submit the demo request (use 4.1-B with "Capacity 500 ml." if the faculty confirmed it; see `docs/eval1_corpus_confirmation.md` §4) in the web client at `/ui`. Expected: heading 9617, code 96170011, GRI-1 + GRI-6, policy Free (`EXP-GN-1`). The exact sentence without a capacity routes to `seek-product-clarification`.

## #2 Citations resolve to retrieved text
For each citation in the result, open its clause and show that the quote is an exact substring:
```
curl -s localhost:8001/clause/HDG-9617
curl -s localhost:8001/clause/TL-96170011
curl -s localhost:8001/clause/GRI-1
```
The batch evaluation checks this automatically for every run: the hallucination rate counts any quote that is not an exact substring (`eval/METRICS.md`).

## #5 A case the corpus cannot answer: escalation, not fabrication
Submit `"Laptop computer with aluminium casing, 14 inch screen."` (scenario S22). Expected: `specialist-classification-review`, no HS code. Also show the retriever refusing an out-of-scope code:
```
curl -s localhost:8001/policy/84713010      # 404: not Chapter 73 or 96
```

## Evaluation and data-freshness segment (L3, D2, L1, L6)
```
curl -s localhost:8001/index/info                                   # built_at, sources + sha256, 438 chunks
docker compose run --rm retriever python -m retriever.ingest build  # second run: "embedded_chunks": 0
cat eval/BEFORE_AFTER.md                                            # the four metrics before and after
```
In Grafana, show the quality-over-time panel (`ecs_eval_score{source="live"}`), which the retriever's live scorer feeds.
