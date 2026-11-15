"""One client over any OpenAI-compatible chat endpoint (A5, L5, D4).

Path for every call: primary provider -> fallback provider (if configured) -> LLMUnavailable,
which the graph turns into a degraded, retrieval-only result. Per provider:
timeout on every request, bounded retry with exponential backoff + jitter (timeouts, 5xx,
connection errors only), and a Redis-shared circuit breaker.

Rate limits (429) are not outages: free tiers (e.g. 8k tokens/minute) answer 429 with a Retry-After
hint. A short hint (<= LLM_RATE_LIMIT_MAX_WAIT_S) is honoured by waiting, within the run's wall-clock
budget, and does not count against the breaker. A long hint (daily quota spent) counts as a failure
and moves on to the fallback provider.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from agent_worker.config import Provider, Settings
from agent_worker.llm.breaker import CircuitBreaker
from agent_worker.metrics import llm_cost, llm_retries, llm_tokens

log = logging.getLogger("agent_worker.llm")
CHAOS_KEY = "ecs:chaos:llm_fail"   # redis-cli SET ecs:chaos:llm_fail all  -> every provider "fails" (demo #8)


class LLMUnavailable(Exception):
    """Every provider failed or has its breaker open."""


class _Retryable(Exception):
    pass


class _RateLimited(_Retryable):
    def __init__(self, retry_after: float):
        super().__init__(f"HTTP 429 (retry after {retry_after:.1f}s)")
        self.retry_after = retry_after


def _retry_after(resp: httpx.Response) -> float:
    """Seconds the provider asks us to wait: Retry-After header, else 'try again in 8.4s' in the body."""
    try:
        return max(0.0, float(resp.headers.get("retry-after", "")))
    except ValueError:
        pass
    m = re.search(r"try again in ([\d.]+)\s*(ms|s)", resp.text or "")
    if m:
        return float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
    return 5.0


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    provider: str
    latency_ms: int
    attempts: int
    errors: list[str] = field(default_factory=list)


class LLMClient:
    def __init__(self, settings: Settings, redis, http: Optional[httpx.Client] = None, sleep=time.sleep):
        self.s, self.r = settings, redis
        self.http = http or httpx.Client()
        self.sleep = sleep
        self.breakers = {p.name: CircuitBreaker(redis, p.name, settings.cb_threshold, settings.cb_window_s,
                                                settings.cb_open_s, probe_ttl_s=int(settings.llm_timeout_s) + 10)
                         for p in settings.providers}

    def chat(self, messages: list[dict], *, agent: str, step: str, run_id: str | None = None,
             tools: list[dict] | None = None, json_mode: bool = False,
             deadline: float | None = None) -> LLMResponse:
        errors: list[str] = []
        for prov in self.s.providers:
            breaker = self.breakers[prov.name]
            if not breaker.allow():
                errors.append(f"{prov.name}: circuit open")
                continue
            attempt = rate_waits = 0
            while True:
                timeout = self.s.llm_timeout_s
                if deadline is not None:
                    timeout = min(timeout, deadline - time.monotonic())
                    if timeout < 1:
                        errors.append(f"{prov.name}: run wall-clock budget spent")
                        raise LLMUnavailable("; ".join(errors))
                start = time.perf_counter()
                try:
                    data = self._post(prov, messages, tools, json_mode, timeout)
                except _RateLimited as exc:
                    errors.append(f"{prov.name}: {exc}")
                    wait = exc.retry_after + random.uniform(0.2, 1.0)
                    too_long = exc.retry_after > self.s.rate_limit_max_wait_s
                    over_budget = deadline is not None and time.monotonic() + wait >= deadline
                    if too_long or rate_waits >= self.s.rate_limit_max_waits:
                        breaker.record_failure()   # quota spent, not a blip: try the fallback provider
                        break
                    if over_budget:
                        errors.append(f"{prov.name}: run wall-clock budget spent waiting for rate limit")
                        raise LLMUnavailable("; ".join(errors))
                    rate_waits += 1
                    llm_retries.labels(agent=agent).inc()
                    log.info("rate limited, waiting %.1fs", wait, extra={"event": "llm_rate_limited",
                                                                        "provider": prov.name, "llm_step": step})
                    self.sleep(wait)
                    continue
                except _Retryable as exc:
                    breaker.record_failure()
                    errors.append(f"{prov.name} attempt {attempt + 1}: {exc}")
                    log.warning("llm call failed: %s", exc, extra={"event": "llm_error", "provider": prov.name,
                                                                   "attempt": attempt + 1, "llm_step": step})
                    if attempt >= self.s.llm_max_retries or breaker.state() != "closed":
                        break
                    backoff = min(8.0, 0.5 * 2 ** attempt) * random.uniform(0.5, 1.5)
                    if deadline is not None and time.monotonic() + backoff >= deadline:
                        break
                    attempt += 1
                    llm_retries.labels(agent=agent).inc()
                    self.sleep(backoff)
                    continue
                except httpx.HTTPStatusError as exc:   # 4xx other than 429: our request is wrong, not the provider
                    errors.append(f"{prov.name}: HTTP {exc.response.status_code} {exc.response.text[:200]}")
                    break
                breaker.record_success()
                return self._response(data, prov, agent, start, attempt + rate_waits + 1, errors,
                                      len(json.dumps(messages)))
        raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")

    def _post(self, prov: Provider, messages, tools, json_mode, timeout) -> dict:
        if self._chaos(prov):
            raise _Retryable("forced failure (LLM_FORCE_FAIL / ecs:chaos:llm_fail)")
        body: dict[str, Any] = {"model": prov.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self.http.post(f"{prov.base_url.rstrip('/')}/chat/completions", json=body, timeout=timeout,
                                  headers={"Authorization": f"Bearer {prov.api_key}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retryable(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code == 429:
            raise _RateLimited(_retry_after(resp))
        if resp.status_code >= 500:
            raise _Retryable(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise _Retryable("invalid JSON from provider") from exc

    def _chaos(self, prov: Provider) -> bool:
        flag = self.s.force_fail
        if not flag:
            try:
                flag = (self.r.get(CHAOS_KEY) or b"").decode().lower()
            except Exception:  # noqa: BLE001 - chaos switch must never break a real call
                flag = ""
        return flag in ("1", "all", prov.name)

    def _response(self, data: dict, prov: Provider, agent: str, start: float, attempts: int,
                  errors: list[str], prompt_chars: int) -> LLMResponse:
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        usage = data.get("usage") or {}
        # Providers that omit usage: estimate ~4 chars per token so cost is never silently zero.
        pt = int(usage.get("prompt_tokens") or 0) or prompt_chars // 4
        ct = int(usage.get("completion_tokens") or 0) or (len(content) + len(json.dumps(tool_calls))) // 4
        cost = pt / 1000 * self.s.price_in_per_1k + ct / 1000 * self.s.price_out_per_1k
        llm_tokens.labels(agent=agent, kind="prompt").inc(pt)
        llm_tokens.labels(agent=agent, kind="completion").inc(ct)
        llm_cost.labels(agent=agent).inc(cost)
        return LLMResponse(content, tool_calls, pt, ct, round(cost, 8), prov.name,
                           int((time.perf_counter() - start) * 1000), attempts, errors)
