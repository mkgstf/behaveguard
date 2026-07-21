from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from fastapi import HTTPException, Request

from .config import (
    RATE_LIMIT_LOGIN_PER_MINUTE,
    RATE_LIMIT_VERIFY_PER_MINUTE,
    REPLAY_DETECTION_TTL_SECONDS,
)
from .database import create_security_alert
from .redis_client import get_redis

# --- Rate limiting -----------------------------------------------------------

# Fixed-window counter: simple, and precise enough for brute-force
# protection at this scale (a sliding-window log would be more exact at
# window boundaries but isn't worth the extra Redis round-trips here).
_BRUTE_FORCE_ALERT_THRESHOLD = 3  # blocked attempts within the dedupe window below...
_BRUTE_FORCE_DEDUPE_SECONDS = 3600  # ...raises at most one alert per hour per key


def _client_ip(request: Request) -> str:
    # Trusts X-Forwarded-For only because this app is expected to sit behind
    # a reverse proxy/load balancer in any real deployment; falls back to
    # the direct peer address for local dev where there is no proxy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(bucket: str, key: str, limit: int) -> None:
    redis = get_redis()
    window = int(time.time() // 60)
    counter_key = f"behaveguard:ratelimit:{bucket}:{key}:{window}"
    count = redis.incr(counter_key)
    if count == 1:
        redis.expire(counter_key, 120)  # a little over one window; avoids a leaked key on incr-only paths
    if count <= limit:
        return

    # Blocked — track how often this key gets blocked, and raise a
    # brute-force alert (deduped per hour) once it happens repeatedly,
    # rather than on every single blocked request.
    block_key = f"behaveguard:ratelimit:blocked:{bucket}:{key}"
    blocked_count = redis.incr(block_key)
    redis.expire(block_key, _BRUTE_FORCE_DEDUPE_SECONDS)
    if blocked_count == _BRUTE_FORCE_ALERT_THRESHOLD:
        dedupe_key = f"behaveguard:ratelimit:alerted:{bucket}:{key}"
        if redis.set(dedupe_key, "1", nx=True, ex=_BRUTE_FORCE_DEDUPE_SECONDS):
            create_security_alert(
                "brute_force", "high",
                {"bucket": bucket, "key": key, "blocked_count": blocked_count},
            )
    raise HTTPException(429, "Too many attempts. Please wait a moment and try again.")


def rate_limit_login(request: Request) -> None:
    _check_rate_limit("login", _client_ip(request), RATE_LIMIT_LOGIN_PER_MINUTE)


def rate_limit_verify(request: Request, profile_id: str) -> None:
    _check_rate_limit("verify", profile_id, RATE_LIMIT_VERIFY_PER_MINUTE)


# --- Replay detection ---------------------------------------------------------


def _payload_hash(session: dict[str, Any]) -> str:
    # Stable serialization (sorted keys) so semantically-identical payloads
    # hash identically regardless of key order.
    canonical = json.dumps(session, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_replay(profile_id: str, session: dict[str, Any]) -> None:
    """Raises a passive `replay_suspected` alert (never blocks the request)
    if this exact payload was already submitted for this profile recently.
    A literal byte-for-byte repeat of a raw event stream is not something a
    live human types/moves twice — it's the signature of a captured-and-
    resubmitted session."""
    redis = get_redis()
    digest = _payload_hash(session)
    key = f"behaveguard:replay:{profile_id}"
    if redis.sismember(key, digest):
        create_security_alert(
            "replay_suspected", "medium", {"payload_hash": digest}, profile_id=profile_id,
        )
        return
    redis.sadd(key, digest)
    redis.expire(key, REPLAY_DETECTION_TTL_SECONDS)


# --- FAR-spike detection -------------------------------------------------------

_FAR_SPIKE_WINDOW = 5
_FAR_SPIKE_MIN_HITS = 3
_FAR_SPIKE_BAND = 5.0  # similarity points below threshold considered "near-miss"


def track_verification_score(profile_id: str, similarity: float, threshold: float) -> None:
    """Keeps a short rolling window of recent similarity scores for this
    profile and raises a `far_spike` alert if several recent attempts
    clustered suspiciously close to (but under) the accept threshold —
    a pattern consistent with someone probing for the boundary rather than
    a single person's naturally varying typing/mouse behavior."""
    if not (threshold - _FAR_SPIKE_BAND <= similarity < threshold):
        return
    redis = get_redis()
    key = f"behaveguard:far_scores:{profile_id}"
    redis.lpush(key, similarity)
    redis.ltrim(key, 0, _FAR_SPIKE_WINDOW - 1)
    redis.expire(key, 3600)
    recent = [float(value) for value in redis.lrange(key, 0, _FAR_SPIKE_WINDOW - 1)]
    near_miss_count = sum(1 for value in recent if threshold - _FAR_SPIKE_BAND <= value < threshold)
    if near_miss_count >= _FAR_SPIKE_MIN_HITS:
        dedupe_key = f"behaveguard:far_spike_alerted:{profile_id}"
        if redis.set(dedupe_key, "1", nx=True, ex=3600):
            create_security_alert(
                "far_spike", "medium",
                {"recent_scores": recent, "threshold": threshold, "near_miss_count": near_miss_count},
                profile_id=profile_id,
            )
