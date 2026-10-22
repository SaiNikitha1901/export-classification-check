"""Whole-run cache (D7).

A run is expensive (several LLM calls). The same product description is often re-checked,
so a completed result is reused when the normalised request, the prompt version and the
index build are all identical. Rebuilding the index or changing the prompt changes the key,
so stale answers are never served. Only 'completed' runs are cached, never degraded/failed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

import requests

from contracts import ProductRequest

log = logging.getLogger("runcache")

_index_cache: dict[str, float | str] = {"value": "unknown", "fetched": 0.0}


def index_version(retriever_url: str, max_age_s: float = 30.0) -> str:
    """The retriever's index build time; part of the cache key. 'unknown' disables caching."""
    if time.monotonic() - float(_index_cache["fetched"]) < max_age_s:
        return str(_index_cache["value"])
    value = "unknown"
    try:
        info = requests.get(f"{retriever_url}/index/info", timeout=2).json()
        value = str(info.get("built_at") or "unknown")
    except Exception as exc:
        log.warning("could not read retriever index info: %s", exc)
    _index_cache.update(value=value, fetched=time.monotonic())
    return value


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def cache_key(req: ProductRequest, prompt_version: str, index_built_at: str) -> str | None:
    if index_built_at == "unknown":
        return None
    material_set = sorted((_norm(m.name), round(m.share_pct, 1)) for m in req.materials or [])
    basis = {
        "d": _norm(req.product_description),
        "m": material_set,
        "u": _norm(req.intended_use),
        "c": req.destination_country,
        "h": req.declared_hs_code,
        "p": prompt_version,
        "i": index_built_at,
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    return f"runcache:{digest}"


def get(redis_conn, key: str) -> dict | None:
    raw = redis_conn.get(key)
    return json.loads(raw) if raw else None


def put(redis_conn, key: str, result: dict, ttl_s: int) -> None:
    redis_conn.set(key, json.dumps(result), ex=ttl_s, nx=True)
