"""All configuration comes from the environment (D4). Missing required values fail at startup."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _req(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable {name} (see .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    service: str
    postgres_dsn: str
    redis_url: str
    retriever_url: str
    rate_limit_per_min: int
    run_cache_ttl_s: int
    run_timeout_s: int
    prompt_version: str
    log_level: str
    otel_endpoint: str | None
    queue_name: str = "runs"
    job_func: str = "agent_worker.tasks.run_classification"


def load() -> Settings:
    return Settings(
        service=os.environ.get("SERVICE_NAME", "api"),
        postgres_dsn=_req("POSTGRES_DSN"),
        redis_url=_req("REDIS_URL"),
        retriever_url=_req("RETRIEVER_URL").rstrip("/"),
        rate_limit_per_min=int(_req("RATE_LIMIT_PER_MIN")),
        run_cache_ttl_s=int(_req("RUN_CACHE_TTL_S")),
        run_timeout_s=int(_req("RUN_TIMEOUT_S")),
        prompt_version=_req("PROMPT_VERSION"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        otel_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
    )


settings = load()
