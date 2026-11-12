# Prompt comparison (L2): `classifier@v1` vs `classifier@v2`

**Setup.** The same 28 scenarios (`eval/scenarios.jsonl`), the same retriever (hybrid, structure-aware index), the same metric code and judge (`judge@v1` on the same model), run on 2026-11-12 with a **local model, `qwen2.5:7b`** (Ollama, 12k context, temperature 0) for both the agents and the judge. Only `PROMPT_VERSION` changed. Results: `eval/results/20261112T171458Z_v1-hybrid/` and `eval/results/20261112T172800Z_v2-hybrid/`.

- **v1** (Member 3, `prompts/classifier/v1.yaml`): "free reasoning: the model decides how to search and how to apply the GRI".
- **v2** (`prompts/classifier/v2.yaml`): an explicit GRI checklist 1 → 2 → 3(a) → 3(b) → 3(c) → 4 → 5 → 6, stopping at the first rule that decides, plus a mandatory keyword search for a heading that names the article before any material heading.

## Result

| Group | Metric | v1-hybrid | v2-hybrid | Change | Better? |
|---|---|---|---|---|---|
| quality | groundedness | 0.157 | 0.750 | +0.593 | yes |
| quality | groundedness_runs | 5 | 1 | -4 |  |
| quality | context_relevance | 0.196 | 0.282 | +0.086 | yes |
| quality | context_recall | 0.735 | 0.724 | -0.011 | no |
| quality | faithfulness | 0.973 | 1.000 | +0.027 | yes |
| quality | hallucination_rate | 0.000 | 0.000 | 0.000 |  |
| task | route_accuracy | 0.269 | 0.231 | -0.038 | no |
| task | heading_accuracy | 0.158 | 0.053 | -0.105 | no |
| task | hs_code_accuracy | 0.111 | 0.056 | -0.056 | no |
| task | clear_for_filing_precision | 1.000 | 1.000 | 0.000 |  |
| task | escalation_precision | 0.217 | 0.200 | -0.017 | no |
| task | escalation_recall | 1.000 | 1.000 | 0.000 |  |
| task | injection_detection | 1.000 | 1.000 | 0.000 |  |
| task | boundary_accuracy | 1.000 | 1.000 | 0.000 |  |
| cost | mean_latency_ms | 46473.320 | 27225.038 | -19248.282 | yes |
| cost | mean_cost_usd | 0.031 | 0.026 | -0.005 | yes |
| cost | cost_per_100_runs_usd | 3.130 | 2.580 | -0.550 | yes |
| cost | mean_tool_calls | 11.360 | 11.846 | +0.486 | no |
| cost | mean_prompt_tokens | 49934.040 | 41417.961 | -8516.078 | yes |

## Which did better, on which metric, by how much

- **v2 is cheaper and faster.** Mean latency per run is 46.5 s → 27.2 s (**−41%**), prompt tokens per run −17%, and notional cost per 100 runs $3.13 → $2.58 (**−18%**). The checklist makes the model stop sooner instead of searching around.
- **v2 retrieves more relevant context.** Context relevance is 0.196 → 0.282 (**+0.086**, +44% relative): the mandatory "search for the article's name" step pulls the named heading in early. Context recall is the same (0.735 vs 0.724).
- **v2 is more faithful and less wrong, but answers less.** Faithfulness is 0.973 → 1.000. Both prompts have **0% hallucination** and **100% clear-for-filing precision** (every confident answer was right). But v2 reached a verified answer in only 1 run (v1: 2), so route accuracy is 0.269 → 0.231 (−0.038), heading accuracy 0.158 → 0.053 (−0.105) and code accuracy 0.111 → 0.056 (−0.056).
- **Groundedness is not comparable here.** It only applies to runs that cite passages: 5 runs for v1 (0.157) and 1 run for v2 (0.750). One run is too few to call a winner.

**Verdict for this model:** v1 is better on the task (it reaches the right heading 3× as often). v2 is better on cost (−18%), latency (−41%) and context relevance (+0.086). Neither is reliable with a 7B local model: 92-96% of runs escalate (v1 23/25, v2 25/26) because the classifier does not finish within its loop budget, or the verifier rejects its draft. That is the designed safe failure (escalate, never guess), but it means the demo needs a stronger model.

## Limits of this comparison
- n = 28, run once each. A difference of one scenario moves route accuracy by about 0.04, so the task deltas above are within noise. The cost and latency deltas are much larger (−18%, −41%), but they also come from a single run per prompt.
- One v1 run (S20) hit the batch runner's 240 s poll timeout while the GPU was shared with the judge, and counts as "no result".
- The same 7B model is the judge. A stronger judge would score context relevance and groundedness more reliably.
- **To repeat with a stronger model** (for example a free hosted Llama-3.3-70B), set `LLM_*` in `.env`, then run the same two commands with `PROMPT_VERSION=classifier@v1` and `classifier@v2`:
  `docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/run_eval.py --label v1-hybrid --fresh`
