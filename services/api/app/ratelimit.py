"""Per-client sliding-window rate limit in Redis (D7).

Cost control: one client looping against a multi-step agent can burn the LLM budget in
minutes, so every client gets RATE_LIMIT_PER_MIN run submissions per rolling minute.
"""
from __future__ import annotations

import math
import time
import uuid

WINDOW_MS = 60_000


def check(redis_conn, client_id: str, limit: int) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds). Rejected attempts are not counted."""
    key = f"rl:{client_id}"
    now = int(time.time() * 1000)
    member = f"{now}-{uuid.uuid4().hex[:8]}"
    pipe = redis_conn.pipeline()
    pipe.zremrangebyscore(key, 0, now - WINDOW_MS)
    pipe.zadd(key, {member: now})
    pipe.zcard(key)
    pipe.pexpire(key, WINDOW_MS + 1000)
    _, _, count, _ = pipe.execute()
    if count <= limit:
        return True, 0
    redis_conn.zrem(key, member)
    oldest = redis_conn.zrange(key, 0, 0, withscores=True)
    retry_ms = (oldest[0][1] + WINDOW_MS - now) if oldest else WINDOW_MS
    return False, max(1, math.ceil(retry_ms / 1000))
