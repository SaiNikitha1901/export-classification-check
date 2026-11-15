# Evaluation metrics: exactly how each number is computed

Code: `eval/metrics.py` (shared by the batch runner `eval/run_eval.py` and the live scorer `services/retriever/retriever/live_scoring.py`), judge in `eval/judge.py`, judge prompt `eval/judge_prompts/v1.json` (`judge@v1`). We use our own TruLens-style implementation ("TruLens or equivalent", spec L3) instead of the TruLens library, so the judge goes through the same env-configured LLM as the agents and every rule below can be read in about 200 lines.

## Inputs for one run
- **Result** (A.5) from `GET /runs/{id}`.
- **Retrieved passages:** every passage returned by any tool call in the run, taken from the `run_steps` trace (`GET /runs/{id}/trace`), deduplicated by `passage_id`.
- **Cited passages:** for each citation, the retrieved passage with its `passage_id`, or else the clause text from `GET /clause/{clause_id}`.
- **Scenario** (batch only): `eval/scenarios.jsonl` gives the expected route, heading, code, escalation and `supporting_clause_ids`.

## The judge
`EVAL_JUDGE=llm|lexical|auto` (default `auto`).
- **llm:** the agents' LLM (`LLM_BASE_URL`, `LLM_MODEL`), temperature 0, one call per metric per run (all claims or all passages in one prompt, which keeps us inside free-tier rate limits). Answers are cached in Redis (`evaljudge:*`, 30 days), keyed by judge version + model + exact prompt. If an answer cannot be parsed, that item falls back to the lexical judge, and the method is reported as `llm+lexical`.
- **lexical:** deterministic and model-free. Used automatically when the LLM is the load-test stub, which cannot judge.
  - **Claim support:** at least 60% of the claim's content words (stop-words removed, light plural stemming) occur in the cited passages, and every 4–8 digit code in the claim occurs in them.
  - **Passage relevance:** 1 if the passage shares at least 2 content words with the product description + intended use, 0.5 if it shares 1, else 0.

Every results folder, and every `eval_scores.label`, records which judge produced the numbers.

## The four quality metrics (L3)

| Metric | Per run | Aggregate | Direction |
|---|---|---|---|
| **Groundedness** | Split `reasoning_summary` + `route_basis` into claims (sentences, split on `.`/`;`). The judge decides for each claim whether the **cited** passages support it. Score = supported claims ÷ claims. **Not applicable** (excluded from the mean, with the count reported) when the run cites nothing: an escalation without citations makes only process statements ("no verified classification; loop limit reached"), which say nothing about grounding. | Mean over runs that cite passages | higher is better |
| **Context relevance** | (a) The judge rates each of the first 10 retrieved passages 0 / 0.5 / 1 for relevance to the request; score = mean. This is a *precision*-type measure: an agent search for 8 headings where only 1 applies scores about 0.1, even when the right heading is found (that is what recall is for). (b) **Context recall** (batch only) = share of the scenario's `supporting_clause_ids` that appear among the retrieved passages' clause IDs (recall over everything the run retrieved). | Means over runs | higher is better |
| **Faithfulness** | Deterministic checks that the final answer agrees with what the cited passages say: the heading is cited (as `HDG-xxxx` or one of its `TL-`); the cited heading passage really is that heading; the code starts with the heading; the code's `TL-` is cited; `clear-for-filing` only with verification passed + status completed + a code; a specialist escalation carries no code; the export-policy clause equals what the corpus gives for that code (`GET /policy`). Score = passed checks ÷ applicable checks. | Mean over runs | higher is better |
| **Hallucination rate** | A run counts as hallucinating if **any** of these holds: a cited clause does not exist in the corpus; a cited clause was never retrieved in that run; a citation quote is not an exact substring of a retrieved passage of that clause; the proposed HS code is not a tariff item in the corpus; the heading or the export-policy clause does not exist. The reasons are listed under "Hallucination findings" in `summary.md`. | Share of runs with a result that hallucinate | lower is better |

Per the glossary, the hallucination rate counts runs that state something unsupported. We use the strict, checkable version (a non-existent provision, or a quote that is not in the retrieved text), because "stating a provision that does not exist is more serious than declining to answer".

## Task metrics

| Metric | Definition |
|---|---|
| route_accuracy | result.route == expected_route, over scenarios that create a run |
| heading_accuracy | result.heading == expected_heading, over scenarios with an expected heading (including the 4.1 case) |
| hs_code_accuracy | result.proposed_hs_code == expected_hs_code, over scenarios with an expected code |
| clear_for_filing_precision | of the runs routed `clear-for-filing`, the share whose expected route was also clear **and** whose code is right (wrong confident answers are the costly error) |
| escalation_precision / recall | positive = `specialist-classification-review`; precision = TP ÷ (TP + FP), recall = TP ÷ (TP + FN) against `expected_escalation` |
| injection_detection | share of injection scenarios with `guardrails.injection_detected = true` |
| boundary_accuracy | HTTP status == `expected_http` (202 for valid, 422 for malformed), over all scenarios |

Cost and latency from `result.usage`: mean latency, mean cost, cost per 100 runs, mean tool calls, mean prompt tokens.

## Where the numbers go
- `eval/results/<UTC time>_<label>/summary.md` (readable), `summary.json` and `runs.jsonl` (per scenario, with every check and claim verdict).
- Postgres `eval_scores` (`source='batch'`, `scenario_id`, `metric`, `value`, `label = <run label>|<judge>`).
- Live runs (L6): the retriever's scorer samples about 10% of finished runs (`LIVE_SCORING_SAMPLE_RATE`, a deterministic hash of the run_id, skipping whole-run cache hits). It computes the same four metrics without a reference answer (so no recall and no task metrics), writes `eval_scores` (`source='live'`), and exports `ecs_eval_score{metric,source}` (live = mean of the last hour; batch = the latest batch run) for the Grafana "quality over time" panel.

## Commands
```
docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/run_eval.py --label baseline --fresh
docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/compare.py eval/results/<A> eval/results/<B>
```
On Windows Git Bash, prefix the commands with `MSYS_NO_PATHCONV=1` and use the full path in `-v`.
