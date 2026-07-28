"""One-time migration of the v1 SQLite dev database into the Phase 0
PostgreSQL schema.

Preserves original ids and timestamps exactly (so every foreign key —
`sessions.profile_id`, `review_samples.promoted_session_id`, etc. — still
resolves correctly after migration), rather than going through
`database.py`'s public functions, which mint new ids/timestamps for most
inserts.

Usage:
    python scripts/migrate_sqlite_to_postgres.py [--sqlite-path PATH] [--dry-run]

`--sqlite-path` defaults to `behaveguard.config.DB_PATH` (the old
`data/behaveguard.db`). The Postgres target is whatever `DATABASE_URL` the
app is configured with (see `behaveguard.config.DATABASE_URL`).

Safe to re-run: rows that already exist in Postgres (matched by id) are
skipped rather than duplicated or overwritten.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from behaveguard.config import DATABASE_URL, DB_PATH
from behaveguard.db.engine import session_scope
from behaveguard.db.models import Profile, ReviewSample, Session as SessionRow, VerificationEvent


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _sqlite_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist in an older/newer SQLite schema variant — skip.
        return []


def migrate(sqlite_path: Path, dry_run: bool = False) -> dict[str, int]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"No SQLite database found at {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    counts = {"profiles": 0, "sessions": 0, "verification_events": 0, "review_samples": 0}

    try:
        with session_scope() as session:
            for row in _sqlite_rows(conn, "profiles"):
                if session.get(Profile, row["id"]) is not None:
                    continue
                counts["profiles"] += 1
                if dry_run:
                    continue
                session.add(
                    Profile(
                        id=row["id"],
                        label=row["label"],
                        blacklisted=bool(row["blacklisted"]),
                        created_at=_parse_dt(row["created_at"]),
                        updated_at=_parse_dt(row["updated_at"]),
                    )
                )
            session.flush()

            for row in _sqlite_rows(conn, "sessions"):
                if session.get(SessionRow, row["id"]) is not None:
                    continue
                counts["sessions"] += 1
                if dry_run:
                    continue
                session.add(
                    SessionRow(
                        id=row["id"],
                        profile_id=row["profile_id"],
                        purpose=row["purpose"],
                        collected_at=row["collected_at"],
                        payload=json.loads(row["payload"]),
                        features=json.loads(row["features"]),
                        created_at=_parse_dt(row["created_at"]),
                    )
                )
            session.flush()

            for row in _sqlite_rows(conn, "verification_events"):
                if session.get(VerificationEvent, row["id"]) is not None:
                    continue
                counts["verification_events"] += 1
                if dry_run:
                    continue
                session.add(
                    VerificationEvent(
                        id=row["id"],
                        mode=row["mode"],
                        claimed_profile_id=row["claimed_profile_id"],
                        candidates=json.loads(row["candidates"]),
                        result=json.loads(row["result"]),
                        created_at=_parse_dt(row["created_at"]),
                    )
                )
            session.flush()

            for row in _sqlite_rows(conn, "review_samples"):
                if session.get(ReviewSample, row["id"]) is not None:
                    continue
                counts["review_samples"] += 1
                if dry_run:
                    continue
                session.add(
                    ReviewSample(
                        id=row["id"],
                        verification_event_id=row["verification_event_id"],
                        mode=row["mode"],
                        claimed_profile_id=row["claimed_profile_id"],
                        predicted_profile_id=row["predicted_profile_id"],
                        candidate_ids=json.loads(row["candidate_ids"]),
                        payload=json.loads(row["payload"]),
                        features=json.loads(row["features"]),
                        result=json.loads(row["result"]),
                        feedback_correct=(
                            None if row["feedback_correct"] is None else bool(row["feedback_correct"])
                        ),
                        true_profile_id=row["true_profile_id"],
                        status=row["status"],
                        promoted_session_id=row["promoted_session_id"],
                        created_at=_parse_dt(row["created_at"]),
                        reviewed_at=_parse_dt(row["reviewed_at"]),
                        trained_at=_parse_dt(row["trained_at"]),
                    )
                )
    finally:
        conn.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", type=Path, default=DB_PATH, help="Path to the legacy behaveguard.db")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing to Postgres")
    args = parser.parse_args()

    print(f"Source SQLite DB: {args.sqlite_path}")
    print(f"Target Postgres:  {DATABASE_URL}")
    if args.dry_run:
        print("(dry run — no rows will be written)")

    counts = migrate(args.sqlite_path, dry_run=args.dry_run)
    for table, count in counts.items():
        print(f"  {table}: {count} row(s) {'would be ' if args.dry_run else ''}migrated")


if __name__ == "__main__":
    main()
