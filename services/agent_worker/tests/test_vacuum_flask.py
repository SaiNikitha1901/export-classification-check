"""Section 4.1 end to end against the REAL retriever (Member 2) and whatever LLM .env configures
(the llm-stub by default, a real provider when a key is set). Skips while the retriever is the
empty placeholder.

Expected values: from docs/eval1_corpus_confirmation.md (Member 2) once it exists. Until then they
come from the official First Schedule text: heading 9617; tariff lines 9617 00 11 (<= 0.75 l) and
9617 00 12 (> 0.75 l), so the 8-digit line needs the capacity; excluded from Chapter 73 by
Section XV Note 1(m) ("other articles of Chapter 96").
"""
import httpx
import pytest
import redis as redis_lib

import conftest
from agent_worker import config, graph, prompts
from agent_worker.llm import LLMClient
from agent_worker.recorder import Budget, StepRecorder
from agent_worker.state import RunContext
from agent_worker.tools import RetrieverTools

EXPECTED_HEADING = "9617"
EXPECTED_LINES = {"96170011", "96170012"}
EXCLUDING_NOTES = {"SEC-XV-NOTE-1"}


@pytest.fixture
def real_ctx(monkeypatch):
    for k, v in conftest.REAL_ENV.items():
        monkeypatch.setenv(k, v)
    url = conftest.REAL_ENV["RETRIEVER_URL"]
    try:
        info = httpx.get(f"{url}/index/info", timeout=5).json()
    except Exception:  # noqa: BLE001
        pytest.skip("retriever not reachable")
    if not info.get("chunk_count"):
        pytest.skip("retriever index is empty (placeholder)")
    s = config.load()

    def make(description):
        pv = s.prompt_version
        return RunContext(run_id="00000000-0000-0000-0000-0000000000f1",
                          request={"product_description": description, "destination_country": "AE"}, settings=s,
                          llm=LLMClient(s, redis_lib.Redis.from_url(s.redis_url)),
                          tools=RetrieverTools(s.retriever_url, "flask-test"),
                          recorder=StepRecorder("00000000-0000-0000-0000-0000000000f1"),
                          budget=Budget(s.max_steps, s.max_tool_calls, s.max_wall_s),
                          prompts=prompts.resolve(pv), prompt_version=pv)
    return make


def test_vacuum_flask_section_4_1(real_ctx):
    ctx = real_ctx(conftest.FLASK)
    r = graph.run(ctx)
    seen_chapters = {p.get("chapter") for p in ctx.evidence.values()}
    assert "flask" in (r.article or "").lower()
    assert "73" in seen_chapters                                    # the material-first chapter was looked at
    assert r.heading == EXPECTED_HEADING
    assert "GRI-1" in r.gri_applied
    cited = {c.clause_id for c in r.citations}
    assert f"HDG-{EXPECTED_HEADING}" in cited and "GRI-1" in cited and cited & EXCLUDING_NOTES
    assert r.verification.passed
    assert r.export_policy.policy != "unknown"
    assert r.route in ("seek-product-clarification", "clear-for-filing") and r.route_basis
    if r.proposed_hs_code:
        assert r.proposed_hs_code in EXPECTED_LINES


def test_flask_with_capacity_gets_the_line(real_ctx):
    r = graph.run(real_ctx(conftest.FLASK + " Capacity 1 litre."))
    assert r.route == "clear-for-filing" and r.proposed_hs_code == "96170012"
