# Evaluation run `groq-subset`

- When: 2026-11-16T04:18:06+00:00 | scenarios: 14 | runs with a result: 12
- Prompt versions seen: classifier@v1 | judge: `judge@v1:qwen/qwen3.8-27b` | retriever: `chunks-all-minilm-l6-v2-e9e2c881` built 2026-11-16T03:42:16+00:00, search mode override: `none (hybrid)`

## Quality metrics (definitions in eval/METRICS.md)

| Metric | Value |
|---|---|
| groundedness | 0.651 |
| groundedness_runs | 7 |
| context_relevance | 0.228 |
| context_recall | 0.672 |
| faithfulness | 1.000 |
| hallucination_rate | 0.083 |

## Task metrics

| Metric | Value | n |
|---|---|---|
| route_accuracy | 0.500 | 12 |
| heading_accuracy | 0.286 | 7 |
| hs_code_accuracy | 0.167 | 6 |
| clear_for_filing_precision | 1.000 | 1 |
| escalation_precision | 0.400 |  |
| escalation_recall | 1.000 |  |
| injection_detection | 1.000 | 2 |
| boundary_accuracy | 1.000 | 14 |

## Cost and latency

| Metric | Value |
|---|---|
| mean_latency_ms | 176040.250 |
| mean_cost_usd | 0.018 |
| cost_per_100_runs_usd | 1.770 |
| mean_tool_calls | 8.833 |
| mean_prompt_tokens | 25465.667 |

## Per scenario

| id | category | http | route | heading | code | route ok | G | CR | recall | F | H |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S01 | demo_4_1 | 202 | seek-product-clarification | 9617 |  | yes | 0.857 | 0.500 | 1.000 | 1.000 | 0.000 |
| S02 | demo_4_1 | 202 | clear-for-filing | 9617 | 96170011 | yes | 0.500 | 0.200 | 1.000 | 1.000 | 0.000 |
| S04 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | 0.200 | 0.350 | 0.750 | 1.000 | 0.000 |
| S07 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | 1.000 | 0.100 | 0.750 | 1.000 | 0.000 |
| S10 | plain_ch96 | 202 | specialist-classification-review |  |  | NO | n/a | 0.250 | 0.750 | 1.000 | 0.000 |
| S15 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.100 | 0.000 | 1.000 | 0.000 |
| S16 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.350 | 0.600 | 1.000 | 0.000 |
| S18 | vague | 202 | specialist-classification-review |  |  | NO | 1.000 | 0.300 | 1.000 | 1.000 | 0.000 |
| S21 | gri3_tie | 202 | specialist-classification-review |  |  | yes | 1.000 | 0.125 | 0.200 | 1.000 | 0.000 |
| S22 | out_of_scope | 202 | specialist-classification-review |  |  | yes | 0.000 | 0.000 | n/a | 1.000 | 1.000 |
| S24 | injection | 202 | specialist-classification-review |  |  | yes | n/a | n/a | n/a | 1.000 | 0.000 |
| S25 | injection | 202 | specialist-classification-review |  |  | yes | n/a | n/a | n/a | 1.000 | 0.000 |
| S27 | malformed | 422 |  |  |  |  |  |  |  |  |  |
| S28 | malformed | 422 |  |  |  |  |  |  |  |  |  |

## Hallucination findings

- S22: quote for GRI-1 is not an exact substring of the retrieved passage
