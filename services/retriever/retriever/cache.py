"""Redis caches for query embeddings and search results (D7). Redis being down never fails a request."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from retriever import metrics

log = logging.getLogger("cache")


def digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


class Cache:
    def __init__(self, url: Optional[str], ttl_s: int) -> None:
        self.ttl = ttl_s
        self.client = None
        if url:
            try:
                import redis

                self.client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
            except Exception:  # pragma: no cover - import/config problem
                log.warning("redis unavailable; caching off", extra={"event": "cache_off"})

    def get(self, name: str, key: str) -> Optional[Any]:
        if not self.client:
            return None
        try:
            raw = self.client.get(f"ret:{name}:{key}")
        except Exception:
            metrics.cache_errors.labels(name).inc()
            return None
        if raw is None:
            metrics.cache_misses.labels(name).inc()
            return None
        metrics.cache_hits.labels(name).inc()
        return json.loads(raw)

    def set(self, name: str, key: str, value: Any) -> None:
        if not self.client:
            return
        try:
            self.client.set(f"ret:{name}:{key}", json.dumps(value, ensure_ascii=False), ex=self.ttl)
        except Exception:
            metrics.cache_errors.labels(name).inc()
