"""Agent 2 - Classifier (F4, F5). A tool-using loop: the model chooses which retrieval tool to call.

Tools: search_corpus, get_clause, get_applicable_notes, get_request_fields (+ submit_classification).
Output: Draft. Each attempt uses a different search strategy; on a retry the verifier's problems
are fed back. Bounded per attempt by MAX_TURNS and per run by the shared Budget.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from agent_worker import prompts, tools
from agent_worker.agents.common import call_llm, parse_json
from agent_worker.guardrails import delimit
from agent_worker.recorder import BudgetExceeded
from agent_worker.state import Draft

AGENT = "classifier"
ALLOWED = {"search_corpus", "get_clause", "get_applicable_notes", "get_request_fields"}
MAX_TURNS = 8
STRATEGIES = [
    "Start with a hybrid search on the product description. Then search, in keyword mode, for a heading "
    "that names the article itself, and check the notes that apply to each candidate heading.",
    "Change strategy: use keyword mode and search by WHAT THE ARTICLE IS and WHAT IT DOES (its name and "
    "function), not by its material. Fetch each candidate heading with get_clause before citing it.",
    "Change strategy: search in dense mode across both chapters 73 and 96 with no chapter filter, look at "
    "headings in the OTHER chapter from your previous answer, and fetch every passage you cite with get_clause.",
]


def _feedback(state: dict) -> str:
    v = state.get("verification") or {}
    if not v.get("problems"):
        return ""
    prev = state.get("draft") or {}
    return ("Your previous answer was REJECTED by the verifier:\n- " + "\n- ".join(v["problems"]) +
            f"\nPrevious answer: heading={prev.get('heading')!r} code={prev.get('proposed_hs_code')!r}. "
            "Search again and fix every problem. Quotes must be copied exactly from passages returned in this attempt.")


def run(state: dict, ctx) -> dict:
    attempt = int(state.get("attempt") or 0)
    p = ctx.prompts["classifier"]
    user = prompts.render(p["user"], strategy=STRATEGIES[min(attempt, len(STRATEGIES) - 1)],
                          feedback=_feedback(state),
                          extraction=json.dumps(state.get("extraction") or {}, ensure_ascii=False),
                          request_block=delimit(ctx.request),
                          max_tool_calls=max(0, ctx.budget.max_tool_calls - ctx.budget.tool_calls))
    messages = [{"role": "system", "content": p["system"]}, {"role": "user", "content": user}]
    specs = [tools.SPECS[n] for n in sorted(ALLOWED)] + [tools.submit_spec(p["output_schema"])]

    for turn in range(1, MAX_TURNS + 1):
        resp = call_llm(ctx, AGENT, f"attempt{attempt + 1}.turn{turn}", messages, p["id"], tools=specs)
        if not resp.tool_calls:
            try:  # some models answer with plain JSON instead of the submit tool
                return {"draft": Draft.model_validate(parse_json(resp.content)).model_dump(mode="json"),
                        "attempt": attempt + 1}
            except (ValueError, ValidationError):
                messages += [{"role": "assistant", "content": resp.content or ""},
                             {"role": "user", "content": "Continue: call a tool, or call submit_classification."}]
                continue
        messages.append({"role": "assistant", "content": resp.content or "", "tool_calls": resp.tool_calls})
        submitted = None
        for call in resp.tool_calls:
            name = call.get("function", {}).get("name", "")
            try:
                args = json.loads(call.get("function", {}).get("arguments") or "{}")
            except ValueError:
                messages.append(tools.as_tool_message(call.get("id", ""), {"error": "arguments were not valid JSON"}))
                continue
            if name == "submit_classification":
                try:
                    submitted = Draft.model_validate(args)
                    messages.append(tools.as_tool_message(call.get("id", ""), {"received": True}))
                except ValidationError as exc:
                    messages.append(tools.as_tool_message(call.get("id", ""), {"error": str(exc)[:500]}))
                continue
            result, _ = tools.execute(ctx, AGENT, ALLOWED, name, args)
            messages.append(tools.as_tool_message(call.get("id", ""), result))
        if submitted is not None:
            return {"draft": submitted.model_dump(mode="json"), "attempt": attempt + 1}
    raise BudgetExceeded(f"classifier did not submit an answer within {MAX_TURNS} turns")
