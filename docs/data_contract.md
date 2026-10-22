# Data contract: `POST /runs` (F1, D1)

Source of truth: `shared/contracts/request.py` (Pydantic v2). Published JSON Schema: `shared/contracts/request.schema.json`. Live OpenAPI: `http://localhost:8000/docs`.

## Fields

| Field | Required | Type / rule |
|---|---|---|
| `product_description` | yes | string, 10–2000 chars after trimming. Must contain at least 3 letters (not only digits/symbols) |
| `destination_country` | yes | ISO-3166 alpha-2, **uppercase**, from the allowed list in `request.py` (India excluded: these are exports from India) |
| `materials` | no | 1–10 items of `{name: 1–60 chars, share_pct: 0–100}` |
| `intended_use` | no | string ≤ 300 |
| `declared_hs_code` | no | 4, 6 or 8 digits (`^\d{4}(\d{2}){0,2}$`) |
| `quantity` | no | number > 0 |
| `unit` | no | one of `PCS, KG, SET, PAIR, DOZ` |
| `client_ref` | no | string ≤ 64 |
| `callback_url` | no | http(s) URL. The final result is POSTed here |

**Unknown fields are rejected.**

## Cross-field rules

1. If `materials` is given, `share_pct` values must sum to **100 ± 1**, and names must be unique (case-insensitive).
2. `quantity` and `unit` must be given together.
3. `declared_hs_code`, if given, must start with `73` or `96`. Anything else is out of scope and rejected at the boundary.

## Headers

- `X-Client-Id` (optional): identifies the client for rate limiting. Defaults to the caller's IP.
- `X-Correlation-ID` (optional): echoed back and carried through every service. Generated if missing.

## Responses

| Code | When | Body |
|---|---|---|
| 202 | accepted | `{run_id, status: "queued", cache_hit: false, poll_url}`, or `status: "completed", cache_hit: true` for a cache hit |
| 422 | invalid | `{quarantine_id, errors: [{field, error, value}], detail}`. **No run is created** |
| 429 | rate limited | `{detail, retry_after_s}` + `Retry-After` header |
| 503 | queue unavailable | the run is marked `failed`, nothing runs |

## Examples

Valid (the §4.1 demo case):
```json
{"product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
 "materials": [{"name": "stainless steel", "share_pct": 70}, {"name": "plastic", "share_pct": 30}],
 "destination_country": "AE", "quantity": 500, "unit": "PCS"}
```

Invalid. Each line produces one field-level error:
```json
{"product_description": "flask",          // < 10 chars
 "destination_country": "xx",             // not uppercase / not in list
 "quantity": -3,                          // must be > 0
 "rogue": 1}                              // unknown field
```
```json
{"product_description": "Steel water bottle", "destination_country": "US",
 "materials": [{"name": "steel", "share_pct": 40}]}     // shares sum to 40, not 100
```

## Other endpoints

`GET /runs/{id}`, `GET /runs/{id}/trace`, `POST /runs/{id}/feedback` (`{satisfactory: bool, reason: 1–500 chars}`), `GET /feedback/summary`, `GET /quarantine`, `GET /admin/stats`, `GET /health`, `GET /metrics`. The result body follows `shared/contracts/result.py` (contract A.5).
