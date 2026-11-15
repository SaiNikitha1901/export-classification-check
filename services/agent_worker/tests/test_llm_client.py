"""LLM client: retry/backoff, circuit breaker (shared via Redis), fallback, cost, chaos switch."""
import fakeredis
import httpx
import pytest

from agent_worker import config
from agent_worker.llm import CHAOS_KEY, LLMClient, LLMUnavailable

OK = {"choices": [{"message": {"role": "assistant", "content": "{}"}}],
      "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}}
MSG = [{"role": "user", "content": "hi"}]


def client(handler, redis=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return LLMClient(config.load(), redis or fakeredis.FakeRedis(),
                     http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)


def seq(*codes):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        code = codes[min(len(calls) - 1, len(codes) - 1)]
        return httpx.Response(code, json=OK if code == 200 else {"error": "x"})
    handler.calls = calls
    return handler


def test_retries_with_backoff_then_succeeds_and_prices_tokens():
    h, sleeps = seq(503, 429, 200), []
    r = client(h, sleeps=sleeps).chat(MSG, agent="t", step="s")
    assert r.attempts == 3 and len(h.calls) == 3 and len(sleeps) == 2
    assert sleeps[1] > sleeps[0] * 0.3                       # exponential with jitter
    assert r.cost_usd == pytest.approx(0.00059 + 0.00079)    # 1k in + 1k out at the env prices


def test_client_error_is_not_retried():
    h = seq(400)
    with pytest.raises(LLMUnavailable):
        client(h).chat(MSG, agent="t", step="s")
    assert len(h.calls) == 1


def test_timeout_is_retryable():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=OK)
    assert client(handler).chat(MSG, agent="t", step="s").attempts == 2


def test_breaker_opens_is_shared_and_short_circuits():
    redis = fakeredis.FakeRedis()
    h = seq(503)
    with pytest.raises(LLMUnavailable):
        client(h, redis).chat(MSG, agent="t", step="s")      # 3 failures = threshold (CB_FAILURE_THRESHOLD=3)
    other_replica = client(h, redis)                          # new client, same Redis
    assert other_replica.breakers["primary"].state() == "open"
    n = len(h.calls)
    with pytest.raises(LLMUnavailable, match="circuit open"):
        other_replica.chat(MSG, agent="t", step="s")
    assert len(h.calls) == n                                  # no request sent while open


def test_half_open_probe_closes_on_success(monkeypatch):
    redis = fakeredis.FakeRedis()
    c = client(seq(200), redis)
    br = c.breakers["primary"]
    for _ in range(3):
        br.record_failure()
    assert br.state() == "open"
    redis.set(br.k_open, 1)                                   # pretend open_s has passed
    assert br.state() == "half_open"
    c.chat(MSG, agent="t", step="s")
    assert br.state() == "closed"


def test_fallback_provider_used_when_primary_fails(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://fallback.test/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "fb-model")

    def handler(request):
        return httpx.Response(503) if "llm.test" in str(request.url) else httpx.Response(200, json=OK)
    r = client(handler).chat(MSG, agent="t", step="s")
    assert r.provider == "fallback" and r.errors


def test_chaos_switch_in_redis_forces_failure():
    redis = fakeredis.FakeRedis()
    redis.set(CHAOS_KEY, "all")
    h = seq(200)
    with pytest.raises(LLMUnavailable, match="forced failure"):
        client(h, redis).chat(MSG, agent="t", step="s")
    assert h.calls == []


def test_missing_usage_is_estimated():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "x" * 400}}]})
    r = client(handler).chat(MSG, agent="t", step="s")
    assert r.completion_tokens == 100 and r.prompt_tokens > 0


def _rate_limited_then_ok(n_429, retry_after):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) <= n_429:
            return httpx.Response(429, headers={"retry-after": str(retry_after)}, json={"error": "rate limit"})
        return httpx.Response(200, json=OK)
    handler.calls = calls
    return handler


def test_rate_limit_waits_retry_after_and_does_not_open_breaker():
    redis, sleeps = fakeredis.FakeRedis(), []
    h = _rate_limited_then_ok(8, 7)                     # more 429s than the breaker threshold (5)
    r = client(h, redis=redis, sleeps=sleeps).chat(MSG, agent="t", step="s")
    assert r.provider == "primary" and len(h.calls) == 9
    assert len(sleeps) == 8 and all(s >= 7 for s in sleeps)   # waited what the provider asked
    assert not redis.get("ecs:cb:primary:open_until")        # a rate limit is not an outage


def test_rate_limit_hint_in_body_is_used():
    sleeps = []

    def handler(request, calls=[]):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "Please try again in 8.44s."}})
        return httpx.Response(200, json=OK)
    client(handler, sleeps=sleeps).chat(MSG, agent="t", step="s")
    assert 8.44 <= sleeps[0] <= 9.5


def test_long_retry_after_counts_as_failure(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
    redis = fakeredis.FakeRedis()
    with pytest.raises(LLMUnavailable, match="429"):
        client(_rate_limited_then_ok(99, 3600), redis=redis).chat(MSG, agent="t", step="s")
    assert int(redis.get("ecs:cb:primary:fails") or 0) == 1   # daily quota spent: counted, then fallback
