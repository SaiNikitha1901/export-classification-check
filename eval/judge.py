"""The evaluation judge (L3). Two methods, chosen by EVAL_JUDGE:

  llm      the same env-configured OpenAI-compatible LLM as the agents (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL),
           prompt eval/judge_prompts/v1.json (judge@v1), temperature 0, answers cached in Redis.
  lexical  deterministic token overlap (no model). Used when the LLM is the load-test stub, which cannot judge.
  auto     (default) llm, unless LLM_BASE_URL points at the llm-stub service.

If an LLM answer cannot be parsed, that item falls back to lexical, and the method is reported as "llm+lexical".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

PROMPTS = json.loads((Path(__file__).with_name("judge_prompts") / "v1.json").read_text(encoding="utf-8"))
JUDGE_VERSION = PROMPTS["version"]
_STOP = set("a an and are as at be by for from has have in into is it its of on or other than that the their "
            "thereof these this to was were which with without whether not under heading headings tariff line "
            "item chapter chapters gri rule note notes".split())


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in _STOP or len(w) < 3:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


class Judge:
    def __init__(self, mode: Optional[str] = None) -> None:
        self.base = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
        self.key = os.getenv("LLM_API_KEY") or ""
        self.model = os.getenv("LLM_MODEL") or ""
        self.timeout = float(os.getenv("LLM_TIMEOUT_S", "20"))
        mode = (mode or os.getenv("EVAL_JUDGE") or "auto").lower()
        if mode == "auto":
            mode = "lexical" if (not self.base or "llm-stub" in self.base) else "llm"
        self.mode = mode
        self.redis = None
        if os.getenv("REDIS_URL"):
            try:
                import redis

                self.redis = redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=1)
            except Exception:
                self.redis = None
        self.calls = 0
        self.cache_hits = 0

    @property
    def label(self) -> str:
        return f"{JUDGE_VERSION}:{self.model}" if self.mode == "llm" else "lexical@v1"

    # ------------------------------------------------------------ public API

    def claims_supported(self, claims: list[str], passages: list[str]) -> tuple[list[bool], str]:
        if not passages:
            return [False] * len(claims), self.mode if self.mode == "lexical" else "llm"
        if self.mode == "llm":
            out = self._llm("groundedness", {"claims": _numbered(claims), "passages": _numbered(passages, 1500)},
                            "verdicts", len(claims))
            if out is not None:
                return [bool(v) for v in out], "llm"
            return self._lex_claims(claims, passages), "llm+lexical"
        return self._lex_claims(claims, passages), "lexical"

    def passage_relevance(self, query: str, passages: list[str]) -> tuple[list[float], str]:
        if self.mode == "llm":
            out = self._llm("context_relevance", {"query": query, "passages": _numbered(passages, 800)},
                            "scores", len(passages))
            if out is not None:
                return [min(1.0, max(0.0, float(v))) for v in out], "llm"
            return self._lex_relevance(query, passages), "llm+lexical"
        return self._lex_relevance(query, passages), "lexical"

    # ------------------------------------------------------------ lexical judge

    @staticmethod
    def _lex_claims(claims: list[str], passages: list[str]) -> list[bool]:
        """A claim is supported if >= 60% of its content words (and all its 4+ digit codes) occur in the passages."""
        ptoks = _tokens(" ".join(passages))
        ptxt = " ".join(passages).replace(" ", "")
        out = []
        for c in claims:
            # Codes are checked separately (spacing-insensitive), so they are not counted as words: the corpus
            # prints "9617 00 11", which would never match the word "96170011".
            ct = {t for t in _tokens(c) if not t.isdigit()}
            codes = re.findall(r"\d{4,8}", c)
            word_ok = not ct or len(ct & ptoks) / len(ct) >= 0.6
            codes_ok = all(code in ptxt for code in codes)
            out.append(word_ok and codes_ok)
        return out

    @staticmethod
    def _lex_relevance(query: str, passages: list[str]) -> list[float]:
        """1 if the passage shares >= 2 content words with the product, 0.5 if it shares 1, else 0."""
        q = _tokens(query)
        out = []
        for p in passages:
            n = len(q & _tokens(p))
            out.append(1.0 if n >= 2 else 0.5 if n == 1 else 0.0)
        return out

    # ------------------------------------------------------------ LLM judge

    def _llm(self, task: str, values: dict, key: str, n: int) -> Optional[list]:
        tpl = PROMPTS[task]
        messages = [{"role": "system", "content": tpl["system"]},
                    {"role": "user", "content": tpl["user"].format(**values)}]
        ck = "evaljudge:" + hashlib.sha256(json.dumps([JUDGE_VERSION, self.model, messages]).encode()).hexdigest()
        cached = self._cache_get(ck)
        if cached is not None:
            self.cache_hits += 1
            return cached
        import requests

        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 400}
        for attempt in range(3):
            try:
                self.calls += 1
                r = requests.post(f"{self.base}/chat/completions", json=body, timeout=self.timeout,
                                  headers={"Authorization": f"Bearer {self.key}"})
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(2 ** attempt * 2)
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"] or ""
                m = re.search(r"\{.*\}", content, re.S)
                vals = json.loads(m.group(0))[key] if m else None
                if isinstance(vals, list) and len(vals) == n:
                    self._cache_set(ck, vals)
                    return vals
                return None
            except Exception:
                time.sleep(2 ** attempt)
        return None

    def _cache_get(self, k: str):
        if not self.redis:
            return None
        try:
            raw = self.redis.get(k)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _cache_set(self, k: str, v) -> None:
        if self.redis:
            try:
                self.redis.set(k, json.dumps(v), ex=30 * 86400)
            except Exception:
                pass


def _numbered(items: list[str], max_chars: int = 400) -> str:
    return "\n".join(f"[{i + 1}] {t[:max_chars]}" for i, t in enumerate(items))
