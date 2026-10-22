"""PLACEHOLDER OpenAI-compatible stub (Member 1 skeleton; Member 3 owns this folder and replaces it
with fixed responses the agents can parse). Sleeps a realistic delay so load tests measure our system."""
import asyncio
import os
import random
import time
import uuid

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.responses import Response

app = FastAPI(title="llm-stub (placeholder)")
calls = Counter("ecs_llm_stub_calls_total", "Stub completions served")
DELAY_MIN = float(os.environ.get("STUB_DELAY_MIN_S", "1.5"))
DELAY_MAX = float(os.environ.get("STUB_DELAY_MAX_S", "4.0"))


@app.get("/health")
def health():
    return {"status": "ok", "placeholder": True}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
async def chat(body: dict):
    await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    calls.inc()
    return {
        "id": f"stub-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "stub"),
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "{\"placeholder\": true}"}}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 120, "total_tokens": 920},
    }
