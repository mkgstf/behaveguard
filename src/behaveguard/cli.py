from pathlib import Path

import typer
import uvicorn

from .api import app as api_app
from .database import (
    create_claim_token, get_profile_by_label, init_db, list_merge_events, merge_profiles,
    promote_user_role, revert_merge_event,
)
from .importer import import_xlsx
from .merging import scan_and_auto_merge
from .modeling import model_status, retrain_model
from .training import train_neural
from .experiments import run_experiments
from .personal_verifier import train_personal_verifier
from .worker import run_worker

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


@app.command("generate-claim-token")
def generate_claim_token(profile_label: str) -> None:
    """Generate a one-time link for the real owner of a pre-existing/legacy
    profile (e.g. one created by `import-xlsx`) to connect it to their own
    self-registered account. Send the printed token to that person yourself
    (email, Slack, in person) — there is no automated delivery in Phase 1.
    """
    init_db()
    try:
        profile = get_profile_by_label(profile_label)
    except KeyError:
        typer.echo(f"No profile found with label {profile_label!r}.")
        raise typer.Exit(1)
    try:
        token = create_claim_token(profile["id"])
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(1)
    typer.echo(f"Claim token for '{profile_label}' (send this to its real owner):")
    typer.echo(token)


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


@app.command("worker")
def worker_command(
    consumer_name: str = typer.Option(None, help="Consumer identity within the retrain_workers group (defaults to hostname-based)"),
) -> None:
    """Run the retrain-job worker as a standalone, blocking process.

    Not required for local dev — `behaveguard serve` already runs this same
    loop as a background thread automatically. This command exists for the
    deployment shape where the worker runs as its own independent
    service/container instead (see worker.py's docstring), and for anyone
    who wants to run it separately locally too (e.g. to watch its logs on
    their own, or restart it independently of the API process).
    """
    run_worker(consumer_name=consumer_name)
