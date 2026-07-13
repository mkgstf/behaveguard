from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from .config import DB_PATH, ensure_directories


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    ensure_directories()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL UNIQUE COLLATE NOCASE,
                blacklisted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                purpose TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                features TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_profile ON sessions(profile_id);
            CREATE TABLE IF NOT EXISTS verification_events (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                claimed_profile_id TEXT,
                candidates TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def create_profile(label: str) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    now = utcnow()
    with connection() as conn:
        conn.execute(
            "INSERT INTO profiles(id,label,created_at,updated_at) VALUES(?,?,?,?)",
            (profile_id, label.strip(), now, now),
        )
    return get_profile(profile_id)


def list_profiles(include_blacklisted: bool = True) -> list[dict[str, Any]]:
    where = "" if include_blacklisted else "WHERE p.blacklisted = 0"
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT p.*, COUNT(s.id) AS enrollment_count,
                MAX(s.collected_at) AS last_enrollment
                FROM profiles p LEFT JOIN sessions s ON s.profile_id=p.id
                {where} GROUP BY p.id ORDER BY p.label COLLATE NOCASE"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_profile(profile_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT p.*, COUNT(s.id) AS enrollment_count,
            MAX(s.collected_at) AS last_enrollment
            FROM profiles p LEFT JOIN sessions s ON s.profile_id=p.id
            WHERE p.id=? GROUP BY p.id""",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise KeyError(profile_id)
    return dict(row)


def get_profile_by_label(label: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE label=? COLLATE NOCASE", (label.strip(),)).fetchone()
    if row is None:
        raise KeyError(label)
    return get_profile(str(row["id"]))


def merge_profiles(source_label: str, target_label: str) -> dict[str, Any]:
    source = get_profile_by_label(source_label)
    target = get_profile_by_label(target_label)
    if source["id"] == target["id"]:
        return target
    with connection() as conn:
        conn.execute("UPDATE sessions SET profile_id=? WHERE profile_id=?", (target["id"], source["id"]))
        conn.execute("DELETE FROM profiles WHERE id=?", (source["id"],))
        conn.execute("UPDATE profiles SET updated_at=? WHERE id=?", (utcnow(), target["id"]))
    return get_profile(target["id"])


def set_blacklist(profile_id: str, value: bool) -> dict[str, Any]:
    with connection() as conn:
        cur = conn.execute(
            "UPDATE profiles SET blacklisted=?, updated_at=? WHERE id=?",
            (int(value), utcnow(), profile_id),
        )
        if cur.rowcount == 0:
            raise KeyError(profile_id)
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    with connection() as conn:
        cur = conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        if cur.rowcount == 0:
            raise KeyError(profile_id)


def add_session(profile_id: str, payload: dict[str, Any], features: dict[str, float], purpose: str = "enroll") -> str:
    session_id = str(uuid.uuid4())
    collected_at = str(payload.get("collected_at") or utcnow())
    with connection() as conn:
        conn.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",
            (session_id, profile_id, purpose, collected_at, json.dumps(payload), json.dumps(features), utcnow()),
        )
        conn.execute("UPDATE profiles SET updated_at=? WHERE id=?", (utcnow(), profile_id))
    return session_id


def all_training_rows() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT s.id, s.profile_id, s.payload, s.features, s.collected_at, p.label
            FROM sessions s JOIN profiles p ON p.id=s.profile_id
            WHERE p.blacklisted=0 ORDER BY s.created_at"""
        ).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload"]), "features": json.loads(row["features"])}
        for row in rows
    ]


def profile_sessions(profile_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,collected_at,features,payload FROM sessions WHERE profile_id=? ORDER BY collected_at",
            (profile_id,),
        ).fetchall()
    return [
        {**dict(row), "features": json.loads(row["features"]), "payload": json.loads(row["payload"])}
        for row in rows
    ]


def log_verification(mode: str, claimed: str | None, candidates: list[str], result: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO verification_events VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), mode, claimed, json.dumps(candidates), json.dumps(result), utcnow()),
        )


def verification_count() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM verification_events").fetchone()[0])
