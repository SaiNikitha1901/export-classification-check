"""The typed hand-off between agents (A2) and the per-run context.

RunState is what LangGraph passes from node to node. Each agent reads only the fields it needs and
returns only the fields it owns:
  input_guard -> guard          intake -> extraction          classifier -> draft
  verifier    -> verification   policy_route -> decision      any agent -> stop (why the run ended early)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator

from contracts import Citation


class MaterialFact(BaseModel):
    name: str
    share_pct: Optional[float] = None


class Extraction(BaseModel):
    article: str
    function: str = ""
    materials: list[MaterialFact] = Field(default_factory=list)
    form: str = ""
    missing_facts: list[str] = Field(default_factory=list)
    source: str = "llm"  # "llm" | "fallback" (deterministic, when the LLM could not be used)


def _digits(v: Any) -> str:
    return re.sub(r"\D", "", str(v or ""))


class Draft(BaseModel):
    article: str = ""
    heading: str = ""
    proposed_hs_code: str = ""
    gri_applied: list[str] = Field(default_factory=list)
    decided_by: str = ""
    reasoning_summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    out_of_scope: bool = False
    competing_headings: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)

    @field_validator("heading", "proposed_hs_code", mode="before")
    @classmethod
    def _only_digits(cls, v):  # "9617.00.11" / "9617 00 11" -> "96170011"
        return _digits(v)

    @field_validator("gri_applied", mode="before")
    @classmethod
    def _norm_gri(cls, v):
        return [normalise_gri(x) for x in (v or [])]

    @field_validator("decided_by", mode="before")
    @classmethod
    def _norm_decided(cls, v):
        return normalise_gri(v) if v else ""

    @field_validator("competing_headings", mode="before")
    @classmethod
    def _norm_competing(cls, v):
        return [_digits(x)[:4] for x in (v or []) if _digits(x)]


def normalise_gri(v: Any) -> str:
    """'GRI 3 (b)', 'Rule 3(b)', 'gri-3b' -> 'GRI-3(b)'."""
    m = re.search(r"(\d)(?:\s*\(\s*([a-c])\s*\)|([a-c])\b)?", str(v), re.I)
    if not m:
        return str(v).strip()
    letter = m.group(2) or m.group(3)
    return f"GRI-{m.group(1)}" + (f"({letter.lower()})" if letter else "")


class VerificationOut(BaseModel):
    passed: bool = False
    attempts: int = 0
    problems: list[str] = Field(default_factory=list)   # deterministic + entailment findings, last attempt
    history: list[list[str]] = Field(default_factory=list)


class Decision(BaseModel):
    status: str
    route: str
    route_basis: str
    escalation_reason: Optional[str] = None
    export_policy: dict = Field(default_factory=dict)
    proposed_hs_code: Optional[str] = None


class RunState(TypedDict, total=False):
    guard: dict                  # {"injection_detected", "injection_fields", "toxicity_flag", "toxicity"}
    extraction: dict             # Extraction
    draft: Optional[dict]        # Draft (latest attempt)
    verification: dict           # VerificationOut
    attempt: int                 # classifier attempts made (0-based count)
    decision: dict               # Decision
    stop: Optional[dict]         # {"kind": "injection"|"toxic"|"budget"|"degraded"|"error", "reason": str}


@dataclass
class RunContext:
    """Per-run services and the evidence ledger. Not passed through LangGraph state because it holds
    clients; each run builds its own, so worker replicas share nothing in memory."""
    run_id: str
    request: dict
    settings: Any
    llm: Any
    tools: Any
    recorder: Any
    budget: Any
    prompts: dict
    prompt_version: str
    evidence: dict[str, dict] = field(default_factory=dict)   # passage_id -> passage, everything retrieved
    tool_log: list[dict] = field(default_factory=list)        # ordered tool calls (for the GRI-order check)

    def request_view(self) -> dict:
        from agent_worker.guardrails import delimit
        return {"request": delimit(self.request)}
