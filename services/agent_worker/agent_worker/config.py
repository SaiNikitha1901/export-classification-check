"""All worker settings come from the environment (D4). Read per run, so tests can change env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class Provider:
    name: str          # "primary" | "fallback" (metric label; never a model id)
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Settings:
    providers: list[Provider] = field(default_factory=list)
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 3
    price_in_per_1k: float = 0.0
    price_out_per_1k: float = 0.0
    max_steps: int = 12
    max_tool_calls: int = 10
    max_wall_s: float = 90.0
    prompt_version: str = "classifier@v1"
    retriever_url: str = ""
    redis_url: str = ""
    postgres_dsn: str = ""
    cb_threshold: int = 5
    cb_window_s: int = 60
    cb_open_s: int = 30
    toxicity_threshold: float = 0.7
    force_fail: str = ""   # demo switch: "", "primary", "fallback" or "all"
    rate_limit_max_wait_s: float = 60.0   # honour a 429 Retry-After up to this long; longer = quota spent
    rate_limit_max_waits: int = 30        # per call, so a stuck provider cannot loop forever
    classifier_max_turns: int = 10


def load() -> Settings:
    providers = [Provider("primary", _env("LLM_BASE_URL"), _env("LLM_API_KEY"), _env("LLM_MODEL"))]
    if _env("LLM_FALLBACK_BASE_URL") and _env("LLM_FALLBACK_MODEL"):
        providers.append(Provider("fallback", _env("LLM_FALLBACK_BASE_URL"), _env("LLM_FALLBACK_API_KEY"),
                                  _env("LLM_FALLBACK_MODEL")))
    return Settings(
        providers=providers,
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "20")),
        llm_max_retries=int(_env("LLM_MAX_RETRIES", "3")),
        price_in_per_1k=float(_env("LLM_PRICE_IN_PER_1K", "0")),
        price_out_per_1k=float(_env("LLM_PRICE_OUT_PER_1K", "0")),
        max_steps=int(_env("AGENT_MAX_STEPS", "12")),
        max_tool_calls=int(_env("AGENT_MAX_TOOL_CALLS", "10")),
        max_wall_s=float(_env("AGENT_MAX_WALL_S", "90")),
        prompt_version=_env("PROMPT_VERSION", "classifier@v1"),
        retriever_url=_env("RETRIEVER_URL", "http://retriever:8001").rstrip("/"),
        redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
        postgres_dsn=_env("POSTGRES_DSN"),
        cb_threshold=int(_env("CB_FAILURE_THRESHOLD", "5")),
        cb_window_s=int(_env("CB_WINDOW_S", "60")),
        cb_open_s=int(_env("CB_OPEN_S", "30")),
        toxicity_threshold=float(_env("TOXICITY_THRESHOLD", "0.7")),
        force_fail=_env("LLM_FORCE_FAIL").lower(),
        rate_limit_max_wait_s=float(_env("LLM_RATE_LIMIT_MAX_WAIT_S", "60")),
        rate_limit_max_waits=int(_env("LLM_RATE_LIMIT_MAX_WAITS", "30")),
        classifier_max_turns=int(_env("CLASSIFIER_MAX_TURNS", "10")),
    )
