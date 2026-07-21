from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import RETRAIN_CONSUMER_GROUP, RETRAIN_STREAM_KEY
from .redis_client import get_redis

# Job status is tracked separately from the Stream entries themselves: a
# Stream entry is immutable once written (it just records "a retrain was
# requested, here's why"), while status needs to move
# queued -> running -> done/failed as the worker processes it. A small
# TTL'd Redis hash per job id is enough for this — it's operational
# visibility, not a durable audit record. The durable record of *what a
# retrain actually did* is the `model_versions` table (see database.py).
_JOB_STATUS_TTL_SECONDS = 7 * 24 * 3600
_RECENT_JOBS_KEY = "behaveguard:recent_jobs"
_RECENT_JOBS_MAX = 50


def _status_key(job_id: str) -> str:
    return f"behaveguard:job_status:{job_id}"


def ensure_consumer_group() -> None:
    """Idempotent — creates the stream + consumer group if they don't exist
    yet. Safe to call from both the API (on startup) and the worker."""
    redis = get_redis()
    try:
        redis.xgroup_create(RETRAIN_STREAM_KEY, RETRAIN_CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as error:  # redis raises a plain ResponseError for BUSYGROUP
        if "BUSYGROUP" not in str(error):
            raise


def enqueue_retrain_neural(reason: str) -> str:
    """Appends a retrain-neural job to the stream and returns its job id.
    Called instead of `train_neural(...)` directly from request handlers —
    this is the entire cost of "requesting a retrain" from the HTTP path;
    the actual (potentially slow) training happens out-of-band in the
    worker (see worker.py)."""
    ensure_consumer_group()
    redis = get_redis()
    job_id = str(uuid.uuid4())
    redis.xadd(RETRAIN_STREAM_KEY, {"job_id": job_id, "type": "retrain_neural", "reason": reason})
    redis.set(
        _status_key(job_id),
        json.dumps({"job_id": job_id, "type": "retrain_neural", "reason": reason, "status": "queued", "queued_at": datetime.now(UTC).isoformat()}),
        ex=_JOB_STATUS_TTL_SECONDS,
    )
    redis.lpush(_RECENT_JOBS_KEY, job_id)
    redis.ltrim(_RECENT_JOBS_KEY, 0, _RECENT_JOBS_MAX - 1)
    return job_id


def set_job_status(job_id: str, status: str, **extra: Any) -> None:
    redis = get_redis()
    raw = redis.get(_status_key(job_id))
    payload = json.loads(raw) if raw else {"job_id": job_id}
    payload["status"] = status
    payload[f"{status}_at"] = datetime.now(UTC).isoformat()
    payload.update(extra)
    redis.set(_status_key(job_id), json.dumps(payload), ex=_JOB_STATUS_TTL_SECONDS)


def get_job_status(job_id: str) -> dict[str, Any] | None:
    raw = get_redis().get(_status_key(job_id))
    return json.loads(raw) if raw else None


def list_recent_job_statuses() -> list[dict[str, Any]]:
    redis = get_redis()
    job_ids = redis.lrange(_RECENT_JOBS_KEY, 0, _RECENT_JOBS_MAX - 1)
    statuses = []
    for job_id in job_ids:
        status = get_job_status(job_id)
        if status:
            statuses.append(status)
    return statuses
