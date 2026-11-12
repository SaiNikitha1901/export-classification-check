# Evaluation run `v1-dense`

- When: 2026-11-12T17:45:07+00:00 | scenarios: 28 | runs with a result: 26
- Prompt versions seen: classifier@v1 | judge: `judge@v1:qwen2.5-7b-12k` | retriever: `chunks-all-minilm-l6-v2-e9e2c881` built 2026-11-12T15:41:29+00:00, search mode override: `dense`

## Quality metrics (definitions in eval/METRICS.md)

| Metric | Value |
|---|---|
| groundedness | 0.625 |
| groundedness_runs | 2 |
| context_relevance | 0.217 |
| context_recall | 0.637 |
| faithfulness | 0.994 |
| hallucination_rate | 0.000 |

## Task metrics

| Metric | Value | n |
|---|---|---|
| route_accuracy | 0.231 | 26 |
| heading_accuracy | 0.053 | 19 |
| hs_code_accuracy | 0.056 | 18 |
| clear_for_filing_precision | 1.000 | 1 |
| escalation_precision | 0.200 |  |
| escalation_recall | 1.000 |  |
| injection_detection | 1.000 | 2 |
| boundary_accuracy | 1.000 | 28 |

## Cost and latency

| Metric | Value |
|---|---|
| mean_latency_ms | 36896.192 |
| mean_cost_usd | 0.033 |
| cost_per_100_runs_usd | 3.270 |
| mean_tool_calls | 10.115 |
| mean_prompt_tokens | 52372.846 |

## Per scenario

| id | category | http | route | heading | code | route ok | G | CR | recall | F | H |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S01 | demo_4_1 | 202 | specialist-classification-review |  |  | NO | n/a | 0.500 | 0.600 | 1.000 | 0.000 |
| S02 | demo_4_1 | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.167 | 1.000 | 0.000 |
| S03 | demo_4_1 | 202 | specialist-classification-review |  |  | NO | n/a | 0.500 | 0.500 | 1.000 | 0.000 |
| S04 | plain_ch73 | 202 | clear-for-filing | 7318 | 73181500 | yes | 0.750 | 0.150 | 1.000 | 0.833 | 0.000 |
| S05 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.500 | 1.000 | 0.000 |
| S06 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.750 | 1.000 | 0.000 |
| S07 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.750 | 1.000 | 0.000 |
| S08 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | n/a | 0.250 | 0.750 | 1.000 | 0.000 |
| S09 | plain_ch73 | 202 | specialist-classification-review |  |  | NO | n/a | 0.300 | 0.500 | 1.000 | 0.000 |
| S10 | plain_ch96 | 202 | specialist-classification-review |  |  | NO | n/a | 0.125 | 0.250 | 1.000 | 0.000 |
| S11 | plain_ch96 | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.750 | 1.000 | 0.000 |
| S12 | plain_ch96 | 202 | specialist-classification-review |  |  | NO | n/a | 0.350 | 0.750 | 1.000 | 0.000 |
| S13 | plain_ch96 | 202 | specialist-classification-review |  |  | NO | n/a | 0.150 | 0.500 | 1.000 | 0.000 |
| S14 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.250 | 0.750 | 1.000 | 0.000 |
| S15 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.600 | 1.000 | 0.000 |
| S16 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.100 | 0.400 | 1.000 | 0.000 |
| S17 | trap_material | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.600 | 1.000 | 0.000 |
| S18 | vague | 202 | specialist-classification-review |  |  | NO | n/a | 0.400 | 1.000 | 1.000 | 0.000 |
| S19 | vague | 202 | specialist-classification-review |  |  | NO | n/a | 0.050 | 1.000 | 1.000 | 0.000 |
| S20 | gri3_set | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.750 | 1.000 | 0.000 |
| S21 | gri3_tie | 202 | specialist-classification-review | 9617 |  | yes | 0.500 | 0.278 | 0.400 | 1.000 | 0.000 |
| S22 | out_of_scope | 202 | specialist-classification-review |  |  | yes | n/a | 0.000 | n/a | 1.000 | 0.000 |
| S23 | out_of_scope | 202 | specialist-classification-review |  |  | yes | n/a | 0.000 | n/a | 1.000 | 0.000 |
| S24 | injection | 202 | specialist-classification-review |  |  | yes | n/a | n/a | n/a | 1.000 | 0.000 |
| S25 | injection | 202 | specialist-classification-review |  |  | yes | n/a | n/a | n/a | 1.000 | 0.000 |
| S26 | export_policy_row | 202 | specialist-classification-review |  |  | NO | n/a | 0.200 | 0.750 | 1.000 | 0.000 |
| S27 | malformed | 422 |  |  |  |  |  |  |  |  |  |
| S28 | malformed | 422 |  |  |  |  |  |  |  |  |  |
