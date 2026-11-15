"""Test harness: fake retriever (A.7) in-process, the stub's logic as a zero-delay scripted LLM,
fakeredis for the breaker, and a list as the run_steps sink. Run inside the container:
    docker compose run --rm agent-worker python -m pytest -q tests
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["STUB_DELAY_MIN_S"] = os.environ["STUB_DELAY_MAX_S"] = "0"
sys.path.insert(0, str(Path(__file__).parent))

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fake_retriever  # noqa: E402
import llm_stub_app  # noqa: E402  (copied from services/llm_stub/stub.py in the Dockerfile)
from agent_worker import config, prompts  # noqa: E402
from agent_worker.llm import LLMClient  # noqa: E402
from agent_worker.recorder import Budget, StepRecorder  # noqa: E402
from agent_worker.state import RunContext  # noqa: E402
from agent_worker.tools import RetrieverTools  # noqa: E402

# Captured before the autouse fixture swaps in test values: the real services, for integration tests.
REAL_ENV = {k: os.environ.get(k, "") for k in ("RETRIEVER_URL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                                               "LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_MODEL",
                                               "REDIS_URL")}
FLASK = "Stainless steel vacuum flask with a moulded plastic outer body."
TEST_ENV = {"LLM_BASE_URL": "http://llm.test/v1", "LLM_API_KEY": "x", "LLM_MODEL": "test-model",
            "LLM_FALLBACK_BASE_URL": "", "LLM_FALLBACK_MODEL": "", "LLM_MAX_RETRIES": "2", "LLM_TIMEOUT_S": "5",
            "LLM_PRICE_IN_PER_1K": "0.00059", "LLM_PRICE_OUT_PER_1K": "0.00079", "AGENT_MAX_STEPS": "20",
            "AGENT_MAX_TOOL_CALLS": "16", "AGENT_MAX_WALL_S": "60", "PROMPT_VERSION": "classifier@v2",
            "RETRIEVER_URL": "http://retriever.test", "LLM_FORCE_FAIL": "", "CB_FAILURE_THRESHOLD": "3"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)


def stub_answer(body: dict) -> dict:
    return asyncio.run(llm_stub_app.chat(body))


class ScriptedLLM:
    """httpx transport that answers like the llm-stub. `hook(role, body, response)` may rewrite a reply,
    or return an httpx.Response to simulate provider failures."""

    def __init__(self, hook=None):
        self.hook, self.bodies = hook, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        role = system.split("ROLE:")[1].split()[0] if "ROLE:" in system else "unknown"
        resp = stub_answer(body)
        if self.hook:
            out = self.hook(role, body, resp)
            if isinstance(out, httpx.Response):
                return out
            resp = out or resp
        return httpx.Response(200, json=resp)


def make_ctx(description: str = FLASK, llm: ScriptedLLM | None = None, redis=None, request: dict | None = None,
             prompt_version: str | None = None) -> RunContext:
    s = config.load()
    req = request or {"product_description": description, "destination_country": "AE"}
    llm = llm or ScriptedLLM()
    http_llm = httpx.Client(transport=httpx.MockTransport(llm))
    pv = prompt_version or s.prompt_version
    ctx = RunContext(run_id="00000000-0000-0000-0000-000000000001", request=req, settings=s,
                     llm=LLMClient(s, redis or fakeredis.FakeRedis(), http=http_llm, sleep=lambda _: None),
                     tools=RetrieverTools(s.retriever_url, "test-cid", http=TestClient(fake_retriever.app)),
                     recorder=StepRecorder("00000000-0000-0000-0000-000000000001", None),
                     budget=Budget(s.max_steps, s.max_tool_calls, s.max_wall_s),
                     prompts=prompts.resolve(pv), prompt_version=pv)
    ctx.scripted = llm
    return ctx
