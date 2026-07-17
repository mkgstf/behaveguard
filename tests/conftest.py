from __future__ import annotations

import pytest
from sqlalchemy import text

from behaveguard import database
from behaveguard.db.engine import engine
from behaveguard.db.models import Base


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
