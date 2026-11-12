"""OpenAI-compatible LLM stub for load tests (D6). Owner: Member 3.

POST /v1/chat/completions returns responses the agents can parse, after a realistic delay
(uniform STUB_DELAY_MIN_S..STUB_DELAY_MAX_S), with `usage` token counts proportional to the context.
It picks the behaviour from the "ROLE: <agent>" line of the system prompt:
  extractor  -> JSON facts (article, materials, ...) from the description
  classifier -> a scripted analyst: hybrid search -> notes -> keyword search for the article -> GRI-1/GRI-6
                -> submit_classification, quoting text from the passages the tools actually returned
  verifier   -> {"supported": true}
Deterministic apart from the delay, and works against the real retriever as well as the fake one.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import uuid

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

app = FastAPI(title="llm-stub")
calls = Counter("ecs_llm_stub_calls_total", "Stub completions served", ["role"])
delay_h = Histogram("ecs_llm_stub_delay_seconds", "Injected delay", buckets=(0.5, 1, 1.5, 2, 3, 4, 6))
DELAY_MIN = float(os.environ.get("STUB_DELAY_MIN_S", "1.5"))
DELAY_MAX = float(os.environ.get("STUB_DELAY_MAX_S", "4.0"))

MATERIALS = ["stainless steel", "cast iron", "steel", "iron", "plastics", "plastic", "aluminium", "aluminum", "glass",
             "wood", "copper", "zinc", "brass", "rubber", "leather", "paper", "ceramic", "bamboo"]
_NOISE = {"with", "and", "the", "for", "made", "moulded", "molded", "outer", "inner", "body", "small", "large",
          "packed", "boxes", "set", "pcs", "single", "double", "refillable", "plated", "for", "of"}


def _stem(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 4 and w.endswith("s") else w


def _words(s: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[A-Za-z]+", s or "") if len(w) > 2}


def _description(text: str) -> str:
    m = re.search(r"product_description:\s*(.+)", text or "")
    return m.group(1).strip() if m else (text or "")[:300]


# ------------------------------------------------------------------ extractor
def extractor(messages: list[dict]) -> dict:
    desc = _description(messages[-1]["content"])
    low = desc.lower()
    mats, rest = [], low
    for m in MATERIALS:
        if re.search(rf"\b{m}\b", rest):
            mats.append(m)
            rest = re.sub(rf"\b{m}\b", " ", rest)
    head = re.split(r"\b(with|for|of|in|packed|,|\()", rest)[0]
    words = [w for w in re.findall(r"[a-z]+", head) if w not in _NOISE and not w.endswith("-plated")]
    article = " ".join(words[-2:]) or desc[:40]
    return {"article": article, "function": "", "materials": [{"name": m, "share_pct": None} for m in mats],
            "form": "complete article", "missing_facts": [] if mats else ["material"]}


# ------------------------------------------------------------------ classifier
def _tool_history(messages: list[dict]):
    made, passages = [], {}
    for m in messages:
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or []:
                made.append((c["function"]["name"], json.loads(c["function"]["arguments"] or "{}")))
        elif m.get("role") == "tool":
            try:
                data = json.loads(m.get("content") or "null")
            except ValueError:
                continue
            for p in data if isinstance(data, list) else []:
                passages.setdefault(p["passage_id"], p)
    return made, list(passages.values())


def _heading(p: dict) -> str:
    d = re.sub(r"\D", "", p.get("clause_id") or "")
    return d[:4] if (p.get("clause_id") or "").startswith(("HDG-", "TL-")) else ""


def _quote(text: str, around: str | None = None, n: int = 110) -> str:
    text = text or ""
    i = text.find(around) if around else -1
    if i < 0:
        return text[:n]
    start = max(0, i - 60)
    return text[start:i + len(around) + 40]


def _cite(p: dict, around: str | None = None) -> dict:
    return {"clause_id": p["clause_id"], "passage_id": p["passage_id"], "quote": _quote(p.get("text"), around)}


def _capacity_litres(desc: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|millilit\w*|l|lit\w*)\b", desc.lower())
    if not m:
        return None
    v = float(m.group(1))
    return v / 1000 if m.group(2).startswith("m") else v


def classifier(messages: list[dict]) -> tuple[str, list[dict]]:
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    desc = _description(user)
    try:
        facts = json.loads(re.search(r"\(JSON\):\s*(\{.*?\})\s*\n", user, re.S).group(1))
    except (AttributeError, ValueError):
        facts = {}
    article = facts.get("article") or desc
    made, passages = _tool_history(messages)
    names = [n for n, _ in made]
    by_clause = {p["clause_id"]: p for p in passages}

    def call(name, **args):
        return "", [{"id": f"call_{uuid.uuid4().hex[:10]}", "type": "function",
                     "function": {"name": name, "arguments": json.dumps(args)}}]

    if "search_corpus" not in names:
        return call("search_corpus", query=desc, kinds=["heading", "tariff_line"], mode="hybrid")
    first = next((_heading(p) for p in passages if _heading(p)), "")
    if "get_applicable_notes" not in names and first:
        return call("get_applicable_notes", clause_id=f"HDG-{first}")
    if not any(n == "search_corpus" and a.get("mode") == "keyword" for n, a in made):
        return call("search_corpus", query=article, kinds=["heading", "tariff_line"], mode="keyword")

    terms = _words(article) - _words(" ".join(MATERIALS)) - _NOISE
    scored = [(len(terms & _words(p.get("text", ""))), p) for p in passages if _heading(p)]
    scored = [x for x in scored if x[0] > 0]
    if not scored:
        return submit(article=article, out_of_scope=True,
                      reasoning=f"No heading in Chapters 73 or 96 names or describes '{article}'.")
    h = max(scored, key=lambda x: x[0])[1]
    h = _heading(h)
    if "GRI-1" not in by_clause:
        return call("get_clause", clause_id="GRI-1")
    if f"HDG-{h}" not in by_clause:
        return call("get_clause", clause_id=f"HDG-{h}")
    if h[:2] != first[:2] and "get_applicable_notes" in names and not any(
            a.get("clause_id") == f"HDG-{h}" for n, a in made if n == "get_applicable_notes"):
        return call("get_applicable_notes", clause_id=f"HDG-{h}")

    lines = [p for p in passages if (p.get("clause_id") or "").startswith(f"TL-{h}")]
    dwords = _words(desc) | terms
    ranked = sorted(lines, key=lambda p: -len(dwords & _words(p.get("text", ""))))
    code, missing = "", []
    cap = _capacity_litres(desc)
    cap_lines = [p for p in ranked if "capacity" in p.get("text", "")]
    if cap_lines and cap is not None:
        want = "not exceeding" if cap <= 0.75 else "exceeding"
        pick = next((p for p in cap_lines if (want == "not exceeding") == ("not exceeding" in p["text"])), None)
        code = pick["clause_id"][3:] if pick else ""
    elif cap_lines:
        missing = ["capacity in litres (the tariff lines under this heading are split by capacity)"]
    elif ranked:
        code = ranked[0]["clause_id"][3:]
    if code and "GRI-6" not in by_clause:
        return call("get_clause", clause_id="GRI-6")

    cites = [_cite(by_clause["GRI-1"]), _cite(by_clause[f"HDG-{h}"])]
    note = next((p for p in passages if p.get("kind") in ("section_note", "chapter_note")
                 and f"Chapter {h[:2]}" in (p.get("text") or "")), None)
    if note:
        cites.append(_cite(note, f"Chapter {h[:2]}"))
    gri = ["GRI-1"]
    if code:
        gri.append("GRI-6")
        cites += [_cite(by_clause["GRI-6"]), _cite(by_clause[f"TL-{code}"])]
    return submit(article=article, heading=h, code=code, gri=gri, citations=cites, missing=missing,
                  reasoning=f"The description first matches material-based headings, but heading {h} names the "
                            f"article itself. Under GRI 1 the terms of the headings and the notes decide"
                            + (f"; the cited note excludes the article from the material chapter" if note else "")
                            + (f". GRI 6 selects tariff line {code}." if code else ". The tariff line needs: "
                               + ", ".join(missing) + "." if missing else "."))


def submit(article, heading="", code="", gri=(), citations=(), missing=(), out_of_scope=False, reasoning=""):
    args = {"article": article, "heading": heading, "proposed_hs_code": code, "gri_applied": list(gri),
            "decided_by": "GRI-1" if heading else "", "reasoning_summary": reasoning, "citations": list(citations),
            "out_of_scope": out_of_scope, "competing_headings": [], "missing_facts": list(missing)}
    return "", [{"id": f"call_{uuid.uuid4().hex[:10]}", "type": "function",
                 "function": {"name": "submit_classification", "arguments": json.dumps(args)}}]


# ------------------------------------------------------------------ HTTP
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
async def chat(body: dict):
    messages = body.get("messages") or []
    system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
    role = (re.search(r"ROLE:\s*(\w+)", system) or [None, "unknown"])[1]
    content, tool_calls = "{}", []
    if role == "extractor":
        content = json.dumps(extractor(messages))
    elif role == "classifier":
        content, tool_calls = classifier(messages)
    elif role == "verifier":
        content = json.dumps({"supported": True, "unsupported_claims": []})
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    delay_h.observe(delay)
    await asyncio.sleep(delay)
    calls.labels(role=role).inc()
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    pt = len(json.dumps(messages)) // 4
    ct = (len(content) + len(json.dumps(tool_calls))) // 4
    return {"id": f"stub-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "stub"),
            "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": message}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}}
