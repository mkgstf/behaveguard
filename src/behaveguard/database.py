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
            CREATE TABLE IF NOT EXISTS review_samples (
                id TEXT PRIMARY KEY,
                verification_event_id TEXT REFERENCES verification_events(id) ON DELETE SET NULL,
                mode TEXT NOT NULL,
                claimed_profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
                predicted_profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
                candidate_ids TEXT NOT NULL,
                payload TEXT NOT NULL,
                features TEXT NOT NULL,
                result TEXT NOT NULL,
                feedback_correct INTEGER,
                true_profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'awaiting_feedback'
                    CHECK(status IN ('awaiting_feedback','pending','approved','rejected')),
                promoted_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                trained_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_review_samples_status ON review_samples(status, created_at);
            """
        )
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(review_samples)").fetchall()}
        if "trained_at" not in columns:
            conn.execute("ALTER TABLE review_samples ADD COLUMN trained_at TEXT")


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


def log_verification(mode: str, claimed: str | None, candidates: list[str], result: dict[str, Any]) -> str:
    event_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            "INSERT INTO verification_events VALUES(?,?,?,?,?,?)",
            (event_id, mode, claimed, json.dumps(candidates), json.dumps(result), utcnow()),
        )
    return event_id


def create_review_sample(
    event_id: str,
    mode: str,
    claimed_profile_id: str | None,
    predicted_profile_id: str | None,
    candidate_ids: list[str],
    payload: dict[str, Any],
    features: dict[str, float],
    result: dict[str, Any],
) -> str:
    review_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            """INSERT INTO review_samples(
                id,verification_event_id,mode,claimed_profile_id,predicted_profile_id,
                candidate_ids,payload,features,result,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                review_id, event_id, mode, claimed_profile_id, predicted_profile_id,
                json.dumps(candidate_ids), json.dumps(payload), json.dumps(features), json.dumps(result), utcnow(),
            ),
        )
    return review_id


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["candidate_ids"] = json.loads(item["candidate_ids"])
    item["result"] = json.loads(item["result"])
    item["feedback_correct"] = None if item["feedback_correct"] is None else bool(item["feedback_correct"])
    return item


def get_review_sample(review_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT r.id,r.mode,r.claimed_profile_id,r.predicted_profile_id,r.candidate_ids,
                r.result,r.feedback_correct,r.true_profile_id,r.status,r.promoted_session_id,
                r.created_at,r.reviewed_at,r.trained_at,claimed.label AS claimed_label,
                predicted.label AS predicted_label,truth.label AS true_label
            FROM review_samples r
            LEFT JOIN profiles claimed ON claimed.id=r.claimed_profile_id
            LEFT JOIN profiles predicted ON predicted.id=r.predicted_profile_id
            LEFT JOIN profiles truth ON truth.id=r.true_profile_id
            WHERE r.id=?""",
            (review_id,),
        ).fetchone()
    if row is None:
        raise KeyError(review_id)
    return _review_row(row)


def get_review_sample_material(review_id: str) -> dict[str, Any]:
    """Return sensitive probe material for server-side comparison only."""
    with connection() as conn:
        row = conn.execute("SELECT payload,features FROM review_samples WHERE id=?", (review_id,)).fetchone()
    if row is None:
        raise KeyError(review_id)
    return {"payload": json.loads(row["payload"]), "features": json.loads(row["features"])}


def list_review_samples(statuses: tuple[str, ...] = ("awaiting_feedback", "pending")) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT r.id,r.mode,r.claimed_profile_id,r.predicted_profile_id,r.candidate_ids,
                r.result,r.feedback_correct,r.true_profile_id,r.status,r.promoted_session_id,
                r.created_at,r.reviewed_at,r.trained_at,claimed.label AS claimed_label,
                predicted.label AS predicted_label,truth.label AS true_label
            FROM review_samples r
            LEFT JOIN profiles claimed ON claimed.id=r.claimed_profile_id
            LEFT JOIN profiles predicted ON predicted.id=r.predicted_profile_id
            LEFT JOIN profiles truth ON truth.id=r.true_profile_id
            WHERE r.status IN ({placeholders}) ORDER BY r.created_at DESC""",
            statuses,
        ).fetchall()
    return [_review_row(row) for row in rows]


def submit_review_feedback(review_id: str, prediction_correct: bool, true_profile_id: str | None) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "SELECT predicted_profile_id,status FROM review_samples WHERE id=?",
            (review_id,),
        ).fetchone()
        if row is None:
            raise KeyError(review_id)
        if row["status"] in ("approved", "rejected"):
            raise ValueError("This sample has already been reviewed")
        target = true_profile_id or (str(row["predicted_profile_id"]) if prediction_correct and row["predicted_profile_id"] else None)
        if target is not None:
            profile = conn.execute("SELECT blacklisted FROM profiles WHERE id=?", (target,)).fetchone()
            if profile is None:
                raise KeyError(target)
            if profile["blacklisted"]:
                raise ValueError("Feedback cannot target a blacklisted profile")
        status = "pending" if target else "rejected"
        conn.execute(
            """UPDATE review_samples SET feedback_correct=?,true_profile_id=?,status=?,reviewed_at=?
            WHERE id=?""",
            (int(prediction_correct), target, status, utcnow(), review_id),
        )
    return get_review_sample(review_id)


def promote_review_sample(review_id: str, profile_id: str | None = None) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM review_samples WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise KeyError(review_id)
        if row["status"] == "approved":
            raise ValueError("This sample has already been promoted")
        if row["status"] == "rejected":
            raise ValueError("A rejected sample cannot be promoted")
        target = profile_id or row["true_profile_id"]
        if not target:
            raise ValueError("Assign a true identity before approving this sample")
        profile = conn.execute("SELECT blacklisted FROM profiles WHERE id=?", (target,)).fetchone()
        if profile is None:
            raise KeyError(str(target))
        if profile["blacklisted"]:
            raise ValueError("A blacklisted profile cannot receive training samples")
        session_id = str(uuid.uuid4())
        payload = json.loads(row["payload"])
        conn.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",
            (
                session_id, target, "reviewed_verification", str(payload.get("collected_at") or utcnow()),
                row["payload"], row["features"], utcnow(),
            ),
        )
        now = utcnow()
        conn.execute("UPDATE profiles SET updated_at=? WHERE id=?", (now, target))
        conn.execute(
            """UPDATE review_samples SET true_profile_id=?,status='approved',
            promoted_session_id=?,reviewed_at=? WHERE id=?""",
            (target, session_id, now, review_id),
        )
    return get_review_sample(review_id)


def reject_review_sample(review_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT status FROM review_samples WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise KeyError(review_id)
        if row["status"] == "approved":
            raise ValueError("A promoted sample cannot be rejected")
        conn.execute(
            "UPDATE review_samples SET status='rejected',reviewed_at=? WHERE id=?",
            (utcnow(), review_id),
        )
    return get_review_sample(review_id)


def review_sample_counts() -> dict[str, int]:
    counts = {status: 0 for status in ("awaiting_feedback", "pending", "approved", "rejected")}
    with connection() as conn:
        rows = conn.execute("SELECT status,COUNT(*) AS count FROM review_samples GROUP BY status").fetchall()
    counts.update({str(row["status"]): int(row["count"]) for row in rows})
    counts["available"] = counts["awaiting_feedback"] + counts["pending"]
    with connection() as conn:
        counts["ready_for_retrain"] = int(conn.execute(
            "SELECT COUNT(*) FROM review_samples WHERE status='approved' AND trained_at IS NULL"
        ).fetchone()[0])
    return counts


def mark_approved_samples_trained() -> int:
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE review_samples SET trained_at=? WHERE status='approved' AND trained_at IS NULL",
            (utcnow(),),
        )
    return int(cursor.rowcount)


def verification_count() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM verification_events").fetchone()[0])
