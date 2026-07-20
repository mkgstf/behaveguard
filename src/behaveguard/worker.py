from __future__ import annotations

import logging
import socket
import time
import uuid

from .config import RETRAIN_CONSUMER_GROUP, RETRAIN_JOB_CLAIM_TIMEOUT_MS, RETRAIN_STREAM_KEY
from .database import init_db
from .jobs import ensure_consumer_group, set_job_status
from .redis_client import get_redis
from .training import train_neural_and_promote

logger = logging.getLogger("behaveguard.worker")


def _process_job(job_id: str, job_type: str, reason: str) -> None:
    set_job_status(job_id, "running")
    try:
        if job_type == "retrain_neural":
            result = train_neural_and_promote()
        else:
            result = {"trained": False, "reason": f"Unknown job type: {job_type}"}
        set_job_status(job_id, "done", result=result)
        logger.info("job %s (%s, reason=%s) completed: %s", job_id, job_type, reason, result)
    except Exception as error:  # noqa: BLE001 - a failed job must not crash the worker loop
        set_job_status(job_id, "failed", error=str(error))
        logger.exception("job %s (%s, reason=%s) failed", job_id, job_type, reason)


def _reclaim_stale_jobs(redis, consumer_name: str) -> None:
    """Picks up any job claimed by a consumer that died mid-processing
    (crashed worker, killed process, etc.) — XAUTOCLAIM reassigns entries
    that have been pending longer than the claim timeout to this consumer."""
    try:
        _, claimed, _ = redis.xautoclaim(
            RETRAIN_STREAM_KEY, RETRAIN_CONSUMER_GROUP, consumer_name,
            min_idle_time=RETRAIN_JOB_CLAIM_TIMEOUT_MS, start_id="0-0", count=10,
        )
    except Exception:
        return
    for entry_id, fields in claimed:
        _process_job(fields.get("job_id", entry_id), fields.get("type", "unknown"), fields.get("reason", ""))
        redis.xack(RETRAIN_STREAM_KEY, RETRAIN_CONSUMER_GROUP, entry_id)


def run_worker(consumer_name: str | None = None, iterations: int | None = None) -> None:
    """Blocking consumer loop. `iterations=None` runs forever (the normal
    case — `behaveguard worker`); a finite `iterations` is used by tests to
    process exactly N poll cycles without hanging.
    """
    init_db()
    ensure_consumer_group()
    redis = get_redis()
    consumer_name = consumer_name or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    logger.info("worker %s started, consuming %s", consumer_name, RETRAIN_STREAM_KEY)

    count = 0
    while iterations is None or count < iterations:
        count += 1
        _reclaim_stale_jobs(redis, consumer_name)
        response = redis.xreadgroup(
            RETRAIN_CONSUMER_GROUP, consumer_name, {RETRAIN_STREAM_KEY: ">"}, count=1, block=2000,
        )
        if not response:
            continue
        for _, entries in response:
            for entry_id, fields in entries:
                _process_job(fields.get("job_id", entry_id), fields.get("type", "unknown"), fields.get("reason", ""))
                redis.xack(RETRAIN_STREAM_KEY, RETRAIN_CONSUMER_GROUP, entry_id)


def run_worker_in_background_thread() -> None:
    """Local-dev convenience: starts the worker loop as a daemon thread
    inside the same process as the API (called from api.py's startup
    event), so `uv run behaveguard serve` alone is enough — no second
    terminal needed.

    This is a deliberate local-only shortcut, not the production shape: in
    the deployment phase this becomes its own service/container running
    `behaveguard worker` independently, so the API and worker can scale,
    restart, and fail independently of each other. The consumer-group
    design here doesn't change either way — only how the loop gets started.
    """
    import threading

    thread = threading.Thread(target=run_worker, daemon=True, name="behaveguard-worker")
    thread.start()
