"""Runtime configuration. Everything comes from env vars (D4); defaults are documented in .env.example."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    service_name: str
    log_level: str
    embed_model: str
    index_dir: Path
    corpus_dir: Path
    redis_url: str | None
    cache_ttl_s: int
    otel_endpoint: str | None
    chunking: str  # "structure" (default) or "fixed" (baseline for the L3 before/after)

    @property
    def chunks_path(self) -> Path:
        return self.index_dir / "chunks.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.index_dir / "manifest.json"

    @property
    def active_path(self) -> Path:
        return self.index_dir / "active.json"

    @property
    def chroma_dir(self) -> Path:
        return self.index_dir / "chroma"


def load() -> Settings:
    return Settings(
        service_name=os.getenv("SERVICE_NAME", "retriever"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        embed_model=os.environ.get("EMBED_MODEL", ""),
        index_dir=Path(os.getenv("INDEX_DIR", "/data/index")),
        corpus_dir=Path(os.getenv("CORPUS_DIR", "/srv/corpus")),
        redis_url=os.getenv("REDIS_URL") or None,
        cache_ttl_s=int(os.getenv("RETRIEVAL_CACHE_TTL_S", "3600")),
        otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        chunking=os.getenv("CHUNKING", "structure"),
    )
