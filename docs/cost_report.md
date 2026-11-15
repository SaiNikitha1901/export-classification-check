# Cost report (L5): Member 3

## How cost is recorded
- **Each LLM call:** at the moment it returns, the worker writes one `run_steps` row (`kind=llm`) with `prompt_tokens`, `completion_tokens`, `cost_usd`, `agent`, `name` (e.g. `attempt1.turn3`) and `prompt_version`.
  - Cost = `prompt_tokens/1000 · LLM_PRICE_IN_PER_1K + completion_tokens/1000 · LLM_PRICE_OUT_PER_1K`.
  - These are notional prices from env, so cost is reported even on a free tier.
  - If a provider omits `usage`, tokens are estimated at 4 characters per token, so cost is never silently zero.
- **Each run:** the totals go into `result.usage` (`prompt_tokens`, `completion_tokens`, `cost_usd`, `steps`, `tool_calls`, `latency_ms`).
- **Prometheus:** `ecs_llm_tokens_total{agent,kind}`, `ecs_llm_cost_usd_total{agent}`, `ecs_llm_retries_total{agent}`.

Query used for the numbers below (Postgres):
```sql
SELECT s.agent, count(*) AS llm_calls, sum(prompt_tokens), sum(completion_tokens), sum(cost_usd)
FROM run_steps s JOIN runs r USING (run_id)
WHERE r.status='completed' AND s.kind='llm' GROUP BY s.agent;
```

## Measured: llm-stub, 2026-11-12 (9 completed flask runs)
Prices: `LLM_PRICE_IN_PER_1K=0.00059`, `LLM_PRICE_OUT_PER_1K=0.00079`. Prompt `classifier@v1`. Fake retriever (real tariff text).

| | value |
|---|---|
| mean prompt tokens per run | 16,600 |
| mean completion tokens per run | 707 |
| mean cost per run | $0.0104 |
| **cost per 100 runs** | **$1.04** |
| mean end-to-end time (stub delay 1.5–4 s per call) | 24.4 s |

| Agent | LLM calls (9 runs) | Prompt tokens | Completion tokens | Cost | Share |
|---|---|---|---|---|---|
| **classifier** | 61 | 139,359 | 5,821 | $0.0868 | **93.2 %** |
| verifier | 9 | 7,302 | 99 | $0.0044 | 4.7 % |
| intake | 9 | 2,736 | 441 | $0.0020 | 2.1 % |

### Largest single cost driver: the classifier's growing context
The classifier is a tool loop. Every turn re-sends the whole conversation: the system prompt, plus every passage returned by every earlier tool call. Mean prompt tokens per classifier turn:

| turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| prompt tokens | 714 | 1,414 | 2,080 | 2,531 | 2,728 | 3,289 | 3,509 |

So classifier cost grows roughly with the **square** of the number of turns. Section and chapter notes are the longest passages: Section XV Note 1 alone is about 1,400 characters, and it must be sent in full, because the decisive exclusion (1(m)) is at its end. A verifier retry adds a whole new classifier attempt, roughly doubling the cost of that run.

**Levers, in order of effect:**
1. **Keep `AGENT_MAX_TOOL_CALLS` tight.** It is a cost bound as well as a loop bound.
2. **Cache retrievals.** Member 2's D7 retrieval cache saves latency, but it does not save tokens.
3. **Whole-run cache.** Member 1's D7 run cache makes a repeated request cost $0.
4. **Trim tool results.** Send the model only the passage fields it needs (already done: `tools.compact`).
5. **Drop already-read passages** from later turns. **Done (2026-11-15, PR #7):** within one classifier attempt, a passage that was already shown is re-sent only as `{passage_id, clause_id, already_shown_above}`. The full text stays earlier in the same conversation, so quotes are still copyable. Duplicate fields (chapter, heading, a heading's title) are dropped, and search returns 6 passages instead of 8.

## Measured: a real provider (Groq free tier, 2026-11-15)
Same SQL, notional prices `LLM_PRICE_IN_PER_1K=0.00059`, `LLM_PRICE_OUT_PER_1K=0.00079`.

| Run | Model | Prompt + completion tokens | Cost | Time |
|---|---|---|---|---|
| §4.1 exact sentence (after the token cut), verified first attempt | `openai/gpt-oss-20b` | 21,013 + 4,049 | $0.0156 | 101 s |
| §4.1 + 500 ml (before all fixes), escalated at the 8-turn loop limit | `openai/gpt-oss-120b` | 53,569 + 4,469 | $0.0351 | 326 s |
| Laptop (before the token cut), correctly escalated as out of scope | `openai/gpt-oss-120b` | 34,005 + 3,170 | $0.0226 | 187 s |

- **Per-turn prompt tokens on the same flask case: about 5.6k before the cut, ≤ 2.6k after.**
- One verified real run is about **$1.56 per 100 runs** at the notional prices, close to the 1.5–2× of the stub figure predicted above.
- **On a free tier the binding limit is tokens per day, not money:** Groq allows 200,000 tokens/day per model, so 8–15 runs per model per day. That's why decision D2 pairs two models (separate quotas) and why the whole-run cache (D7) matters.
- **[PENDING: Groq run 2026-11-16]** Cost per 100 runs over the Groq evaluation subset, using the SQL above.
