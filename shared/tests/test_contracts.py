import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import Result, validate_request
from contracts.export_schemas import SCHEMAS, render

FLASK = {
    "product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
    "materials": [{"name": "stainless steel", "share_pct": 70}, {"name": "plastic", "share_pct": 30}],
    "destination_country": "AE",
    "quantity": 500,
    "unit": "PCS",
}


def fields(errors):
    return {e["field"] for e in errors}


def test_valid_flask_request():
    req, errors = validate_request(FLASK)
    assert errors == [] and req.destination_country == "AE"


def test_minimal_request():
    req, errors = validate_request({"product_description": "Steel wood screws", "destination_country": "US"})
    assert errors == [] and req.materials is None


@pytest.mark.parametrize(
    "patch,field",
    [
        ({"product_description": "short"}, "product_description"),
        ({"product_description": "x" * 2001}, "product_description"),
        ({"product_description": "1234567890 !!!"}, "product_description"),
        ({"destination_country": "ae"}, "destination_country"),
        ({"destination_country": "XX"}, "destination_country"),
        ({"destination_country": "IN"}, "destination_country"),
        ({"declared_hs_code": "96A7"}, "declared_hs_code"),
        ({"declared_hs_code": "84713010"}, "declared_hs_code"),
        ({"quantity": -1}, "quantity"),
        ({"unit": "LITRE"}, "unit"),
        ({"quantity": 5, "unit": None}, "unit"),
        ({"materials": [{"name": "steel", "share_pct": 50}]}, "materials"),
        ({"materials": [{"name": "steel", "share_pct": 50}, {"name": "Steel", "share_pct": 50}]}, "materials"),
        ({"materials": [{"name": "steel", "share_pct": 120}]}, "materials.0.share_pct"),
        ({"callback_url": "ftp://x"}, "callback_url"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_rejections_name_the_field(patch, field):
    payload = {**FLASK, **patch}
    payload = {k: v for k, v in payload.items() if v is not None}
    req, errors = validate_request(payload)
    assert req is None
    assert field in fields(errors), errors


def test_missing_required_fields():
    _, errors = validate_request({})
    assert {"product_description", "destination_country"} <= fields(errors)


def test_non_object_body():
    _, errors = validate_request(["not", "an", "object"])
    assert fields(errors) == {"__root__"}


def test_cross_field_reports_every_issue():
    _, errors = validate_request(
        {**FLASK, "declared_hs_code": "8471", "materials": [{"name": "a", "share_pct": 10}], "quantity": 2, "unit": None}
    )
    # unit=None with quantity set is a cross-field issue; the hs and materials issues are reported too
    assert {"declared_hs_code", "materials", "unit"} <= fields(errors)


def _result(**kw):
    base = {"run_id": "r1", "status": "completed", "route": "clear-for-filing", "route_basis": "b",
            "prompt_version": "classifier@v1", "verification": {"passed": True, "attempts": 1}}
    return Result.model_validate({**base, **kw})


def test_clear_for_filing_needs_verification():
    assert _result().route == "clear-for-filing"
    with pytest.raises(ValidationError):
        _result(verification={"passed": False})
    with pytest.raises(ValidationError):
        _result(status="degraded")


def test_published_schemas_are_up_to_date():
    here = Path(__file__).parents[1] / "contracts"
    for name, model in SCHEMAS.items():
        published = (here / f"{name}.schema.json").read_text()
        assert json.loads(published) == json.loads(render(model)), f"run: python -m contracts.export_schemas ({name})"
