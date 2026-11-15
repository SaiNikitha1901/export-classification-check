"""Agent 2 - Classifier (F4, F5). A tool-using loop: the model chooses which retrieval tool to call.

Tools: search_corpus, get_clause, get_applicable_notes, get_request_fields (+ submit_classification).
Output: Draft. Each attempt uses a different search strategy; on a retry the verifier's problems
and the passages already retrieved are fed back. Bounded per attempt by CLASSIFIER_MAX_TURNS and per
run by the shared Budget.

After the model submits, a deterministic exclusion lookup (spec section 5, step 2) runs in code: if the
heading is in Chapter 96 but the article is of iron or steel, the Chapter 73 candidate's applicable
notes are fetched and the note item that excludes Chapter 96 is cited (Section XV Note 1(m) for the
vacuum flask). The model does not have to remember to look.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from agent_worker import prompts, tools
from agent_worker.agents.common import call_llm, parse_json
from agent_worker.guardrails import delimit
from agent_worker.recorder import BudgetExceeded
from agent_worker.state import Draft
from contracts import Citation

AGENT = "classifier"
ALLOWED = {"search_corpus", "get_clause", "get_applicable_notes", "get_request_fields"}
STRATEGIES = [
    "Start with a hybrid search on the product description. Then search, in keyword mode, for a heading "
    "that names the article itself, and check the notes that apply to each candidate heading.",
    "Change strategy: use keyword mode and search by WHAT THE ARTICLE IS and WHAT IT DOES (its name and "
    "function), not by its material. Fetch each candidate heading with get_clause before citing it.",
    "Change strategy: search in dense mode across both chapters 73 and 96 with no chapter filter, look at "
    "headings in the OTHER chapter from your previous answer, and fetch every passage you cite with get_clause.",
]


def _feedback(state: dict, ctx) -> str:
    v = state.get("verification") or {}
    if not v.get("problems"):
        return ""
    prev = state.get("draft") or {}
    return ("Your previous answer was REJECTED by the verifier:\n- " + "\n- ".join(v["problems"]) +
            f"\nPrevious answer: heading={prev.get('heading')!r} code={prev.get('proposed_hs_code')!r}. "
            "Search again and fix every problem. Quotes must be copied exactly from retrieved passages."
            + _already_retrieved(state, ctx))


def _already_retrieved(state: dict, ctx) -> str:
    """Carry the evidence of earlier attempts into the retry, so it does not start from nothing."""
    prev = state.get("draft") or {}
    want = {c.get("passage_id") for c in prev.get("citations") or []}
    h = prev.get("heading") or ""
    rows = [p for p in ctx.evidence.values()
            if p.get("passage_id") in want or (h and p.get("clause_id") in (f"HDG-{h}", "GRI-1", "GRI-6"))][:8]
    if not rows:
        return ""
    lines = [f"- passage_id={p['passage_id']} clause_id={p['clause_id']}: {(p.get('text') or '')[:400]}" for p in rows]
    return ("\nPassages already retrieved in earlier attempts (you may cite them with these passage_ids "
            "without searching again):\n" + "\n".join(lines))


def run(state: dict, ctx) -> dict:
    attempt = int(state.get("attempt") or 0)
    ctx.shown_ids = set()   # a new attempt starts a new conversation: passages must be shown in full again
    p = ctx.prompts["classifier"]
    user = prompts.render(p["user"], strategy=STRATEGIES[min(attempt, len(STRATEGIES) - 1)],
                          feedback=_feedback(state, ctx),
                          extraction=json.dumps(state.get("extraction") or {}, ensure_ascii=False),
                          request_block=delimit(ctx.request),
                          max_tool_calls=max(0, ctx.budget.max_tool_calls - ctx.budget.tool_calls))
    messages = [{"role": "system", "content": p["system"]}, {"role": "user", "content": user}]
    specs = [tools.SPECS[n] for n in sorted(ALLOWED)] + [tools.submit_spec(p["output_schema"])]

    max_turns = ctx.settings.classifier_max_turns
    for turn in range(1, max_turns + 1):
        resp = call_llm(ctx, AGENT, f"attempt{attempt + 1}.turn{turn}", messages, p["id"], tools=specs)
        if not resp.tool_calls:
            try:  # some models answer with plain JSON instead of the submit tool
                draft = add_exclusions(Draft.model_validate(parse_json(resp.content)), state, ctx)
                return {"draft": draft.model_dump(mode="json"), "attempt": attempt + 1}
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
            return {"draft": add_exclusions(submitted, state, ctx).model_dump(mode="json"), "attempt": attempt + 1}
    raise BudgetExceeded(f"classifier did not submit an answer within {max_turns} turns")


_IRON_STEEL = re.compile(r"\b(steel|iron)\b", re.I)
_ITEM = re.compile(r"\(([a-z]{1,2})\)\s")


def _excluding_item(text: str, chapter: str, heading: str) -> str:
    """The lettered item of a note that names `chapter` or `heading`, e.g. '(m) ... Chapter 96 ...'."""
    marks = [m.start() for m in _ITEM.finditer(text)] + [len(text)]
    target = re.compile(rf"\b(Chapter\s+{chapter}|heading\s+(No\.\s*)?{heading})\b", re.I)
    for a, b in zip(marks, marks[1:]):
        item = re.sub(r"[;,.\s\"]*(\bor|\band)?[;,.\s\"]*$", "", text[a:b].strip())
        if target.search(item) and len(item) >= 15:
            return item[:300]
    return ""


def add_exclusions(draft: Draft, state: dict, ctx) -> Draft:
    """Cite the note that keeps the material-based chapter from applying (deterministic, recorded tools)."""
    h = draft.heading
    if draft.out_of_scope or not re.fullmatch(r"96\d{2}", h or ""):
        return draft
    ex = state.get("extraction") or {}
    material_text = " ".join([m.get("name", "") for m in ex.get("materials") or []]
                             + [m.get("name", "") for m in ctx.request.get("materials") or []]
                             + [ctx.request.get("product_description", "")])
    if not _IRON_STEEL.search(material_text):
        return draft
    cited = {c.clause_id for c in draft.citations}

    def find() -> tuple[dict, str] | None:
        for p in ctx.evidence.values():
            if p.get("kind") in ("section_note", "chapter_note") and str(p.get("chapter") or p.get("section") or "") != "96":
                item = _excluding_item(p.get("text") or "", h[:2], h)
                if item:
                    return p, item
        return None

    hit = find()   # already retrieved (e.g. by the model, or in an earlier attempt): no extra tool calls
    if hit is None:
        query = f"{draft.article or ex.get('article', '')} of iron or steel".strip()
        found, _ = tools.execute(ctx, AGENT, ALLOWED, "search_corpus",
                                 {"query": query, "kinds": ["heading"], "chapters": ["73"], "mode": "hybrid"})
        cand = next((p for p in found if isinstance(p, dict) and str(p.get("clause_id", "")).startswith("HDG-73")),
                    None) if isinstance(found, list) else None
        if cand is None:
            return draft
        tools.execute(ctx, AGENT, ALLOWED, "get_applicable_notes", {"clause_id": cand["clause_id"]})
        hit = find()
    if hit is None:
        return draft
    p, item = hit
    if p["clause_id"] not in cited:
        draft.citations.append(Citation(clause_id=p["clause_id"], passage_id=p["passage_id"], quote=item))
    if p["clause_id"] not in (draft.reasoning_summary or ""):
        draft.reasoning_summary = (f"{draft.reasoning_summary} Chapter 73 (articles of iron or steel) does not "
                                   f"apply: {p['clause_id']} excludes '{item[:120]}'.").strip()
    return draft
