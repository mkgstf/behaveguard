from __future__ import annotations

import pytest
from sqlalchemy import text

from behaveguard import database
from behaveguard.db.engine import engine
from behaveguard.db.models import Base
from behaveguard.redis_client import get_redis


@pytest.fixture(scope="session", autouse=True)
def _refuse_to_run_against_a_non_test_database():
    """Hard safety check, checked once before anything else: `_clean_tables`
    below TRUNCATEs every table before every single test. `DATABASE_URL`
    defaults to the exact same Postgres the real dev API server uses, so
    running `pytest` without ever pointing it at a dedicated database wipes
    real data — users, profiles, sessions, everything — with no warning.
    This has actually happened (wiped a promoted-admin account and a claimed
    profile). Refuse to proceed unless the database name looks like a test
    database; set DATABASE_URL to something like
    `.../behaveguard_test` before running tests otherwise.
    """
    db_name = engine.url.database or ""
    if "test" not in db_name.lower():
        pytest.exit(
            f"\n\nRefusing to run: DATABASE_URL points at database {db_name!r}, which doesn't "
            "look like a dedicated test database (its name should contain 'test'). "
            "The test suite TRUNCATEs every table before every test — running it against "
            "your real/dev database will silently delete all real data (users, profiles, "
            "sessions, admin roles, claimed profiles — all of it).\n\n"
            "Fix: export DATABASE_URL to a separate database first, e.g.:\n"
            "  export DATABASE_URL=postgresql+psycopg://behaveguard:behaveguard@localhost:5432/behaveguard_test\n",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    """Ensure the schema exists once for the whole test session.

    Tests run against whatever DATABASE_URL points at (see docker-compose.yml
    for local defaults, or export DATABASE_URL to point at a dedicated
    `behaveguard_test` database in CI so this never touches real data).
    """
    database.init_db()
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table before each test so tests stay isolated, replacing
    the old pattern of monkeypatching `database.DB_PATH` to a fresh temp
    SQLite file per test (there is one shared Postgres instance now, not a
    file per test)."""
    with engine.begin() as connection:
        table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture(autouse=True)
def _clean_redis():
    """Flushes Redis before each test — rate-limit counters, replay-detection
    sets, and job-queue state (Phase 3/4) all live in Redis and would
    otherwise leak between tests the same way stale Postgres rows would.
    Uses the same `REDIS_URL` as the app (see docker-compose.yml); assumes a
    dedicated/local Redis instance, same assumption as the Postgres fixture
    above."""
    get_redis().flushall()
    yield
