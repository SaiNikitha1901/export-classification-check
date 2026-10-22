"""Request data contract (shared contract A.4).

Every request is validated against ProductRequest at the API boundary, before any
agent run starts. Field rules are declared on the fields; cross-field rules live in
the model validator and are reported with the field they concern.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

# Destination countries we accept (ISO-3166 alpha-2). India is excluded: these are exports from India.
ALLOWED_COUNTRIES: frozenset[str] = frozenset(
    """AE AR AU BD BE BH BR CA CH CL CN CO CZ DE DK DZ EG ES ET FI FR GB GH GR HK HU ID IE IL IQ IR IT
    JO JP KE KR KW LK MA MM MU MX MY NG NL NO NP NZ OM PE PH PK PL PT QA RO RU SA SE SG TH TR TW TZ
    UA UG US VN ZA ZM""".split()
)

IN_SCOPE_CHAPTERS = ("73", "96")
HS_CODE_RE = re.compile(r"^\d{4}(\d{2}){0,2}$")


class Unit(str, Enum):
    PCS = "PCS"
    KG = "KG"
    SET = "SET"
    PAIR = "PAIR"
    DOZ = "DOZ"


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    share_pct: float = Field(ge=0, le=100)


class ProductRequest(BaseModel):
    """A product to classify. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_ref: Optional[str] = Field(default=None, max_length=64)
    product_description: str = Field(min_length=10, max_length=2000)
    materials: Optional[list[Material]] = Field(default=None, min_length=1, max_length=10)
    intended_use: Optional[str] = Field(default=None, max_length=300)
    destination_country: str = Field(min_length=2, max_length=2)
    declared_hs_code: Optional[str] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    unit: Optional[Unit] = None
    callback_url: Optional[AnyHttpUrl] = None

    @field_validator("product_description")
    @classmethod
    def _description_has_words(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v)
        if sum(ch.isalpha() for ch in v) < 3:
            raise PydanticCustomError("no_words", "description must contain words, not only digits or symbols")
        return v

    @field_validator("destination_country")
    @classmethod
    def _country_known(cls, v: str) -> str:
        if v != v.upper():
            raise PydanticCustomError("country_case", "destination_country must be uppercase ISO-3166 alpha-2")
        if v not in ALLOWED_COUNTRIES:
            raise PydanticCustomError(
                "country_unknown", "destination_country '{value}' is not in the allowed list", {"value": v}
            )
        return v

    @field_validator("declared_hs_code")
    @classmethod
    def _hs_code_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not HS_CODE_RE.match(v):
            raise PydanticCustomError("hs_format", "declared_hs_code must be 4, 6 or 8 digits")
        return v

    @model_validator(mode="after")
    def _cross_field(self) -> "ProductRequest":
        issues: list[dict[str, str]] = []
        if self.materials:
            total = sum(m.share_pct for m in self.materials)
            if abs(total - 100) > 1:
                issues.append({"field": "materials", "error": f"material shares must sum to 100 ± 1 (got {total:g})"})
            names = [m.name.lower() for m in self.materials]
            if len(names) != len(set(names)):
                issues.append({"field": "materials", "error": "material names must be unique"})
        if self.quantity is not None and self.unit is None:
            issues.append({"field": "unit", "error": "unit is required when quantity is given"})
        if self.unit is not None and self.quantity is None:
            issues.append({"field": "quantity", "error": "quantity is required when unit is given"})
        if self.declared_hs_code and self.declared_hs_code[:2] not in IN_SCOPE_CHAPTERS:
            issues.append(
                {
                    "field": "declared_hs_code",
                    "error": f"chapter {self.declared_hs_code[:2]} is out of scope (only chapters 73 and 96)",
                }
            )
        if issues:
            raise PydanticCustomError(
                "cross_field", "{detail}", {"detail": "; ".join(i["error"] for i in issues), "issues": issues}
            )
        return self


def validate_request(payload: Any) -> tuple[Optional[ProductRequest], list[dict[str, Any]]]:
    """Validate a decoded JSON payload. Returns (request, []) or (None, field-level errors)."""
    if not isinstance(payload, dict):
        return None, [{"field": "__root__", "error": "request body must be a JSON object", "value": None}]
    try:
        return ProductRequest.model_validate(payload), []
    except ValidationError as exc:
        errors: list[dict[str, Any]] = []
        for err in exc.errors(include_url=False):
            issues = (err.get("ctx") or {}).get("issues")
            if err["type"] == "cross_field" and issues:
                for issue in issues:
                    errors.append({**issue, "value": payload.get(issue["field"])})
                continue
            field = ".".join(str(p) for p in err["loc"]) or "__root__"
            errors.append({"field": field, "error": err["msg"], "value": err.get("input")})
        return None, errors
