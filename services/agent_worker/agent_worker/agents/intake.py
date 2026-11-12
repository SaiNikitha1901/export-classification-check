"""Agent 1 - Intake/Extraction (F3). Tool permission: get_request_fields only.

Output: Extraction (article, function, materials, form, missing_facts).
Failure handling: unparseable model output -> deterministic fallback extraction (run continues);
LLM unavailable -> LLMUnavailable propagates and the graph degrades the run.
"""
from __future__ import annotations

import logging
import re

from pydantic import ValidationError

from agent_worker import prompts, tools
from agent_worker.agents.common import call_llm, parse_json
from agent_worker.state import Extraction, MaterialFact

AGENT = "intake"
ALLOWED = {"get_request_fields"}
log = logging.getLogger("agent_worker.intake")


def fallback_extraction(request: dict) -> Extraction:
    desc = request.get("product_description") or ""
    article = re.split(r"\b(with|of|made of|for|,|;)\b", desc, maxsplit=1)[0].strip(" .") or desc[:60]
    return Extraction(article=article[:80], function=request.get("intended_use") or "",
                      materials=[MaterialFact(**m) for m in request.get("materials") or []], source="fallback")


def run(state: dict, ctx) -> dict:
    fields, _ = tools.execute(ctx, AGENT, ALLOWED, "get_request_fields", {})
    p = ctx.prompts["extractor"]
    messages = [{"role": "system", "content": p["system"]},
                {"role": "user", "content": prompts.render(p["user"], request_block=fields["request"])}]
    resp = call_llm(ctx, AGENT, "extract", messages, p["id"], json_mode=True)
    try:
        ex = Extraction.model_validate(parse_json(resp.content))
    except (ValueError, ValidationError) as exc:
        log.warning("extractor output unusable, using fallback: %s", exc, extra={"event": "extract_fallback"})
        ex = fallback_extraction(ctx.request)
    if ctx.request.get("materials"):  # declared shares are authoritative over the model's reading
        ex.materials = [MaterialFact(**m) for m in ctx.request["materials"]]
        ex.missing_facts = [f for f in ex.missing_facts if "material" not in f.lower()]
    return {"extraction": ex.model_dump()}
