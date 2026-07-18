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

# --- Phase 1: auth ---------------------------------------------------------

# HS256-signed JWTs. In production this must be set to a long random value
# via env var — the fallback here is only for local dev convenience and is
# intentionally obvious/unsafe so it's never mistaken for a real secret.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# Profile claim tokens (linking a pre-existing/legacy profile to a newly
# registered account) — see database.create_claim_token / claim_profile.
CLAIM_TOKEN_EXPIRE_DAYS = int(os.getenv("CLAIM_TOKEN_EXPIRE_DAYS", "7"))

# Google OAuth ("Sign in with Google"). Required only for the
# /auth/google/* routes; password-based register/login work without these.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")

# Where to send the browser after a successful Google login, with tokens in
# the URL fragment (see api.py's /auth/google/callback for why a fragment).
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# --- Phase 2: direct-enroll + auto-merge -----------------------------------

# A self-verification (POST /verify/{own_profile_id}) at or above this
# similarity is confident enough to fold in as an additional enrollment
# session automatically — this is the "quality gate" that replaces a human
# reviewer for re-enrollment. Deliberately higher than the ~62 match
# threshold used for the accept/reject decision itself.
AUTO_ENROLLMENT_SIMILARITY_THRESHOLD = float(os.getenv("AUTO_ENROLLMENT_SIMILARITY_THRESHOLD", "85.0"))

# Centroid cosine similarity (as a 0-1 fraction, not the 0-100 display scale)
# above which two profiles are treated as the same person and auto-merged.
# Deliberately conservative — this executes without human review, so a false
# merge is much costlier than a missed one.
AUTO_MERGE_SIMILARITY_THRESHOLD = float(os.getenv("AUTO_MERGE_SIMILARITY_THRESHOLD", "0.97"))


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    PERSONAL_NEURAL_DIR.mkdir(parents=True, exist_ok=True)
