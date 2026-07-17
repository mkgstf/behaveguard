from __future__ import annotations

import os
from pathlib import Path


DATA_DIR = Path(os.getenv("BEHAVEGUARD_DATA_DIR", "data")).resolve()
ARTIFACT_DIR = Path(os.getenv("BEHAVEGUARD_ARTIFACT_DIR", "artifacts")).resolve()

# Legacy SQLite path. No longer used by the application at runtime — kept only
# as the default source path for scripts/migrate_sqlite_to_postgres.py.
DB_PATH = DATA_DIR / "behaveguard.db"

# Phase 0: PostgreSQL (+pgvector) replaces the SQLite file as the system of record.
# Defaults point at the docker-compose services in docker-compose.yml.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://behaveguard:behaveguard@localhost:5432/behaveguard",
)

# Phase 0: Redis is provisioned now (job-queue/cache use lands in a later phase).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Embedding dimensionality used by pgvector columns; must match
# BehavioralSequenceNet's fusion embedding_dim (see neural.py).
EMBEDDING_DIM = int(os.getenv("BEHAVEGUARD_EMBEDDING_DIM", "128"))
MODEL_PATH = ARTIFACT_DIR / "behavior_model.joblib"
NEURAL_PATH = ARTIFACT_DIR / "behavior_neural.pt"
PERSONAL_NEURAL_PATH = ARTIFACT_DIR / "personal_neural.pt"
PERSONAL_NEURAL_REPORT_PATH = ARTIFACT_DIR / "personal_neural_report.json"
PERSONAL_NEURAL_DIR = ARTIFACT_DIR / "personal_neural"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    PERSONAL_NEURAL_DIR.mkdir(parents=True, exist_ok=True)
