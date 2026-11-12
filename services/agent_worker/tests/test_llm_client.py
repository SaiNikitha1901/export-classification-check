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
