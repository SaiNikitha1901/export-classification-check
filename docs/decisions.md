# Team decisions

Final calls on questions that were left open. Made by Member 1 (scrum master) on 2026-11-15. These override "proposed" and "to confirm" notes elsewhere (`docs/contract_changes.md`, `docs/eval1_corpus_confirmation.md`).

## D1. §4.1 reference answer: 4.1-A is the reference, 4.1-B is the follow-up

The examiners will type the exact sentence: *"Stainless steel vacuum flask with a moulded plastic outer body."*

**Reference answer (4.1-A, the exact sentence):**
- heading **9617**, decided by **GRI 1**. Heading 9617 names vacuum flasks, and **Section XV Note 1(m)** excludes Chapter 96 articles from the base-metal chapters, so Chapter 73 (7323) does not apply;
- citations: `GRI-1`, `HDG-9617`, `SEC-XV-NOTE-1`;
- route **`seek-product-clarification`**, with capacity as the missing fact. 9617 00 11 (≤ 0.75 l) and 9617 00 12 (> 0.75 l) differ only by capacity, and the sentence does not give it;
- `proposed_hs_code`: null, with both candidates named in the route basis.

**Follow-up in the same demo (4.1-B):** the same sentence + "Capacity 500 ml." gives **96170011**, by GRI 1 then **GRI 6**, with route **`clear-for-filing`** (only if verified) and export policy **Free** (`EXP-GN-1`).

**Why:** guessing a capacity would mean inventing a fact. The spec rewards a system "that knows when not to answer" (§4, F5/F7). 4.1-A shows the hard part (finding 9617 and citing the exclusion) *and* restraint. 4.1-B then shows the full path to an 8-digit code. Both are already in `eval/scenarios.jsonl` (S01, S02).

## D2. LLM: Groq `openai/gpt-oss-120b`, with `openai/gpt-oss-20b` as fallback

| Option | Decision | Reason |
|---|---|---|
| llm-stub | **load tests only** (D6) | It cannot judge. With the stub, the verifier passes unrelated headings (a laptop got 9612) |
| local `qwen2.5:7b` (Ollama) | rejected | 92–96% of eval runs escalated, and the right heading came back only 16% of the time (`eval/PROMPT_COMPARISON.md`) |
| Gemini free tier | rejected | about 20 requests/day per model; a run needs ~8 LLM calls, and the 28-scenario eval needs a few hundred |
| Groq `qwen` models | rejected | about 40% of tool calls fail with `tool_use_failed` (seen in another course lab on the same account type) |
| **Groq `openai/gpt-oss-120b`** | **primary** | OpenAI-compatible, reliable tool calling (10/10 in testing), free tier |
| **Groq `openai/gpt-oss-20b`** | **fallback** (`LLM_FALLBACK_*`) | the same API, a separate model quota, so when the 120B is rate-limited the run still completes before dropping to degraded mode |

Configuration goes in `.env` only (never committed):
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<your Groq key>
LLM_MODEL=openai/gpt-oss-120b
LLM_FALLBACK_BASE_URL=https://api.groq.com/openai/v1
LLM_FALLBACK_API_KEY=<your Groq key>
LLM_FALLBACK_MODEL=openai/gpt-oss-20b
```
To be confirmed with a live run of S01/S02 + the out-of-scope cases before the eval re-run. If Groq's daily token limit cannot cover the 28-scenario batch (~40–50k prompt tokens per run), run the batch over two days. The token budget per run, and the classifier as its main driver, go in the cost report (L5).

## D3. Contract changes accepted

| # | Change | Decision |
|---|---|---|
| 7 | M3 acks #1, #2, #3, #6 | accepted |
| 8 | M3 env vars | accepted, in `.env.example` (#2, #4) |
| 9 | loop bounds 20 steps / 16 tool calls | accepted, in `.env.example` (#2) |
| 10 | `run_steps.status` / `agent` values | accepted |
| 11 | retriever response shapes the worker relies on | accepted; M2's endpoints already match |
| 12 | §4.1 needs capacity | accepted, see D1 |
| 13 | `EXP-GN-1` as the export-policy citation when no Schedule 2 row exists | **accepted**; the verifier must accept it |
| 14 | M2 env vars | accepted, in `.env.example` (#2, #4) |
| 15 | new retriever endpoint for notes in other sections that exclude a heading's chapter (e.g. `HDG-9617` → `SEC-XV-NOTE-1`) | **superseded (2026-11-15):** the classifier now does this lookup in code with the existing tools (`search_corpus` + `get_applicable_notes`), so no new endpoint is needed |

## D4. Definition of done

The project is complete when all of these hold on `main`:
1. PR #1 is merged, and `docker compose up --build --wait` from a fresh clone serves the flask case.
2. `test_vacuum_flask` passes against the real retriever and the real model (D1).
3. Demo items 1–10 (`docs/demo_script.md`) each pass once in a rehearsal from a fresh clone.
4. The eval batch has been re-run on the D2 model, with `BEFORE_AFTER.md` and `PROMPT_COMPARISON.md` updated.
5. `loadtest/RESULTS.md` has the 1- vs 3-worker sweeps and cache on/off, against `SLO.md`.
6. The final report is in `docs/report/` with every section listed in spec §11.
