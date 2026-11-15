"""Unit tests for eval/metrics.py on hand-made runs whose correct scores are known.
Run: docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python -m pytest -q eval/test_metrics.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from judge import Judge  # noqa: E402
from metrics import claims_of, context_relevance, faithfulness, hallucination, retrieved_passages  # noqa: E402

HDG = {"passage_id": "p1", "clause_id": "HDG-9617", "kind": "heading", "heading": "9617",
       "text": "9617 VACUUM FLASKS AND OTHER VACUUM VESSELS, COMPLETE; PARTS THEREOF OTHER THAN GLASS INNERS"}
TL = {"passage_id": "p2", "clause_id": "TL-96170011", "kind": "tariff_line", "heading": "9617",
      "text": "Tariff item 9617 00 11: ---- Vacuum flasks having a capacity not exceeding 0.75 l"}
GN = {"passage_id": "p3", "clause_id": "EXP-GN-1", "kind": "export_policy", "heading": None,
      "text": "1. Free Exportability All goods other than the entries ... are freely exportable."}
CORPUS = {p["clause_id"]: [p] for p in (HDG, TL, GN)}
STEPS = [{"kind": "tool", "output": {"passages": [HDG, TL]}}, {"kind": "tool", "output": {"passages": [GN]}},
         {"kind": "llm", "output": {"passages": [{"passage_id": "x", "clause_id": "IGNORED", "text": "llm"}]}}]


def resolve(cid):
    return CORPUS.get(cid)


def good_result(**over):
    r = {"status": "completed", "route": "clear-for-filing", "heading": "9617", "proposed_hs_code": "96170011",
         "verification": {"passed": True}, "reasoning_summary": "Heading 9617 names vacuum flasks.",
         "route_basis": "Verified.", "export_policy": {"policy": "Free", "clause_id": "EXP-GN-1"},
         "citations": [{"clause_id": "HDG-9617", "passage_id": "p1", "quote": "VACUUM FLASKS"},
                       {"clause_id": "TL-96170011", "passage_id": "p2", "quote": "capacity not exceeding 0.75 l"}]}
    r.update(over)
    return r


def test_retrieved_passages_only_from_tool_steps():
    ids = [p["clause_id"] for p in retrieved_passages(STEPS)]
    assert ids == ["HDG-9617", "TL-96170011", "EXP-GN-1"]


def test_clean_run_does_not_hallucinate():
    assert hallucination(good_result(), retrieved_passages(STEPS), resolve)["value"] == 0.0


def test_fabricated_quote_is_a_hallucination():
    r = good_result(citations=[{"clause_id": "HDG-9617", "passage_id": "p1", "quote": "VACUUM FLASKS OF STEEL"}])
    out = hallucination(r, retrieved_passages(STEPS), resolve)
    assert out["value"] == 1.0 and "not an exact substring" in out["problems"][0]


def test_nonexistent_code_and_unretrieved_clause_are_hallucinations():
    r = good_result(proposed_hs_code="96179999", citations=[{"clause_id": "GRI-1", "quote": "x"}])
    problems = hallucination(r, retrieved_passages(STEPS), resolve)["problems"]
    assert any("does not exist" in p for p in problems) and any("96179999" in p for p in problems)


def test_faithfulness_all_checks_pass_for_clean_run():
    out = faithfulness(good_result(), [], resolve, lambda code: {"EXP-GN-1"})
    assert out["value"] == 1.0 and len(out["checks"]) >= 6


def test_faithfulness_catches_unverified_clear_and_wrong_policy():
    r = good_result(verification={"passed": False}, export_policy={"clause_id": "EXP-96020030"})
    out = faithfulness(r, [], resolve, lambda code: {"EXP-GN-1"})
    failed = [c["check"] for c in out["checks"] if not c["ok"]]
    assert any("verified" in c for c in failed) and any("export policy" in c for c in failed)


def test_context_recall_counts_supporting_clauses():
    out = context_relevance({"product_description": "vacuum flask"}, retrieved_passages(STEPS), Judge("lexical"),
                            ["HDG-9617", "SEC-XV-NOTE-1"])
    assert out["recall"] == 0.5 and out["missing"] == ["SEC-XV-NOTE-1"]


def test_lexical_judge_requires_codes_to_appear():
    j = Judge("lexical")
    verdicts, method = j.claims_supported(["Tariff item 96170011 covers vacuum flasks.",
                                           "Tariff item 73239390 covers vacuum flasks."], [TL["text"], HDG["text"]])
    assert method == "lexical" and verdicts == [True, False]


def test_groundedness_not_applicable_without_citations():
    from metrics import groundedness

    r = good_result(citations=[], reasoning_summary="No verified classification. The agent hit a loop limit.")
    out = groundedness(r, retrieved_passages(STEPS), resolve, Judge("lexical"))
    assert out["value"] is None and out["not_applicable"] == "no citations"


def test_claims_split_into_sentences():
    assert len(claims_of({"reasoning_summary": "GRI 1 decides. Heading 9617 names the article.",
                          "route_basis": "Verified; policy Free."})) == 4
