"""PLACEHOLDER retriever (Member 1 skeleton; Member 2 owns this folder and replaces it).

Implements the A.7 endpoint shapes with an empty index so the rest of the system can start.
built_at is null, which tells the API's run cache to stay off until a real index exists.
"""
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

app = FastAPI(title="retriever (placeholder)")


@app.get("/health")
def health():
    return {"status": "ok", "placeholder": True}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/index/info")
def index_info():
    return {"built_at": None, "sources": [], "chunk_count": 0, "embed_model": None, "placeholder": True}


@app.post("/search")
def search(body: dict):
    return {"query": body.get("query"), "mode": body.get("mode", "hybrid"), "passages": [], "cache_hit": False}


@app.get("/clause/{clause_id}")
def clause(clause_id: str):
    raise HTTPException(404, f"{clause_id} not found (placeholder index is empty)")
