from __future__ import annotations

import os
from pathlib import Path


DATA_DIR = Path(os.getenv("BEHAVEGUARD_DATA_DIR", "data")).resolve()
ARTIFACT_DIR = Path(os.getenv("BEHAVEGUARD_ARTIFACT_DIR", "artifacts")).resolve()
DB_PATH = DATA_DIR / "behaveguard.db"
MODEL_PATH = ARTIFACT_DIR / "behavior_model.joblib"
NEURAL_PATH = ARTIFACT_DIR / "behavior_neural.pt"
PERSONAL_NEURAL_PATH = ARTIFACT_DIR / "personal_neural.pt"
PERSONAL_NEURAL_REPORT_PATH = ARTIFACT_DIR / "personal_neural_report.json"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
