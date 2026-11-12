"""Step 4 - Policy & Routing (F6, F7), plus the degraded retrieval-only path (A5).

Rules (first match wins). Only one path ends in clear-for-filing:
  stop: injection / budget        -> escalated, specialist-classification-review
  stop: toxic input / error       -> failed,    specialist-classification-review
  no draft / nothing retrieved / out of scope -> escalated, specialist
  verification failed (3 tries)   -> escalated, specialist
  2+ headings equal after GRI 3   -> escalated, specialist
  verified heading, missing facts -> completed, seek-product-clarification
  verified code, no policy row    -> escalated, specialist
  verified code + policy found    -> completed, clear-for-filing
Tool permission: get_export_policy only.
"""
from __future__ import annotations

import re

from agent_worker import tools
from agent_worker.recorder import BudgetExceeded
from agent_worker.state import Decision, Draft

AGENT = "router"
ALLOWED = {"get_export_policy"}
SPECIALIST, CLARIFY, CLEAR = "specialist-classification-review", "seek-product-clarification", "clear-for-filing"


def parse_policy(passages: list[dict], code: str) -> dict:
    ranked = sorted(passages, key=lambda p: p.get("clause_id") != f"EXP-{code}")
    for p in ranked:
        m = re.search(r"\b(Free|Restricted|Prohibited|STE)\b", p.get("text") or "")
        if m:
            return {"policy": m.group(1), "conditions": re.sub(r"\s+", " ", p["text"]).strip()[:400],
                    "clause_id": p.get("clause_id")}
    return {"policy": "unknown", "conditions": "No export policy row found in the corpus.", "clause_id": None}


def _escalate(reason: str, status: str = "escalated") -> Decision:
    return Decision(status=status, route=SPECIALIST, route_basis=reason, escalation_reason=reason)


def decide(state: dict, ctx) -> Decision:
    stop = state.get("stop") or {}
    if stop.get("kind") == "injection":
        return _escalate("Possible prompt injection in the request; it was not sent to the classifier. "
                         f"A specialist must review it ({stop.get('reason')}).")
    if stop.get("kind") == "toxic":
        return _escalate(f"Request rejected: {stop.get('reason')}.", status="failed")
    if stop.get("kind") == "budget":
        return _escalate(f"The agent hit a loop limit before a verified answer ({stop.get('reason')}); "
                         "escalated instead of guessing.")
    if stop.get("kind") == "error":
        return _escalate(f"The run failed internally ({stop.get('reason')}); no answer is given.", status="failed")
    if not state.get("draft"):
        return _escalate("No classification was produced.")
    draft = Draft.model_validate(state["draft"])
    v = state.get("verification") or {}
    if not any(p.get("kind") in ("heading", "tariff_line") for p in ctx.evidence.values()):
        return _escalate("The corpus search returned no candidate headings, so the product can be neither "
                         "classified nor confirmed out of scope.")
    if draft.out_of_scope:
        return _escalate("The product does not fall under Customs Tariff Chapters 73 or 96, which is the scope "
                         "of this service.")
    if not v.get("passed"):
        return _escalate(f"The answer could not be verified against the retrieved passages after "
                         f"{v.get('attempts', 0)} attempts: " + "; ".join((v.get("problems") or [])[:3]))
    if len(draft.competing_headings) >= 2:
        return _escalate(f"Headings {' and '.join(draft.competing_headings)} remain equally supported after GRI 3.")

    lookup = draft.proposed_hs_code or draft.heading
    try:
        result, status = tools.execute(ctx, AGENT, ALLOWED, "get_export_policy", {"hs_code": lookup})
    except BudgetExceeded:
        result, status = {"error": "tool budget spent"}, "error"
    passages = [ctx.evidence[p["passage_id"]] for p in result if p.get("passage_id") in ctx.evidence] \
        if isinstance(result, list) else []
    policy = parse_policy(passages, lookup)
    rule = draft.decided_by
    if draft.missing_facts and not draft.proposed_hs_code:
        return Decision(status="completed", route=CLARIFY, export_policy=policy,
                        route_basis=f"Heading {draft.heading} is decided by {rule} and verified, but the tariff line "
                                    f"depends on facts the description does not give: {', '.join(draft.missing_facts)}.")
    if not draft.proposed_hs_code:
        return _escalate(f"Heading {draft.heading} is verified but no 8-digit tariff line could be chosen.")
    if policy["policy"] == "unknown":
        return _escalate(f"Tariff line {draft.proposed_hs_code} is verified but no export policy row was found.")
    return Decision(status="completed", route=CLEAR, export_policy=policy, proposed_hs_code=draft.proposed_hs_code,
                    route_basis=f"Single heading {draft.heading} decided by {rule}, verified against the cited "
                                f"passages; export policy {policy['policy']} ({policy['clause_id']}).")


def run(state: dict, ctx) -> dict:
    d = decide(state, ctx)
    with ctx.recorder.step(AGENT, "route", "decide", {"stop": state.get("stop"),
                                                      "verified": (state.get("verification") or {}).get("passed")}) as rec:
        rec["output"] = d.model_dump()
    return {"decision": d.model_dump()}


def degrade(state: dict, ctx) -> dict:
    """Retrieval-only result when no LLM can be reached: candidates, never a code."""
    reason = (state.get("stop") or {}).get("reason", "LLM unavailable")
    if not any(p.get("kind") in ("heading", "tariff_line") for p in ctx.evidence.values()):
        try:
            tools.execute(ctx, AGENT, {"search_corpus"}, "search_corpus",
                          {"query": ctx.request.get("product_description", ""), "kinds": ["heading", "tariff_line"]})
        except BudgetExceeded:
            pass
    d = Decision(status="degraded", route=SPECIALIST, escalation_reason=reason,
                 route_basis="The language model is unavailable, so only a retrieval-only result is given: candidate "
                             "headings, not a classification. A specialist must classify.")
    with ctx.recorder.step(AGENT, "route", "degrade", {"reason": reason}) as rec:
        rec["output"] = d.model_dump()
    return {"decision": d.model_dump()}
