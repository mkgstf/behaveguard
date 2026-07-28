from __future__ import annotations

import redis

from .config import REDIS_URL

# `decode_responses=True` so callers get str, not bytes, back from Redis —
# every value this app stores/reads (job payload JSON, rate-limit counters,
# replay-detection hashes) is text.
_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client
