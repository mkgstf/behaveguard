from __future__ import annotations

import logging

from .database import init_db
from .jobs import set_job_status
from .training import train_neural_and_promote

logger = logging.getLogger("behaveguard.worker")


def run_retrain_job(job_id: str, job_type: str, reason: str) -> dict:
    """Runs exactly one retrain job and returns its result.

    Phase 5 redesign: this used to be called from inside a persistent
    Redis-Streams consumer loop (`run_worker`, since removed) that had to
    stay running 24/7 to ever process anything. Now it's a one-shot
    function — the single entrypoint used by both:
    - the Cloud Run Job container (via `behaveguard run-retrain-job`,
      reading job_id/job_type/reason from env vars — see cli.py), which
      runs this once and exits, billed only for the seconds it runs; and
    - local dev's background-thread fallback (see jobs.py's
      `_trigger_local_background_thread`), for zero-GCP-setup local runs.

    Never raises — a failed job records its own "failed" status rather than
    propagating, since callers (a background thread, or a Cloud Run Job
    entrypoint that still needs to set its own exit code) each handle that
    differently.
    """
    init_db()
    set_job_status(job_id, "running")
    try:
        if job_type == "retrain_neural":
            result = train_neural_and_promote()
        else:
            result = {"trained": False, "reason": f"Unknown job type: {job_type}"}
        set_job_status(job_id, "done", result=result)
        logger.info("job %s (%s, reason=%s) completed: %s", job_id, job_type, reason, result)
        return result
    except Exception as error:  # noqa: BLE001 - record the failure, don't crash the caller
        set_job_status(job_id, "failed", error=str(error))
        logger.exception("job %s (%s, reason=%s) failed", job_id, job_type, reason)
        return {"trained": False, "error": str(error)}
