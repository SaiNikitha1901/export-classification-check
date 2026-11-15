"""Evaluation metrics (L3, L6). Shared by the batch runner (eval/run_eval.py) and the live scorer
(services/retriever/retriever/live_scoring.py). How each metric is computed is documented in eval/METRICS.md.

Inputs per run: the Result (A.5), the run_steps trace, and a `resolve(clause_id) -> list[passage] | None`
function backed by the retriever's GET /clause (None = clause not in the corpus).
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from judge import Judge

Resolve = Callable[[str], Optional[list[dict]]]
# A claim ends at ";" or at "." followed by a capital/digit (so "c.i.f." and "0.75 l" do not split).
_SENT = re.compile(r"(?<=;)\s+|(?<=\.)\s+(?=[A-Z0-9])")


# ------------------------------------------------------------------ helpers

def retrieved_passages(steps: Iterable[dict]) -> list[dict]:
    """Every passage any tool returned during the run (deduplicated by passage_id, first-seen order)."""
    seen: dict[str, dict] = {}

    def walk(x):
        if isinstance(x, dict):
            if "passage_id" in x and "text" in x and "clause_id" in x:
                seen.setdefault(x["passage_id"], x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for s in steps:
        if s.get("kind") == "tool":
            walk(s.get("output"))
    return list(seen.values())


def claims_of(result: dict) -> list[str]:
    text = " ".join(filter(None, [result.get("reasoning_summary"), result.get("route_basis")]))
    return [c.strip() for c in _SENT.split(text) if len(c.strip()) > 8]


def cited_text(result: dict, retrieved: list[dict], resolve: Resolve) -> list[dict]:
    """The passages behind the citations: the retrieved passage with that id, else the clause from the corpus."""
    by_id = {p["passage_id"]: p for p in retrieved}
    out = []
    for c in result.get("citations") or []:
        p = by_id.get(c.get("passage_id"))
        if p is None:
            p = next(iter(resolve(c.get("clause_id", "")) or []), None)
        if p is not None:
            out.append(p)
    return out


# ------------------------------------------------------------------ metrics

def hallucination(result: dict, retrieved: list[dict], resolve: Resolve) -> dict:
    """1 if the run states anything that does not exist in the retrieved text or the corpus, else 0."""
    problems = []
    by_clause: dict[str, list[dict]] = {}
    for p in retrieved:
        by_clause.setdefault(p["clause_id"], []).append(p)
    for c in result.get("citations") or []:
        cid, quote = c.get("clause_id", ""), (c.get("quote") or "")
        if resolve(cid) is None:
            problems.append(f"cited clause {cid} does not exist in the corpus")
            continue
        texts = [p["text"] for p in by_clause.get(cid, [])]
        if not texts:
            problems.append(f"cited clause {cid} was never retrieved in this run")
        elif quote and not any(quote in t for t in texts):
            problems.append(f"quote for {cid} is not an exact substring of the retrieved passage")
    code = result.get("proposed_hs_code")
    if code and resolve(f"TL-{code}") is None:
        problems.append(f"HS code {code} is not a tariff item in the corpus")
    heading = result.get("heading")
    if heading and resolve(f"HDG-{heading}") is None:
        problems.append(f"heading {heading} is not in the corpus")
    pol = (result.get("export_policy") or {}).get("clause_id")
    if pol and resolve(pol) is None:
        problems.append(f"export policy clause {pol} does not exist")
    return {"value": 1.0 if problems else 0.0, "problems": problems}


def groundedness(result: dict, retrieved: list[dict], resolve: Resolve, judge: Judge) -> dict:
    """Share of claims in reasoning_summary + route_basis supported by the cited passages.
    Not applicable (None) when the run cites nothing: an escalation without citations makes no legal claim,
    only process statements ("no verified classification; loop limit reached"), and scoring those against
    passages would always give 0 and say nothing about grounding."""
    claims = claims_of(result)
    if not claims or not (result.get("citations") or []):
        return {"value": None, "claims": [], "method": None, "not_applicable": "no citations"}
    passages = cited_text(result, retrieved, resolve)
    verdicts, method = judge.claims_supported(claims, [p["text"] for p in passages])
    return {"value": sum(verdicts) / len(claims), "claims": [{"claim": c, "supported": v}
                                                              for c, v in zip(claims, verdicts)], "method": method}


def context_relevance(request: dict, retrieved: list[dict], judge: Judge, supporting: Optional[list[str]] = None,
                      max_passages: int = 10) -> dict:
    """Mean judged relevance (0, 0.5, 1) of the retrieved passages to the request, plus recall of the
    scenario's supporting clauses among everything retrieved (batch only)."""
    out: dict = {"value": None, "recall": None, "method": None}
    if retrieved:
        sample = retrieved[:max_passages]
        query = " ".join(filter(None, [request.get("product_description"), request.get("intended_use")]))
        scores, method = judge.passage_relevance(query, [p["text"] for p in sample])
        out.update(value=sum(scores) / len(scores), method=method, judged=len(sample), retrieved=len(retrieved))
    if supporting:
        got = {p["clause_id"] for p in retrieved}
        hit = [c for c in supporting if c in got]
        out["recall"] = len(hit) / len(supporting)
        out["missing"] = [c for c in supporting if c not in got]
    return out


def faithfulness(result: dict, retrieved: list[dict], resolve: Resolve, policy_lookup=None) -> dict:
    """Share of checks passed that the final heading / code / route / policy agree with the cited passages."""
    checks: list[tuple[str, bool]] = []
    cited = {c.get("clause_id", "") for c in result.get("citations") or []}
    heading, code, route = result.get("heading"), result.get("proposed_hs_code"), result.get("route")
    if heading:
        checks.append(("heading is cited (HDG or one of its TL)",
                       f"HDG-{heading}" in cited or any(c.startswith(f"TL-{heading}") for c in cited)))
        hp = resolve(f"HDG-{heading}") or []
        checks.append(("cited heading passage is that heading", any(p.get("heading") == heading for p in hp)))
    if code:
        checks.append(("code is under the heading", bool(heading) and code.startswith(heading)))
        checks.append(("tariff line of the code is cited", f"TL-{code}" in cited))
    ver = result.get("verification") or {}
    if route == "clear-for-filing":
        checks.append(("clear-for-filing only when verified and completed",
                       ver.get("passed") is True and result.get("status") == "completed" and bool(code)))
    if route == "specialist-classification-review":
        checks.append(("escalation carries no code", not code))
    pol = result.get("export_policy") or {}
    if code and policy_lookup and pol.get("clause_id"):
        expected = policy_lookup(code)
        if expected is not None:
            checks.append(("export policy clause matches the corpus for this code", pol["clause_id"] in expected))
    if not checks:
        return {"value": None, "checks": []}
    return {"value": sum(ok for _, ok in checks) / len(checks), "checks": [{"check": n, "ok": ok} for n, ok in checks]}


def score_run(request: dict, result: dict, steps: list[dict], resolve: Resolve, judge: Judge,
              supporting: Optional[list[str]] = None, policy_lookup=None) -> dict:
    retrieved = retrieved_passages(steps)
    return {
        "groundedness": groundedness(result, retrieved, resolve, judge),
        "context_relevance": context_relevance(request, retrieved, judge, supporting),
        "faithfulness": faithfulness(result, retrieved, resolve, policy_lookup),
        "hallucination": hallucination(result, retrieved, resolve),
        "retrieved_count": len(retrieved),
    }
