from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import CLOUD_RUN_JOB_NAME, CLOUD_RUN_JOB_REGION, GOOGLE_CLOUD_PROJECT
from .redis_client import get_redis

logger = logging.getLogger("behaveguard.jobs")

# Job status tracking (unchanged from the original Redis-Streams design): a
# small TTL'd Redis hash per job id, moving queued -> running -> done/failed
# as the job processes. This is operational visibility, not a durable audit
# record — the durable record of *what a retrain actually did* is the
# `model_versions` table (see database.py). This part didn't need to change
# when the trigger mechanism below did.
_JOB_STATUS_TTL_SECONDS = 7 * 24 * 3600
_RECENT_JOBS_KEY = "behaveguard:recent_jobs"
_RECENT_JOBS_MAX = 50


def _status_key(job_id: str) -> str:
    return f"behaveguard:job_status:{job_id}"


def trigger_retrain_job(reason: str) -> str:
    """Starts a retrain-neural job and returns its job id immediately —
    this is the entire cost of "requesting a retrain" from the HTTP path;
    the actual (potentially slow) training happens out-of-band, not in the
    request handler.

    Phase 5 redesign: previously this pushed onto a Redis Streams consumer
    group that an always-running worker process pulled from. That worker
    had to stay up 24/7 to ever process anything, which is a real ongoing
    cost for something that only needs to run occasionally. Now:

    - In production (CLOUD_RUN_JOB_NAME/CLOUD_RUN_JOB_REGION/
      GOOGLE_CLOUD_PROJECT all set): triggers a one-shot Cloud Run Job
      execution via the Cloud Run Admin API, passing this job's id/type/
      reason as container env var overrides. The job container runs,
      does the retrain, and exits — billed only for the seconds it
      actually runs, nothing kept warm in between.
    - Locally (any of those unset, the default): runs the same job function
      in a background daemon thread in-process, so `uv run behaveguard
      serve` alone still works with zero GCP setup, same as before.
    """
    job_id = str(uuid.uuid4())
    job_type = "retrain_neural"
    _set_status(job_id, "queued", type=job_type, reason=reason, queued_at=datetime.now(UTC).isoformat())
    _remember_job(job_id)

    if CLOUD_RUN_JOB_NAME and CLOUD_RUN_JOB_REGION and GOOGLE_CLOUD_PROJECT:
        _trigger_cloud_run_job_execution(job_id, job_type, reason)
    else:
        _trigger_local_background_thread(job_id, job_type, reason)

    return job_id


def _trigger_cloud_run_job_execution(job_id: str, job_type: str, reason: str) -> None:
    from google.cloud import run_v2

    client = run_v2.JobsClient()
    job_name = client.job_path(GOOGLE_CLOUD_PROJECT, CLOUD_RUN_JOB_REGION, CLOUD_RUN_JOB_NAME)
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(
                env=[
                    run_v2.EnvVar(name="RETRAIN_JOB_ID", value=job_id),
                    run_v2.EnvVar(name="RETRAIN_JOB_TYPE", value=job_type),
                    run_v2.EnvVar(name="RETRAIN_JOB_REASON", value=reason),
                ]
            )
        ]
    )
    try:
        client.run_job(request=run_v2.RunJobRequest(name=job_name, overrides=overrides))
    except Exception:
        # Triggering the execution failed (bad IAM, job doesn't exist, GCP
        # hiccup) — record it as failed rather than leaving it stuck at
        # "queued" forever with nothing actually running.
        logger.exception("Failed to trigger Cloud Run Job execution for job %s", job_id)
        set_job_status(job_id, "failed", error="Could not start the Cloud Run Job execution")


def _trigger_local_background_thread(job_id: str, job_type: str, reason: str) -> None:
    from .worker import run_retrain_job

    thread = threading.Thread(
        target=run_retrain_job, args=(job_id, job_type, reason), daemon=True,
        name=f"behaveguard-retrain-{job_id[:8]}",
    )
    thread.start()


def _set_status(job_id: str, status: str, **extra: Any) -> None:
    payload = {"job_id": job_id, "status": status, **extra}
    get_redis().set(_status_key(job_id), json.dumps(payload), ex=_JOB_STATUS_TTL_SECONDS)


def _remember_job(job_id: str) -> None:
    redis = get_redis()
    redis.lpush(_RECENT_JOBS_KEY, job_id)
    redis.ltrim(_RECENT_JOBS_KEY, 0, _RECENT_JOBS_MAX - 1)


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
