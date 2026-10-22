"""API gateway: the only public entry point.

Order of work on POST /runs: rate limit -> validate (quarantine on failure, no run) ->
whole-run cache -> insert run row -> enqueue RQ job by name -> 202 with run_id.
The API never imports agent code; the worker is found by the job's string name.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import redis
import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from rq import Queue
from starlette.responses import Response

from app import background, db, metrics, ratelimit, runcache, telemetry
from app.config import settings
from contracts import FINAL_STATUSES, ProductRequest, validate_request
from ecs_common import CORRELATION_HEADER, bind, new_correlation_id, setup_logging

setup_logging(settings.service, settings.log_level)
log = logging.getLogger("api")

redis_conn = redis.Redis.from_url(settings.redis_url)
queue = Queue(settings.queue_name, connection=redis_conn)
metrics.register_queue_collector(redis_conn, settings.queue_name)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.pool.open(wait=True, timeout=30)
    stop = background.start(redis_conn)
    log.info("api started", extra={"event": "startup"})
    yield
    stop.set()
    db.pool.close()


app = FastAPI(
    title="Export Classification Check API",
    version="0.1.0",
    description=(
        "Submit a product description; receive a proposed HS classification with citations, the export policy "
        "and a route. Proposed classification only - a licensed customs broker decides. "
        "Data contract: docs/data_contract.md."
    ),
    lifespan=lifespan,
)
telemetry.setup_tracing(app, settings.service, settings.otel_endpoint)


@app.middleware("http")
async def correlation_and_metrics(request: Request, call_next):
    cid = request.headers.get(CORRELATION_HEADER) or new_correlation_id()
    request.state.correlation_id = cid
    start = time.perf_counter()
    with bind(correlation_id=cid):
        telemetry.annotate(correlation_id=cid)
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"event": "http_error", "path": request.url.path})
            response = JSONResponse({"detail": "internal error", "correlation_id": cid}, status_code=500)
        elapsed = time.perf_counter() - start
        route = getattr(request.scope.get("route"), "path", "unmatched")
        metrics.http_requests.labels(metrics.SERVICE, route, str(response.status_code)).inc()
        metrics.http_latency.labels(metrics.SERVICE, route).observe(elapsed)
        if route not in ("/health", "/metrics"):
            log.info(
                "%s %s -> %s", request.method, route, response.status_code,
                extra={"event": "http_request", "latency_ms": round(elapsed * 1000, 1)},
            )
    response.headers[CORRELATION_HEADER] = cid
    return response


# ---------------------------------------------------------------- runs

def _client_id(request: Request, header_value: str | None) -> str:
    if header_value:
        return header_value[:64]
    return request.client.host if request.client else "unknown"


def _quarantine(client_id: str, payload: Any, errors: list[dict], cid: str) -> JSONResponse:
    qid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO quarantine (id, client_id, payload, errors) VALUES (%s, %s, %s, %s)",
        (qid, client_id, db.Jsonb(payload), db.Jsonb(errors)),
    )
    metrics.quarantined.inc()
    log.info("request quarantined", extra={"event": "quarantined", "quarantine_id": qid,
                                            "fields": sorted({e["field"] for e in errors})})
    return JSONResponse(
        {"quarantine_id": qid, "errors": errors, "correlation_id": cid,
         "detail": "request rejected at the ingestion boundary; no run was started"},
        status_code=422,
    )


def _inline_schema(model: type[BaseModel]) -> dict:
    """JSON schema with $defs inlined, so it can sit inside the OpenAPI document."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if ref.startswith("#/$defs/"):
                return resolve(defs[ref.rsplit("/", 1)[1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


_REQUEST_BODY_DOC = {
    "requestBody": {"required": True, "content": {"application/json": {"schema": _inline_schema(ProductRequest)}}}
}


@app.post("/runs", status_code=202, tags=["runs"], openapi_extra=_REQUEST_BODY_DOC,
          summary="Submit a product for classification (asynchronous)")
async def submit_run(request: Request, x_client_id: str | None = Header(default=None)):
    cid = request.state.correlation_id
    client_id = _client_id(request, x_client_id)

    allowed, retry_after = ratelimit.check(redis_conn, client_id, settings.rate_limit_per_min)
    if not allowed:
        metrics.rate_limited.inc()
        log.info("rate limited", extra={"event": "rate_limited", "client_id": client_id})
        return JSONResponse({"detail": "rate limit exceeded", "retry_after_s": retry_after},
                            status_code=429, headers={"Retry-After": str(retry_after)})

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _quarantine(client_id, {"raw": raw.decode("utf-8", "replace")[:4000]},
                           [{"field": "__root__", "error": "body is not valid JSON", "value": None}], cid)

    req, errors = validate_request(payload)
    if errors:
        return _quarantine(client_id, payload, errors, cid)

    run_id = str(uuid.uuid4())
    req_json = req.model_dump(mode="json", exclude_none=True)
    key = runcache.cache_key(req, settings.prompt_version, runcache.index_version(settings.retriever_url))

    with bind(run_id=run_id):
        telemetry.annotate(run_id=run_id)
        cached = runcache.get(redis_conn, key) if key else None
        if cached:
            metrics.cache_hits.labels("run").inc()
            result = {**cached["result"], "run_id": run_id,
                      "usage": {**cached["result"].get("usage", {}), "prompt_tokens": 0,
                                "completion_tokens": 0, "cost_usd": 0.0}}
            db.execute(
                "INSERT INTO runs (run_id, client_id, correlation_id, status, request, result, prompt_version, "
                "cache_hit, cached_from, cache_key) VALUES (%s,%s,%s,'completed',%s,%s,%s,true,%s,%s)",
                (run_id, client_id, cid, db.Jsonb(req_json), db.Jsonb(result), settings.prompt_version,
                 cached["run_id"], key),
            )
            log.info("served from run cache", extra={"event": "run_cache_hit", "cached_from": cached["run_id"]})
            return {"run_id": run_id, "status": "completed", "cache_hit": True, "poll_url": f"/runs/{run_id}"}
        if key:
            metrics.cache_misses.labels("run").inc()

        callback = req_json.get("callback_url")
        db.execute(
            "INSERT INTO runs (run_id, client_id, correlation_id, status, request, prompt_version, cache_key, "
            "trace_context, callback_url, callback_state) VALUES (%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s)",
            (run_id, client_id, cid, db.Jsonb(req_json), settings.prompt_version, key,
             db.Jsonb(telemetry.current_trace_context()), callback, "pending" if callback else None),
        )
        try:
            queue.enqueue(
                settings.job_func,
                kwargs={"run_id": run_id, "correlation_id": cid},
                job_id=run_id,
                job_timeout=settings.run_timeout_s,
                result_ttl=86400,
                failure_ttl=86400,
            )
        except redis.RedisError as exc:
            db.execute("UPDATE runs SET status='failed', error=%s, updated_at=now() WHERE run_id=%s",
                       (f"enqueue failed: {exc}", run_id))
            log.error("enqueue failed", extra={"event": "enqueue_failed"})
            raise HTTPException(503, "queue unavailable; run not started") from exc
        metrics.runs_submitted.inc()
        log.info("run queued", extra={"event": "run_queued", "client_id": client_id})
    return {"run_id": run_id, "status": "queued", "cache_hit": False, "poll_url": f"/runs/{run_id}"}


def _load_run(run_id: str) -> dict:
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(404, "run not found") from None
    row = db.fetch_one("SELECT * FROM runs WHERE run_id=%s", (run_id,))
    if not row:
        raise HTTPException(404, "run not found")
    return row


@app.get("/runs/{run_id}", tags=["runs"], summary="Poll a run's status and result")
def get_run(run_id: str):
    row = _load_run(run_id)
    return {
        "run_id": str(row["run_id"]),
        "status": row["status"],
        "result": row["result"],
        "error": row["error"],
        "cache_hit": row["cache_hit"],
        "prompt_version": row["prompt_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.get("/runs/{run_id}/trace", tags=["runs"], summary="Reconstruct a run: every step, tool call, prompt and cost")
def get_trace(run_id: str):
    row = _load_run(run_id)
    steps = db.fetch_all("SELECT * FROM run_steps WHERE run_id=%s ORDER BY step_no, id", (run_id,))
    totals = {
        "steps": len(steps),
        "tool_calls": sum(1 for s in steps if s["kind"] == "tool"),
        "latency_ms": sum(s["latency_ms"] or 0 for s in steps),
        "prompt_tokens": sum(s["prompt_tokens"] or 0 for s in steps),
        "completion_tokens": sum(s["completion_tokens"] or 0 for s in steps),
        "cost_usd": float(sum(s["cost_usd"] or 0 for s in steps)),
    }
    for s in steps:
        s["cost_usd"] = float(s["cost_usd"]) if s["cost_usd"] is not None else None
    run = {k: row[k] for k in ("run_id", "status", "client_id", "correlation_id", "request", "result",
                               "prompt_version", "cache_hit", "cached_from", "error", "created_at", "updated_at")}
    return {"run": run, "totals": totals, "steps": steps,
            "jaeger_hint": f"search Jaeger for tag run_id={run_id} or correlation_id={row['correlation_id']}"}


# ---------------------------------------------------------------- feedback (L6)

class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    satisfactory: bool
    reason: str = Field(min_length=1, max_length=500)


@app.post("/runs/{run_id}/feedback", status_code=201, tags=["feedback"])
def post_feedback(run_id: str, body: FeedbackIn):
    row = _load_run(run_id)
    if row["status"] not in FINAL_STATUSES:
        raise HTTPException(409, "run has not finished yet")
    inserted = db.execute(
        "INSERT INTO feedback (run_id, satisfactory, reason) VALUES (%s,%s,%s) ON CONFLICT (run_id) DO NOTHING",
        (run_id, body.satisfactory, body.reason),
    )
    if not inserted:
        raise HTTPException(409, "feedback already recorded for this run")
    metrics.feedback_total.labels(str(body.satisfactory).lower()).inc()
    return {"run_id": run_id, "recorded": True}


@app.get("/feedback/summary", tags=["feedback"])
def feedback_summary():
    overall = db.fetch_one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE satisfactory) AS satisfactory FROM feedback"
    )
    by_prompt = db.fetch_all(
        "SELECT r.prompt_version, count(*) AS total, count(*) FILTER (WHERE f.satisfactory) AS satisfactory "
        "FROM feedback f JOIN runs r USING (run_id) GROUP BY r.prompt_version ORDER BY r.prompt_version"
    )
    top_reasons = db.fetch_all(
        "SELECT lower(trim(reason)) AS reason, satisfactory, count(*) AS n FROM feedback "
        "GROUP BY 1, 2 ORDER BY n DESC LIMIT 10"
    )
    pct = lambda s, t: round(100.0 * s / t, 1) if t else None  # noqa: E731
    return {
        "total": overall["total"],
        "satisfactory": overall["satisfactory"],
        "pct_satisfactory": pct(overall["satisfactory"], overall["total"]),
        "by_prompt_version": [{**r, "pct_satisfactory": pct(r["satisfactory"], r["total"])} for r in by_prompt],
        "top_reasons": top_reasons,
    }


# ---------------------------------------------------------------- evidence for demos

@app.get("/quarantine", tags=["admin"], summary="Most recent quarantined requests with field-level errors")
def list_quarantine(limit: int = 20):
    return db.fetch_all("SELECT * FROM quarantine ORDER BY received_at DESC LIMIT %s", (min(limit, 200),))


@app.get("/admin/stats", tags=["admin"], summary="Counts used to prove a rejected request started no run")
def admin_stats():
    counts = db.fetch_one(
        "SELECT (SELECT count(*) FROM runs) AS runs_total, (SELECT count(*) FROM quarantine) AS quarantine_total"
    )
    return {**counts, "queue_length": len(queue)}


# ---------------------------------------------------------------- health, metrics, ui

@app.get("/health", tags=["ops"])
def health():
    checks: dict[str, str] = {}
    try:
        db.fetch_one("SELECT 1 AS ok")
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc.__class__.__name__}"
    try:
        redis_conn.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
    try:
        r = requests.get(f"{settings.retriever_url}/health", timeout=2)
        checks["retriever"] = "ok" if r.ok else f"http {r.status_code}"
    except requests.RequestException as exc:
        checks["retriever"] = f"error: {exc.__class__.__name__}"
    hard_fail = any(checks[k] != "ok" for k in ("postgres", "redis"))
    status = "down" if hard_fail else ("ok" if checks["retriever"] == "ok" else "degraded")
    return JSONResponse({"status": status, "checks": checks}, status_code=503 if hard_fail else 200)


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


_static = Path(__file__).resolve().parent.parent / "static"
app.mount("/ui", StaticFiles(directory=_static, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")
