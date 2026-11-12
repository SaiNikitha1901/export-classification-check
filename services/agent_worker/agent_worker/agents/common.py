"""Helpers shared by the agents: one recorded LLM call, and lenient JSON parsing of model output."""
from __future__ import annotations

import json
import re
from typing import Any

from agent_worker.llm import LLMResponse


def call_llm(ctx, agent: str, step: str, messages: list[dict], prompt_id: str, *,
             tools: list[dict] | None = None, json_mode: bool = False) -> LLMResponse:
    """Budget-checked LLM call, recorded as one run_steps row with tokens and cost at call time (L5)."""
    ctx.budget.check("llm")
    with ctx.recorder.step(agent, "llm", step, {"messages": messages, "tools": [t["function"]["name"] for t in tools or []]},
                           prompt_version=prompt_id) as rec:
        resp = ctx.llm.chat(messages, agent=agent, step=step, run_id=ctx.run_id, tools=tools,
                            json_mode=json_mode, deadline=ctx.budget.deadline)
        rec.update(prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
                   cost_usd=resp.cost_usd,
                   output={"content": resp.content, "tool_calls": resp.tool_calls, "provider": resp.provider,
                           "attempts": resp.attempts, "errors": resp.errors})
    return resp


def parse_json(text: str) -> Any:
    """Parse a JSON object from model text, tolerating ```json fences and prose around it."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))
