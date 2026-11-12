"""Retrieval service (Member 2). Implements the shared retriever contract A.7.

POST /search                        hybrid | keyword | dense search with kind/chapter filters (cached in Redis)
GET  /clause/{clause_id}            passages of one clause ("GRI-3" also returns GRI-3(a)…(c))
GET  /notes/applicable/{clause_id}  section + chapter notes that apply to a heading / tariff item (by metadata)
GET  /policy/{hs_code}              DGFT export policy: Schedule 2 row (8 -> 6 -> 4 digits) or General Note 1
GET  /index/info                    data freshness: built_at, sources + sha256, chunk_count, embed_model
GET  /health, /metrics
Every endpoint reads and echoes X-Correlation-ID (A.9).
"""
from __future__ import annotations

import logging
import time
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from ecs_common import CORRELATION_HEADER, bind, new_correlation_id, setup_logging
from retriever import config, metrics
from retriever.cache import Cache
from retriever.index import Index

settings = config.load()
setup_logging(settings.service_name, settings.log_level)
log = logging.getLogger("retriever")
tracer = trace.get_tracer("retriever")

app = FastAPI(title="Export Classification Check - retriever", version="1.0")
index = Index(settings, Cache(settings.redis_url, settings.cache_ttl_s))

Kind = Literal["gri", "section_note", "chapter_note", "heading", "tariff_line", "export_policy"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=8, ge=1, le=50)
    kinds: Optional[list[Kind]] = None
    chapters: Optional[list[Literal["73", "96"]]] = None
    mode: Literal["dense", "keyword", "hybrid"] = "hybrid"


def _setup_tracing() -> None:
    if not settings.otel_endpoint:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled")
        return
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    RedisInstrumentor().instrument()


_setup_tracing()


@app.on_event("startup")
def _load_index() -> None:
    try:
        index.ensure_loaded()
    except Exception:
        log.exception("index load failed", extra={"event": "index_load_failed"})


@app.middleware("http")
async def correlation_and_metrics(request: Request, call_next):
    cid = request.headers.get(CORRELATION_HEADER) or new_correlation_id()
    run_id = request.headers.get("X-Run-ID")
    start = time.perf_counter()
    with bind(correlation_id=cid, run_id=run_id):
        span = trace.get_current_span()
        span.set_attribute("correlation_id", cid)
        if run_id:
            span.set_attribute("run_id", run_id)
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
            log.info("%s %s -> %s", request.method, route, response.status_code,
                     extra={"event": "http_request", "latency_ms": round(elapsed * 1000, 1)})
    response.headers[CORRELATION_HEADER] = cid
    return response


def _require_index():
    try:
        d = index.ensure_loaded()
    except Exception as e:
        log.exception("index load failed", extra={"event": "index_load_failed"})
        raise HTTPException(503, f"index not available: {e}")
    if d is None:
        raise HTTPException(503, "index not built yet; run `python -m retriever.ingest build`")
    return d


@app.get("/health")
def health():
    d = None
    try:
        d = index.ensure_loaded()
    except Exception:
        pass
    if d is None:
        return JSONResponse({"status": "starting", "index_loaded": False}, status_code=503)
    return {"status": "ok", "index_loaded": True, "chunks": len(d.chunks), "built_at": d.manifest.get("built_at")}


@app.get("/metrics")
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/index/info")
def index_info():
    return index.info()


@app.post("/search")
def search(body: SearchRequest):
    _require_index()
    with tracer.start_as_current_span("retriever.search") as span:
        span.set_attribute("retrieval.mode", body.mode)
        span.set_attribute("retrieval.k", body.k)
        span.set_attribute("retrieval.query", body.query[:200])
        passages, hit = index.search(body.query, body.k, body.kinds, body.chapters, body.mode)
        span.set_attribute("retrieval.cache_hit", hit)
        span.set_attribute("retrieval.clause_ids", ",".join(p["clause_id"] for p in passages))
    log.info("search", extra={"event": "search", "mode": body.mode, "k": body.k, "cache_hit": hit,
                              "query": body.query[:200], "clause_ids": [p["clause_id"] for p in passages]})
    return {"query": body.query, "mode": body.mode, "passages": passages, "cache_hit": hit}


@app.get("/clause/{clause_id}")
def clause(clause_id: str):
    _require_index()
    passages = index.clause(clause_id)
    if not passages:
        raise HTTPException(404, f"clause {clause_id} not found in the corpus")
    return {"clause_id": clause_id.upper(), "passages": passages}


@app.get("/notes/applicable/{clause_id}")
def notes_applicable(clause_id: str):
    _require_index()
    out = index.applicable_notes(clause_id)
    if out is None:
        raise HTTPException(404, f"{clause_id} is not a heading or tariff item of Chapters 73/96 in the corpus")
    return out


@app.get("/policy/{hs_code}")
def policy(hs_code: str):
    _require_index()
    out = index.policy(hs_code)
    if out is None:
        raise HTTPException(404, f"{hs_code}: expected a 4, 6 or 8 digit code in Chapter 73 or 96")
    return out
