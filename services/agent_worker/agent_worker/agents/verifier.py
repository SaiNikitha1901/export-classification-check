"""Agent 3 - Verifier (A3). Checks a draft BEFORE it can be returned.

1. Deterministic (code, not a model): every quote is exact text (whitespace/dash-normalised; fragments
   joined by '...' must each match, in order) from the text or title of a passage retrieved in this run
   under the cited clause_id; the heading and the deciding rule were
   retrieved and cited; the 8-digit code exists in the corpus under the cited heading; the GRI order
   was respected (a heading that names the article was searched for, applicable notes were read, and a
   displaced first candidate is explained by a cited note or rule).
2. LLM entailment (only if 1 passes): do the cited passages support each claim?
Tool permission: get_clause (to confirm a tariff line exists). Output: VerificationOut.
"""
from __future__ import annotations

import re

from agent_worker import prompts, tools
from agent_worker.agents.common import call_llm, parse_json
from agent_worker.state import Draft, VerificationOut

AGENT = "verifier"
ALLOWED = {"get_clause"}
MAX_ATTEMPTS = 3   # first answer + 2 retries, then escalate
VALID_GRI = {"GRI-1", "GRI-2(a)", "GRI-2(b)", "GRI-3(a)", "GRI-3(b)", "GRI-3(c)", "GRI-4", "GRI-5(a)", "GRI-5(b)",
             "GRI-6", "GRI-2", "GRI-3", "GRI-5"}
IN_SCOPE = ("73", "96")
RULE_CLAIMS = {
    "GRI-1": "Rule GRI-1 says classification is determined by the terms of the headings and any relative "
             "Section or Chapter Notes.",
    "GRI-6": "Rule GRI-6 says classification at subheading level follows the terms of the subheadings.",
}
_STOP = {"with", "and", "the", "for", "made", "other", "outer", "inner", "body", "moulded", "molded", "plastic",
         "plastics", "steel", "stainless", "iron", "metal", "base", "article", "articles", "part", "parts"}


_CHARMAP = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
                          "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026|\[\.\.\.\])\s*")


def _norm(s: str) -> str:
    """Whitespace collapsed, typographic dashes/quotes mapped to ASCII. Nothing else is forgiven."""
    return re.sub(r"\s+", " ", (s or "").translate(_CHARMAP)).strip()


def canonical_quote(quote: str, passage: dict) -> str:
    """The quote rewritten with the corpus's own characters, so anyone checking finds an exact substring.
    Models often type typographic dashes or spaces (e.g. 'sub\u2011chapters' for 'sub-chapters');
    only characters that _norm() treats as equal are replaced. Fragments joined by '...' are kept."""
    texts = [passage.get("text") or "", passage.get("title") or ""]

    def exact(fragment: str) -> str | None:
        words = _norm(fragment).split(" ")
        pattern = r"\s+".join(re.escape(w) for w in words if w)
        for t in texts:
            m = re.search(pattern, t.translate(_CHARMAP)) if pattern else None
            if m:
                return t[m.start():m.end()]
        return None

    whole = exact(quote)
    if whole:
        return whole
    parts = [x for x in _ELLIPSIS.split(_norm(quote)) if x]
    found = [exact(x) for x in parts]
    return " … ".join(found) if len(parts) > 1 and all(found) else quote


def quote_in_passage(quote: str, passage: dict) -> bool:
    """True if the quote is exact text from the passage (its text or its title). Models shorten long
    notes with '...': each fragment between ellipses must then appear exactly, in order, and the
    fragments together must still be substantial (>= 15 characters)."""
    haystacks = [_norm(passage.get("text", "")), _norm(passage.get("title", ""))]
    q = _norm(quote)
    if any(q and q in h for h in haystacks):
        return True
    parts = [x for x in _ELLIPSIS.split(q) if x]
    if len(parts) < 2 or sum(len(x) for x in parts) < 15:
        return False
    for h in haystacks:
        pos = 0
        for part in parts:
            pos = h.find(part, pos)
            if pos < 0:
                break
            pos += len(part)
        else:
            return True
    return False


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def article_terms(*names: str) -> set[str]:
    words = {w for n in names for w in re.findall(r"[a-zA-Z]+", n or "")}
    return {_stem(w) for w in words if len(w) >= 4 and w.lower() not in _STOP}


def _heading_of(clause_id: str) -> str:
    d = re.sub(r"\D", "", clause_id or "")
    return d[:4] if clause_id.startswith(("HDG-", "TL-", "EXP-")) and len(d) >= 4 else ""


def check_citations(draft: Draft, evidence: dict[str, dict]) -> list[str]:
    problems = []
    for i, c in enumerate(draft.citations, 1):
        p = evidence.get(c.passage_id)
        if p is None:
            problems.append(f"citation {i} ({c.clause_id}): passage {c.passage_id} was not retrieved in this run")
        elif p.get("clause_id") != c.clause_id:
            problems.append(f"citation {i}: passage {c.passage_id} is clause {p.get('clause_id')}, not {c.clause_id}")
        elif len(_norm(c.quote)) < 15:
            problems.append(f"citation {i} ({c.clause_id}): quote is too short to be evidence")
        elif not quote_in_passage(c.quote, p):
            problems.append(f"citation {i} ({c.clause_id}): quote is not exact text from passage {c.passage_id} "
                            "(copy the words exactly; '...' may join exact fragments)")
    return problems


def check_draft(draft: Draft, evidence: dict[str, dict], tool_log: list[dict], extraction: dict,
                known_clauses: set[str] | None = None) -> list[str]:
    """All deterministic checks. Pure function: easy to test, impossible to talk round.
    known_clauses: clause ids known to exist (retrieved + the verifier's own lookups)."""
    problems = check_citations(draft, evidence)
    cited = {c.clause_id for c in draft.citations}
    retrieved = {p.get("clause_id") for p in evidence.values()}
    known = retrieved | (known_clauses or set())
    if draft.out_of_scope:
        return problems
    if len(draft.competing_headings) >= 2:
        return problems  # the router escalates; nothing confident is returned
    if not draft.citations:
        problems.append("no citations: every claim must be supported by a retrieved passage")
    h = draft.heading
    if not re.fullmatch(r"\d{4}", h):
        return problems + ["no 4-digit heading given (set out_of_scope or competing_headings instead)"]
    if h[:2] not in IN_SCOPE:
        problems.append(f"heading {h} is outside chapters 73 and 96: set out_of_scope instead")
    if f"HDG-{h}" not in retrieved:
        problems.append(f"heading HDG-{h} was never retrieved in this run")
    elif f"HDG-{h}" not in cited:
        problems.append(f"heading HDG-{h} is not cited")
    if not draft.decided_by or draft.decided_by not in VALID_GRI:
        problems.append(f"decided_by {draft.decided_by!r} is not a GRI rule")
    elif draft.decided_by not in draft.gri_applied:
        problems.append(f"decided_by {draft.decided_by} is missing from gri_applied")
    elif not any(c.split("(")[0] == draft.decided_by.split("(")[0] for c in cited if c.startswith("GRI-")):
        problems.append(f"the deciding rule {draft.decided_by} is not cited")
    code = draft.proposed_hs_code
    if code:
        if not re.fullmatch(r"\d{8}", code):
            problems.append(f"proposed_hs_code {code!r} is not 8 digits")
        elif not code.startswith(h):
            problems.append(f"tariff line {code} does not sit under heading {h}")
        elif f"TL-{code}" not in known:
            problems.append(f"tariff line TL-{code} does not exist in the corpus")
        if "GRI-6" not in draft.gri_applied:
            problems.append("an 8-digit line was chosen but GRI-6 (subheadings) is not in gri_applied")
    # GRI order (spec section 5, steps 1-3)
    searches = [t for t in tool_log if t["agent"] == "classifier" and t["tool"] == "search_corpus"]
    terms = article_terms(draft.article, extraction.get("article", ""))
    named = [t for t in searches
             if (not t["args"].get("kinds") or "heading" in t["args"]["kinds"])
             and terms & {_stem(w) for w in re.findall(r"[a-zA-Z]+", t["args"].get("query", ""))}]
    if terms and not named:
        problems.append(f"GRI order: no search for a heading that names the article ({', '.join(sorted(terms))})")
    if not any(t["tool"] == "get_applicable_notes" for t in tool_log if t["agent"] == "classifier"):
        problems.append("GRI order: the section/chapter notes for the candidate headings were never checked")
    first_hits = [_heading_of(c) for c in (searches[0]["clause_ids"] if searches else [])]
    first = next((x for x in first_hits if x), "")
    if first and first != h and not any(c.startswith(("SEC-", "CH", "GRI-3")) for c in cited):
        problems.append(f"the first candidate heading {first} was displaced without citing the note or rule that excludes it")
    return problems


def run(state: dict, ctx) -> dict:
    draft = Draft.model_validate(state["draft"])
    prev = VerificationOut.model_validate(state.get("verification") or {})
    evidence_before = dict(ctx.evidence)  # citations must resolve to what the CLASSIFIER retrieved
    code = draft.proposed_hs_code
    if code and f"TL-{code}" not in {p.get("clause_id") for p in evidence_before.values()}:
        tools.execute(ctx, AGENT, ALLOWED, "get_clause", {"clause_id": f"TL-{code}"})  # does the line exist?
    known = {p.get("clause_id") for p in ctx.evidence.values()}
    with ctx.recorder.step(AGENT, "verify", "deterministic_checks",
                           {"draft": draft.model_dump(mode="json"), "attempt": prev.attempts + 1}) as rec:
        problems = check_draft(draft, evidence_before, ctx.tool_log, state.get("extraction") or {}, known)
        rec["output"] = {"passed": not problems, "problems": problems}
        rec["status"] = "passed" if not problems else "failed"

    if not problems and draft.heading and not draft.out_of_scope and len(draft.competing_headings) < 2:
        problems = _entailment(draft, ctx)

    v = VerificationOut(passed=not problems, attempts=prev.attempts + 1, problems=problems,
                        history=prev.history + [problems])
    return {"verification": v.model_dump()}


def _entailment(draft: Draft, ctx) -> list[str]:
    # Each claim states what the cited text itself must say. ("Rule GRI-1 decides the heading" was
    # rejected by careful models: GRI 1's text names no heading, it says the heading terms and notes decide.)
    claims = [f"Heading {draft.heading} covers the article '{draft.article}'.",
              RULE_CLAIMS.get(draft.decided_by, f"Rule {draft.decided_by} is the rule that decides between the candidate headings.")]
    if draft.proposed_hs_code:
        claims.append(f"Tariff line {draft.proposed_hs_code} covers the article '{draft.article}'.")
    for c in draft.citations:
        if c.clause_id.startswith("SEC-") and draft.heading[:2] == "96":
            claims.append(f"{c.clause_id} excludes articles of Chapter 96 from that Section.")
            break
    seen, passages = set(), []
    for c in draft.citations:
        if c.passage_id not in seen:
            seen.add(c.passage_id)
            p = ctx.evidence[c.passage_id]
            passages.append(f"[{c.clause_id}] {p.get('title') or ''}\n{p.get('text', '')[:1500]}")
    p = ctx.prompts["verifier"]
    messages = [{"role": "system", "content": p["system"]},
                {"role": "user", "content": prompts.render(p["user"], claims="\n".join(f"- {c}" for c in claims),
                                                           passages="\n\n".join(passages))}]
    resp = call_llm(ctx, AGENT, "entailment", messages, p["id"], json_mode=True)
    with ctx.recorder.step(AGENT, "verify", "entailment_result", {"claims": claims}) as rec:
        try:
            out = parse_json(resp.content)
            supported = bool(out.get("supported"))
            unsupported = [str(x) for x in out.get("unsupported_claims") or []]
        except (ValueError, AttributeError):
            supported, unsupported = False, ["entailment check returned unreadable output"]
        if not supported and not unsupported:
            unsupported = ["the cited passages do not support the answer (entailment check)"]
        rec["output"] = {"supported": supported, "unsupported_claims": unsupported}
        rec["status"] = "passed" if supported else "failed"
    return [] if supported else [f"unsupported claim: {u}" for u in unsupported]
