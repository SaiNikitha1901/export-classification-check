"""Circuit breaker per LLM provider, with its state in Redis so every worker replica shares it.

closed    -> calls go through; failures are counted in a fixed window.
open      -> after `threshold` failures inside `window_s`: calls are refused for `open_s` seconds.
half-open -> after `open_s`: exactly one replica gets a probe call (SET NX). Success closes, failure re-opens.
"""
from __future__ import annotations

import logging
import time

from agent_worker.metrics import breaker_state

log = logging.getLogger("agent_worker.breaker")
STATE_VALUE = {"closed": 0, "open": 1, "half_open": 2}


class CircuitBreaker:
    def __init__(self, redis, provider: str, threshold: int, window_s: int, open_s: int, probe_ttl_s: int = 30):
        self.r, self.provider = redis, provider
        self.threshold, self.window_s, self.open_s, self.probe_ttl_s = threshold, window_s, open_s, probe_ttl_s
        base = f"ecs:cb:{provider}"
        self.k_fails, self.k_open, self.k_probe = f"{base}:fails", f"{base}:open_until", f"{base}:probe"

    def state(self) -> str:
        open_until = float(self.r.get(self.k_open) or 0)
        s = "closed" if not open_until else ("open" if time.time() < open_until else "half_open")
        breaker_state.labels(provider=self.provider).set(STATE_VALUE[s])
        return s

    def allow(self) -> bool:
        s = self.state()
        if s == "closed":
            return True
        if s == "open":
            return False
        return bool(self.r.set(self.k_probe, "1", nx=True, ex=self.probe_ttl_s))  # one probe across replicas

    def record_success(self) -> None:
        if self.r.delete(self.k_open):
            log.info("circuit closed", extra={"event": "breaker_closed", "provider": self.provider})
        self.r.delete(self.k_fails, self.k_probe)
        breaker_state.labels(provider=self.provider).set(0)

    def record_failure(self) -> None:
        if self.state() == "half_open":
            return self._trip("probe failed")
        n = self.r.incr(self.k_fails)
        if n == 1:
            self.r.expire(self.k_fails, self.window_s)
        if n >= self.threshold:
            self._trip(f"{n} failures in {self.window_s}s")

    def _trip(self, why: str) -> None:
        self.r.set(self.k_open, time.time() + self.open_s)
        self.r.delete(self.k_fails, self.k_probe)
        breaker_state.labels(provider=self.provider).set(1)
        log.warning("circuit opened: %s", why, extra={"event": "breaker_opened", "provider": self.provider})
