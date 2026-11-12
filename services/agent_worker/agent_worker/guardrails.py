"""Guardrails (L4): prompt-injection detection, toxicity detection, output filtering.

Choice on injection: the run is ESCALATED to specialist review before any model sees the text
(not "strip and continue"). A partial strip can leave instructions behind for a model that holds
tools, and a human can resubmit a clean description in seconds. Documented in docs/agent_design.md.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger("agent_worker.guardrails")

# Instruction-like phrases, role markers, chat-template tokens, tool/JSON syntax, attempts to steer the route.
_INJECTION = [
    (r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b((instruction|rule|prompt|guardrail|directive)s?|(previous|above|prior)\s+(text|message|content|context))\b", "override_instructions"),
    (r"\b(you are now|act as|pretend to be|from now on you|new instructions?|developer mode|jailbreak)\b", "role_change"),
    (r"(^|\n|\s)(system|assistant|user|developer)\s*:", "role_marker"),
    (r"<\|?\s*(im_start|im_end|system|endoftext)\s*\|?>|\[/?INST\]|<</?SYS>>", "chat_template_token"),
    (r"</?\s*product_data\s*>", "delimiter_breakout"),
    (r"\b(tool_calls?|function_call|submit_classification|search_corpus|get_clause)\b", "tool_syntax"),
    (r"[{\[]\s*\"[a-z_]+\"\s*:", "json_payload"),
    (r"clear[- ]for[- ]filing|\broute\s+(this|it)\s+to\b|\b(mark|treat)\s+(this|it)\s+as\s+(verified|approved|cleared)\b", "route_steering"),
    (r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|your prompt|instructions)\b", "prompt_exfiltration"),
]
_INJECTION_RE = [(re.compile(p, re.I), name) for p, name in _INJECTION]


def detect_injection(text: str) -> list[str]:
    return [name for rx, name in _INJECTION_RE if rx.search(text or "")]


def free_text_fields(request: dict) -> dict[str, str]:
    """Every free-text field that can reach a model."""
    fields = {"product_description": request.get("product_description") or "",
              "intended_use": request.get("intended_use") or "",
              "client_ref": request.get("client_ref") or ""}
    for i, m in enumerate(request.get("materials") or []):
        fields[f"materials[{i}].name"] = m.get("name") or ""
    return {k: v for k, v in fields.items() if v}


def scan_injection(request: dict) -> dict[str, list[str]]:
    hits = {f: detect_injection(t) for f, t in free_text_fields(request).items()}
    return {f: h for f, h in hits.items() if h}


def delimit(request: dict) -> str:
    """Customer text always reaches a model inside <product_data> tags, with angle brackets neutralised."""
    lines = []
    for key in ("product_description", "intended_use", "destination_country", "declared_hs_code", "quantity", "unit"):
        if request.get(key) not in (None, ""):
            lines.append(f"{key}: {request[key]}")
    for m in request.get("materials") or []:
        lines.append(f"material: {m.get('name')} ({m.get('share_pct')}%)")
    body = "\n".join(lines).replace("<", "‹").replace(">", "›")
    return f"<product_data>\n{body}\n</product_data>"


# ---------------- toxicity (local detoxify model, loaded once per worker process) ----------------

@lru_cache(maxsize=1)
def _detoxify():
    from detoxify import Detoxify  # heavy import: torch + transformers
    return Detoxify("original-small", device="cpu")


def warm_up() -> None:
    try:
        _detoxify()
    except Exception:  # noqa: BLE001
        log.exception("toxicity model failed to load", extra={"event": "toxicity_model_error"})


def toxicity(texts: list[str]) -> float:
    """Highest toxicity score in [0,1] across texts. Raises if the model cannot load (caller decides)."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return 0.0
    scores = _detoxify().predict(texts)
    return float(max(max(v) if isinstance(v, list) else v for v in scores.values()))


# ---------------- output filtering ----------------

_NOT_FILED = " [This is a proposal only; nothing was filed.]"
_OUTPUT_RULES = [
    (re.compile(r"\s*[^.]*\b(declaration|bill of export|shipping bill)\b[^.]*\b(has been|was|is|been)\s+(filed|submitted|lodged)\b[^.]*\.?", re.I),
     _NOT_FILED),
    (re.compile(r"\s*[^.]*\b(we|i|the system)\s+(have\s+)?(filed|submitted|lodged)\b[^.]*\.?", re.I), _NOT_FILED),
    (re.compile(r"\b(final|binding|definitive|official|guaranteed|legally binding)\s+(classification|determination|ruling|decision|answer)\b", re.I),
     "proposed classification"),
    (re.compile(r"\s*[^.]*\b(duty|tariff rate|igst|bcd|customs duty|tax)\b[^.]*(\d+(\.\d+)?\s*%|₹|rs\.?\s*\d|inr\s*\d|usd\s*\d|\$\s*\d)[^.]*\.?", re.I),
     " [Duty amounts are out of scope for this service.]"),
]


def filter_output(text: str) -> tuple[str, bool]:
    """Rewrite determinations the system is not authorised to make. Returns (text, changed)."""
    out = text or ""
    for rx, replacement in _OUTPUT_RULES:
        out = rx.sub(replacement, out)
    return out, out != (text or "")
