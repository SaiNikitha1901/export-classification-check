"""Result data contract (shared contract A.5).

Invariant enforced here so every service gets it for free:
route == "clear-for-filing" only if verification passed and status == "completed".
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunStatus = Literal["queued", "running", "completed", "escalated", "degraded", "failed"]
FINAL_STATUSES: frozenset[str] = frozenset({"completed", "escalated", "degraded", "failed"})
Route = Literal["clear-for-filing", "seek-product-clarification", "specialist-classification-review"]

DISCLAIMER = "Proposed classification only. Not a filed declaration. A licensed customs broker decides."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportPolicy(_Strict):
    policy: Literal["Free", "Restricted", "Prohibited", "STE", "unknown"] = "unknown"
    conditions: str = ""
    clause_id: Optional[str] = None


class Citation(_Strict):
    clause_id: str
    passage_id: str
    quote: str = Field(min_length=1)


class Verification(_Strict):
    passed: bool = False
    attempts: int = 0
    unsupported_claims: list[str] = Field(default_factory=list)


class Escalation(_Strict):
    escalated: bool = False
    reason: Optional[str] = None
    to: str = "licensed customs broker / specialist"


class Guardrails(_Strict):
    injection_detected: bool = False
    toxicity_flag: bool = False
    output_filtered: bool = False


class Usage(_Strict):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    latency_ms: int = 0


class Result(_Strict):
    run_id: str
    status: RunStatus
    route: Route
    route_basis: str
    article: Optional[str] = None
    materials: list[str] = Field(default_factory=list)
    proposed_hs_code: Optional[str] = None
    heading: Optional[str] = None
    gri_applied: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    export_policy: ExportPolicy = Field(default_factory=ExportPolicy)
    citations: list[Citation] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)
    escalation: Escalation = Field(default_factory=Escalation)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    prompt_version: str
    usage: Usage = Field(default_factory=Usage)
    disclaimer: str = DISCLAIMER

    @model_validator(mode="after")
    def _no_confident_unverified_answer(self) -> "Result":
        if self.route == "clear-for-filing" and not (self.verification.passed and self.status == "completed"):
            raise ValueError("clear-for-filing requires status 'completed' and verification.passed")
        return self
