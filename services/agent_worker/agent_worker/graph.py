"""LangGraph topology (A1, A2). See docs/agent_design.md for the diagram.

  START -> input_guard -> intake -> classifier -> verifier --passed--> policy_route -> END
                                        ^             |
                                        +--retry------+  (max 2 retries, new strategy each time)
  any node: LLM unavailable -> degrade -> END ; loop bound / injection / toxic / error -> policy_route
"""
from __future__ import annotations

import logging
import re

from langgraph.graph import END, START, StateGraph

from agent_worker import guardrails
from agent_worker.agents import classifier, intake, router, verifier
from agent_worker.llm import LLMUnavailable
from agent_worker.metrics import runs_total, steps_per_run
from agent_worker.recorder import BudgetExceeded
from agent_worker.state import Draft, RunState
from contracts import Citation, Escalation, ExportPolicy, Guardrails, Result, Usage, Verification

log = logging.getLogger("agent_worker.graph")
_OUTCOME = {"degraded": "degraded", "budget": "escalated", "injection": "escalated", "toxic": "failed",
            "error": "failed"}


def input_guard(state: dict, ctx) -> dict:
    with ctx.recorder.step("input_guard", "guardrail", "injection_scan",
                           guardrails.free_text_fields(ctx.request)) as rec:
        hits = guardrails.scan_injection(ctx.request)
        rec["output"] = {"injection_detected": bool(hits), "hits": hits}
        rec["status"] = "blocked" if hits else "ok"
    guard = {"injection_detected": bool(hits), "injection_fields": hits, "toxicity_flag": False, "toxicity": None}
    with ctx.recorder.step("input_guard", "guardrail", "toxicity_scan", None) as rec:
        try:
            score = guardrails.toxicity(list(guardrails.free_text_fields(ctx.request).values()))
            guard["toxicity"] = round(score, 4)
            guard["toxicity_flag"] = score >= ctx.settings.toxicity_threshold
            rec["output"] = {"max_score": guard["toxicity"], "threshold": ctx.settings.toxicity_threshold}
            rec["status"] = "blocked" if guard["toxicity_flag"] else "ok"
        except Exception as exc:  # noqa: BLE001 - fail open: injection scan + output filter still apply
            rec["output"], rec["status"] = {"error": f"toxicity model unavailable: {exc}"}, "error"
    if hits:
        return {"guard": guard, "stop": {"kind": "injection", "reason": f"suspicious fields: {', '.join(hits)}"}}
    if guard["toxicity_flag"]:
        return {"guard": guard, "stop": {"kind": "toxic", "reason": f"toxic language (score {guard['toxicity']})"}}
    return {"guard": guard}


def _node(agent: str, fn):
    def wrapped(state: RunState, config) -> dict:
        ctx = config["configurable"]["ctx"]
        try:
            update = fn(state, ctx)
        except LLMUnavailable as exc:
            update = {"stop": {"kind": "degraded", "reason": f"LLM unavailable in {agent}: {exc}"[:500]}}
        except BudgetExceeded as exc:
            update = {"stop": {"kind": "budget", "reason": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - any agent crash ends the run safely, never confidently
            log.exception("%s failed", agent, extra={"event": "agent_error"})
            update = {"stop": {"kind": "error", "reason": f"{agent}: {type(exc).__name__}: {exc}"[:500]}}
        stop = update.get("stop")
        outcome = _OUTCOME[stop["kind"]] if stop else "success"
        if agent == "verifier" and not stop and not update["verification"]["passed"]:
            outcome = "failed"
        if agent in ("policy_route", "degrade") and "decision" in update:
            outcome = {"completed": "success"}.get(update["decision"]["status"], update["decision"]["status"])
        runs_total.labels(agent=agent, outcome=outcome).inc()
        return update
    return wrapped


def _after(state: RunState, normal: str) -> str:
    stop = state.get("stop")
    if stop:
        return "degrade" if stop["kind"] == "degraded" else "policy_route"
    return normal


def _after_verifier(state: RunState) -> str:
    if state.get("stop"):
        return _after(state, "")
    v = state["verification"]
    if v["passed"] or v["attempts"] >= verifier.MAX_ATTEMPTS:
        return "policy_route"
    return "classifier"


def build():
    g = StateGraph(RunState)
    g.add_node("input_guard", _node("input_guard", input_guard))
    g.add_node("intake", _node("intake", intake.run))
    g.add_node("classifier", _node("classifier", classifier.run))
    g.add_node("verifier", _node("verifier", verifier.run))
    g.add_node("policy_route", _node("policy_route", router.run))
    g.add_node("degrade", _node("degrade", router.degrade))
    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", lambda s: _after(s, "intake"), ["intake", "policy_route", "degrade"])
    g.add_conditional_edges("intake", lambda s: _after(s, "classifier"), ["classifier", "policy_route", "degrade"])
    g.add_conditional_edges("classifier", lambda s: _after(s, "verifier"), ["verifier", "policy_route", "degrade"])
    g.add_conditional_edges("verifier", _after_verifier, ["classifier", "policy_route", "degrade"])
    g.add_edge("policy_route", END)
    g.add_edge("degrade", END)
    return g.compile()


GRAPH = build()


def run(ctx) -> Result:
    state = GRAPH.invoke({"attempt": 0}, config={"configurable": {"ctx": ctx}, "recursion_limit": 40})
    result = build_result(state, ctx)
    for agent, n in ctx.recorder.per_agent.items():
        steps_per_run.labels(agent=agent).observe(n)
    return result


def _valid_citations(draft: Draft, ctx) -> list[Citation]:
    return [c for c in draft.citations if not verifier.check_citations(Draft(citations=[c]), ctx.evidence)]


def _degraded_citations(ctx) -> tuple[list[Citation], list[str]]:
    cands = [p for p in ctx.evidence.values() if p.get("kind") == "heading"][:4]
    cits = [Citation(clause_id=p["clause_id"], passage_id=p["passage_id"], quote=(p.get("text") or "")[:160])
            for p in cands if (p.get("text") or "").strip()]
    return cits, [f"{p.get('heading') or p['clause_id']} ({(p.get('title') or '').strip()[:60]})" for p in cands]


def build_result(state: dict, ctx) -> Result:
    d = state["decision"]
    guard = state.get("guard") or {}
    v = state.get("verification") or {}
    ex = state.get("extraction") or {}
    draft = Draft.model_validate(state["draft"]) if state.get("draft") else None
    verified = bool(v.get("passed")) and draft is not None
    filtered = False

    if d["status"] == "degraded":
        citations, cands = _degraded_citations(ctx)
        summary = ("Retrieval-only result (the language model was unavailable). Candidate headings found: "
                   + (", ".join(cands) if cands else "none") + ". This is not a classification.")
        heading, gri, code = None, [], None
    elif verified:  # verified evidence is shown on every route; the code only on clear-for-filing (below)
        citations = _valid_citations(draft, ctx)
        summary, heading, gri, code = draft.reasoning_summary, draft.heading or None, draft.gri_applied, d.get("proposed_hs_code")
    else:
        citations, heading, gri, code = [], None, [], None
        summary = "No verified classification. " + (d["escalation_reason"] or "")
        if draft and draft.out_of_scope:
            summary = draft.reasoning_summary or summary
            citations = _valid_citations(draft, ctx)

    summary, f1 = guardrails.filter_output(summary)
    basis, f2 = guardrails.filter_output(d["route_basis"])
    filtered = f1 or f2
    toxic_out = False
    try:
        if guardrails.toxicity([summary]) >= ctx.settings.toxicity_threshold:
            summary, toxic_out, filtered = "[removed by output filter]", True, True
    except Exception:  # noqa: BLE001 - model missing: output filter above still applied
        pass
    if filtered:
        with ctx.recorder.step("output_guard", "guardrail", "output_filter", None) as rec:
            rec["output"] = {"output_filtered": True, "toxic_output": toxic_out}

    materials = [m["name"] for m in ex.get("materials") or []]
    if not materials:
        materials = [m["name"] for m in ctx.request.get("materials") or []]
    status = d["status"]
    route = d["route"]
    if route == "clear-for-filing" and not (verified and status == "completed"):  # A.5 invariant, belt and braces
        route, status = "specialist-classification-review", "escalated"
    escalated = route == "specialist-classification-review"
    pol = d.get("export_policy") or {}
    return Result(
        run_id=ctx.run_id,
        status=status,
        route=route,
        route_basis=basis,
        article=(draft.article if draft and draft.article else ex.get("article")) or None,
        materials=materials,
        proposed_hs_code=code if route == "clear-for-filing" else None,
        heading=heading if status != "degraded" else None,
        gri_applied=gri,
        reasoning_summary=re.sub(r"\s+", " ", summary).strip(),
        export_policy=ExportPolicy(**pol) if pol else ExportPolicy(),
        citations=citations,
        verification=Verification(passed=verified, attempts=int(v.get("attempts") or 0),
                                  unsupported_claims=list(v.get("problems") or [])),
        escalation=Escalation(escalated=escalated, reason=d.get("escalation_reason") if escalated else None),
        guardrails=Guardrails(injection_detected=bool(guard.get("injection_detected")),
                              toxicity_flag=bool(guard.get("toxicity_flag")) or toxic_out,
                              output_filtered=filtered),
        prompt_version=ctx.prompt_version,
        usage=Usage(prompt_tokens=ctx.recorder.prompt_tokens, completion_tokens=ctx.recorder.completion_tokens,
                    cost_usd=round(ctx.recorder.cost_usd, 6), steps=len(ctx.recorder.rows),
                    tool_calls=ctx.recorder.tool_calls, latency_ms=ctx.recorder.latency_ms()),
    )
