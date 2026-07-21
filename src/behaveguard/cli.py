import os
from pathlib import Path

import typer
import uvicorn

from .api import app as api_app
from .database import (
    init_db, list_merge_events, merge_profiles,
    promote_user_role, revert_merge_event,
)
from .importer import import_xlsx
from .merging import scan_and_auto_merge
from .modeling import model_status, retrain_model
from .training import train_neural
from .experiments import run_experiments
from .personal_verifier import train_personal_verifier
from .worker import run_retrain_job

app = typer.Typer(help="BehaveGuard administration and ML pipeline")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    uvicorn.run("behaveguard.api:app", host=host, port=port, reload=reload)


@app.command("import-xlsx")
def import_workbook(path: Path) -> None:
    init_db()
    typer.echo(import_xlsx(path))
    typer.echo(retrain_model())


@app.command()
def train(neural: bool = True, epochs: int = 30) -> None:
    init_db()
    typer.echo({"classical": retrain_model()})
    if neural:
        typer.echo({"neural": train_neural(epochs=epochs)})


@app.command()
def status() -> None:
    init_db()
    typer.echo(model_status())


@app.command()
def experiment(windows: int = 5, neural_epochs: int = 25) -> None:
    """Tune models, run ablations/profile comparisons, and train the experimental neural model."""
    init_db()
    report = run_experiments(window_count=windows, neural_epochs=neural_epochs)
    typer.echo({
        "validity": report["validity"], "best_model": report["best_model"],
        "best_metrics": report["best_metrics"], "ablations": report["ablations"],
        "neural": report["neural"],
    })


@app.command("personal-neural")
def personal_neural(label: str, epochs: int = 25, windows: int = 4) -> None:
    """Train and session-disjoint evaluate a personal neural verifier for LABEL."""
    init_db()
    report = train_personal_verifier(label, epochs=epochs, window_count=windows)
    typer.echo({
        "target": report["target_label"], "validity": report["validity"],
        "metrics": report["metrics"], "threshold": report["operating_threshold"],
    })


@app.command("merge-profiles")
def merge_profile_command(source: str, target: str) -> None:
    """Move all enrollment sessions from SOURCE into TARGET and delete SOURCE."""
    init_db()
    typer.echo(merge_profiles(source, target))
    typer.echo({"classical": retrain_model()})


@app.command("promote-admin")
def promote_admin(
    email: str,
    role: str = typer.Option("platform_admin", help="'org_admin' or 'platform_admin'"),
) -> None:
    """Promote an already-registered account to an admin role.

    This is the *only* way an account ever becomes org_admin/platform_admin —
    there is no HTTP route for it, by design (see Phase 1 spec: every
    account is created identically through self-service register/Google
    login; only role promotion is operator-only, and only reachable here).
    The account must already exist (register it normally first).
    """
    init_db()
    if not typer.confirm(f"Promote {email} to role={role!r}? This takes effect immediately."):
        raise typer.Abort()
    try:
        user = promote_user_role(email, role)
    except KeyError:
        typer.echo(f"No account found for {email!r} — they need to register first.")
        raise typer.Exit(1)
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(1)
    typer.echo({"email": user["email"], "role": user["role"]})


@app.command("auto-merge-scan")
def auto_merge_scan_command(threshold: float = typer.Option(None, help="Override the default similarity threshold")) -> None:
    """Scan all active profiles for likely duplicates and merge them
    immediately (no per-merge approval — see merging.py's docstring for why
    that's an acceptable default). Every merge is recorded and reversible
    via `revert-merge`."""
    init_db()
    kwargs = {} if threshold is None else {"threshold": threshold}
    result = scan_and_auto_merge(**kwargs)
    typer.echo(result)


@app.command("revert-merge")
def revert_merge_command(event_id: str) -> None:
    """Undo an automatic merge by its MergeEvent id (see `auto-merge-scan`
    output, or GET /api/v1/admin/merge/events)."""
    init_db()
    try:
        result = revert_merge_event(event_id)
    except KeyError:
        typer.echo(f"No merge event found with id {event_id!r}.")
        raise typer.Exit(1)
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(1)
    typer.echo(result)
    typer.echo({"classical": retrain_model()})


@app.command("run-retrain-job")
def run_retrain_job_command() -> None:
    """One-shot entrypoint for a Cloud Run Job execution: runs exactly one
    retrain job (reading which one from env vars set as container
    overrides — see jobs.trigger_retrain_job) and exits — no persistent
    process, nothing kept running afterward.

    Replaces the old `worker` command (a blocking, always-running consumer
    loop) as of the Phase 5 redeploy — see worker.py's docstring for why.
    Not meant to be run manually in normal operation; `trigger_retrain_job`
    is what invokes this, either via a real Cloud Run Job execution in
    production or a local background thread in dev.
    """
    job_id = os.environ.get("RETRAIN_JOB_ID")
    job_type = os.environ.get("RETRAIN_JOB_TYPE", "retrain_neural")
    reason = os.environ.get("RETRAIN_JOB_REASON", "")
    if not job_id:
        typer.echo("RETRAIN_JOB_ID env var is required — this command is meant to be invoked by trigger_retrain_job, not run directly.")
        raise typer.Exit(1)
    init_db()
    result = run_retrain_job(job_id, job_type, reason)
    if not result.get("trained", True) and "error" in result:
        # Non-zero exit so the Cloud Run Job execution is recorded as
        # failed (visible in its execution history/logs), not silently green.
        typer.echo(f"Job {job_id} failed: {result['error']}")
        raise typer.Exit(1)
    typer.echo(result)
