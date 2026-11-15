# One deliberate change, before and after (L3)

**The change:** retrieval mode. **Before** = dense-only (every `/search` forced to the embedding ranking with `FORCE_SEARCH_MODE=dense`, which is the "embed the request, take the top passages" approach from spec §5). **After** = our design, hybrid BM25 + dense with reciprocal-rank fusion. Everything else was identical: the same 28 scenarios, structure-aware index, agents and prompt (`classifier@v1`), and model (`qwen2.5:7b` local, Ollama, temperature 0, also used as judge `judge@v1`), and the same metric code (`eval/metrics.py`; both batches were rescored with the final code). Results: `eval/results/20261112T174507Z_v1-dense/` (before) and `eval/results/20261112T171458Z_v1-hybrid/` (after).

## The four metrics, before and after

| Metric | Before (dense-only) | After (hybrid) | Change |
|---|---|---|---|
| **Groundedness** | 0.625 (n = 2 runs with citations) | 0.157 (n = 5) | not comparable: n too small, see below |
| **Context relevance** (judged precision of retrieved passages) | 0.217 | 0.196 | −0.021 |
| **Context recall** of supporting clauses | 0.637 | 0.735 | **+0.098** |
| **Faithfulness** | 0.994 | 0.973 | −0.020 |
| **Hallucination rate** | 0.000 | 0.000 | 0 |

## Full comparison (quality, task, cost)

| Group | Metric | v1-dense | v1-hybrid | Change | Better? |
|---|---|---|---|---|---|
| quality | groundedness | 0.625 | 0.157 | -0.468 | no |
| quality | groundedness_runs | 2 | 5 | +3 |  |
| quality | context_relevance | 0.217 | 0.196 | -0.021 | no |
| quality | context_recall | 0.637 | 0.735 | +0.098 | yes |
| quality | faithfulness | 0.994 | 0.973 | -0.020 | no |
| quality | hallucination_rate | 0.000 | 0.000 | 0.000 |  |
| task | route_accuracy | 0.231 | 0.269 | +0.038 | yes |
| task | heading_accuracy | 0.053 | 0.158 | +0.105 | yes |
| task | hs_code_accuracy | 0.056 | 0.111 | +0.056 | yes |
| task | clear_for_filing_precision | 1.000 | 1.000 | 0.000 |  |
| task | escalation_precision | 0.200 | 0.217 | +0.017 | yes |
| task | escalation_recall | 1.000 | 1.000 | 0.000 |  |
| task | injection_detection | 1.000 | 1.000 | 0.000 |  |
| task | boundary_accuracy | 1.000 | 1.000 | 0.000 |  |
| cost | mean_latency_ms | 36896.192 | 46473.320 | +9577.128 | no |
| cost | mean_cost_usd | 0.033 | 0.031 | -0.001 | yes |
| cost | cost_per_100_runs_usd | 3.270 | 3.130 | -0.140 | yes |
| cost | mean_tool_calls | 10.115 | 11.360 | +1.245 | no |
| cost | mean_prompt_tokens | 52372.846 | 49934.040 | -2438.806 | yes |

## Supporting evidence without the LLM: retrieval-only evaluation

The same change measured on the retriever alone (`eval/retrieval_eval.py`, one search per scenario for the product text, 19 scenarios with an expected heading, k = 8; `eval/results/20261112T170555Z_retrieval/`):

| Mode | hit@1 | hit@8 | MRR | recall@8 (supporting HDG/TL/notes) |
|---|---|---|---|---|
| dense (before) | 1.000 | 1.000 | 1.000 | 0.724 |
| keyword | 0.947 | 1.000 | 0.956 | 0.829 |
| hybrid (after) | 0.947 | 1.000 | 0.965 | **0.829** |

## What this shows
1. **The structure-aware chunking does most of the work.** Dense-only already ranks the correct heading first for 19/19 scenarios, including the vacuum flask. Every heading chunk starts with its own wording, and every tariff-line chunk repeats its heading's wording, so the embedding cannot drift to "articles of iron or steel" the way a fixed-size chunk of Chapter 73 would.
2. **Hybrid adds recall of the other clauses the answer needs** (+0.10 both retrieval-only and end-to-end). The keyword side brings in the exact tariff line ("Capacity … not exceeding 0.75 l") and the heading together. With more of the supporting clauses in hand, the agent reached the right heading 3× as often (heading accuracy 0.053 → 0.158) and the right route more often (+0.038).
3. **The cost:** slightly lower precision (context relevance −0.021: keyword matches add some off-topic passages, e.g. "cookers" also hits heading 7321 stoves), one top-1 miss in retrieval-only (S07 pressure cooker, rank 3), and +1.2 tool calls and +9.6 s per run.
4. **Safety did not change:** 0 hallucinations, 100% clear-for-filing precision and 100% escalation recall in both. Every confident answer was right, and every case that had to escalate did.

**Decision:** keep hybrid. The +0.10 recall of supporting clauses is what lets the agent cite the heading *and* its tariff line, at a small cost in precision and latency.

## Limits
- The model is a 7B local model. 92-96% of runs with a result escalate before a verified answer (dense 25/26, hybrid 23/25) (classifier loop budget or verifier rejection), so the task metrics rest on few answered runs, and **groundedness** applies only to runs that cite passages (2 vs 5). That is too few to compare, so we do not claim a groundedness change.
- n = 28, single run per configuration. One scenario moves route accuracy by about 0.04.
- We chose this change over "structure-aware vs fixed 500-token chunks" because the chunk IDs are the citation contract (A.7): a fixed-chunk index would break `/clause` and the verifier's citation checks, so the end-to-end comparison would measure broken citations, not retrieval.
- Re-run with a stronger model: set `LLM_*` in `.env`, then run the same two batches (`FORCE_SEARCH_MODE=dense` in `.env` for the "before" batch).
