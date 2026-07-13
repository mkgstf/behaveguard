from pathlib import Path

import typer
import uvicorn

from .api import app as api_app
from .database import init_db, merge_profiles
from .importer import import_xlsx
from .modeling import model_status, retrain_model
from .training import train_neural
from .experiments import run_experiments

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


@app.command("merge-profiles")
def merge_profile_command(source: str, target: str) -> None:
    """Move all enrollment sessions from SOURCE into TARGET and delete SOURCE."""
    init_db()
    typer.echo(merge_profiles(source, target))
    typer.echo({"classical": retrain_model()})
