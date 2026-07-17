from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update, delete as sa_delete

from .db.engine import engine, session_scope
from .db.models import Base, Profile, ReviewSample, Session as SessionRow, VerificationEvent


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def init_db() -> None:
    """Idempotently ensure the schema exists.

    This is a dev-convenience fallback (mirrors the old `CREATE TABLE IF NOT
    EXISTS` behavior) so the app still works if someone runs it without ever
    calling `alembic upgrade head`. For real deployments, Alembic
    (`migrations/`) is the source of truth for schema changes; this function
    should not diverge from what `migrations/versions/0001_initial.py`
    creates.
    """
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        Base.metadata.create_all(bind=connection)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _profile_dict(profile: Profile, enrollment_count: int, last_enrollment: str | None) -> dict[str, Any]:
    return {
        "id": profile.id,
        "label": profile.label,
        "blacklisted": int(profile.blacklisted),
        "created_at": _iso(profile.created_at),
        "updated_at": _iso(profile.updated_at),
        "enrollment_count": int(enrollment_count),
        "last_enrollment": last_enrollment,
    }


def create_profile(label: str) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(Profile(id=profile_id, label=label.strip()))
    return get_profile(profile_id)


def _list_profiles_query(session, include_blacklisted: bool):
    query = (
        select(
            Profile,
            func.count(SessionRow.id).label("enrollment_count"),
            func.max(SessionRow.collected_at).label("last_enrollment"),
        )
        .outerjoin(SessionRow, SessionRow.profile_id == Profile.id)
        .group_by(Profile.id)
        .order_by(func.lower(Profile.label))
    )
    if not include_blacklisted:
        query = query.where(Profile.blacklisted.is_(False))
    return session.execute(query).all()


def list_profiles(include_blacklisted: bool = True) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = _list_profiles_query(session, include_blacklisted)
        return [_profile_dict(profile, count, last) for profile, count, last in rows]


def get_profile(profile_id: str) -> dict[str, Any]:
    with session_scope() as session:
        query = (
            select(
                Profile,
                func.count(SessionRow.id).label("enrollment_count"),
                func.max(SessionRow.collected_at).label("last_enrollment"),
            )
            .outerjoin(SessionRow, SessionRow.profile_id == Profile.id)
            .where(Profile.id == profile_id)
            .group_by(Profile.id)
        )
        row = session.execute(query).first()
        if row is None:
            raise KeyError(profile_id)
        profile, count, last = row
        return _profile_dict(profile, count, last)


def get_profile_by_label(label: str) -> dict[str, Any]:
    with session_scope() as session:
        row = session.execute(
            select(Profile.id).where(func.lower(Profile.label) == label.strip().lower())
        ).first()
        if row is None:
            raise KeyError(label)
        profile_id = row[0]
    return get_profile(profile_id)


def _replace_profile_reference(value: Any, source_id: str, target_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_profile_reference(item, source_id, target_id) for key, item in value.items()}
    if isinstance(value, list):
        replaced = [_replace_profile_reference(item, source_id, target_id) for item in value]
        return list(dict.fromkeys(replaced)) if all(isinstance(item, str) for item in replaced) else replaced
    return target_id if value == source_id else value


def merge_profiles(source_label: str, target_label: str) -> dict[str, Any]:
    source = get_profile_by_label(source_label)
    target = get_profile_by_label(target_label)
    if source["id"] == target["id"]:
        return target
    with session_scope() as session:
        for row in session.execute(select(ReviewSample)).scalars():
            row.candidate_ids = _replace_profile_reference(row.candidate_ids, source["id"], target["id"])
            row.result = _replace_profile_reference(row.result, source["id"], target["id"])
        for row in session.execute(select(VerificationEvent)).scalars():
            row.candidates = _replace_profile_reference(row.candidates, source["id"], target["id"])
            row.result = _replace_profile_reference(row.result, source["id"], target["id"])
        session.execute(
            update(SessionRow).where(SessionRow.profile_id == source["id"]).values(profile_id=target["id"])
        )
        session.execute(
            update(VerificationEvent)
            .where(VerificationEvent.claimed_profile_id == source["id"])
            .values(claimed_profile_id=target["id"])
        )
        for column in ("claimed_profile_id", "predicted_profile_id", "true_profile_id"):
            session.execute(
                update(ReviewSample).where(getattr(ReviewSample, column) == source["id"]).values(**{column: target["id"]})
            )
        session.execute(sa_delete(Profile).where(Profile.id == source["id"]))
        session.execute(update(Profile).where(Profile.id == target["id"]).values(updated_at=datetime.now(UTC)))
    return get_profile(target["id"])


def set_blacklist(profile_id: str, value: bool) -> dict[str, Any]:
    with session_scope() as session:
        result = session.execute(
            update(Profile).where(Profile.id == profile_id).values(blacklisted=value, updated_at=datetime.now(UTC))
        )
        if result.rowcount == 0:
            raise KeyError(profile_id)
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    with session_scope() as session:
        result = session.execute(sa_delete(Profile).where(Profile.id == profile_id))
        if result.rowcount == 0:
            raise KeyError(profile_id)


def add_session(profile_id: str, payload: dict[str, Any], features: dict[str, float], purpose: str = "enroll") -> str:
    session_id = str(uuid.uuid4())
    collected_at = str(payload.get("collected_at") or utcnow())
    with session_scope() as session:
        session.add(
            SessionRow(
                id=session_id, profile_id=profile_id, purpose=purpose,
                collected_at=collected_at, payload=payload, features=features,
            )
        )
        session.execute(
            update(Profile).where(Profile.id == profile_id).values(updated_at=datetime.now(UTC))
        )
    return session_id


def all_training_rows() -> list[dict[str, Any]]:
    with session_scope() as session:
        query = (
            select(SessionRow, Profile.label)
            .join(Profile, Profile.id == SessionRow.profile_id)
            .where(Profile.blacklisted.is_(False))
            .order_by(SessionRow.created_at)
        )
        rows = session.execute(query).all()
        return [
            {
                "id": row.id, "profile_id": row.profile_id, "payload": row.payload,
                "features": row.features, "collected_at": row.collected_at, "label": label,
            }
            for row, label in rows
        ]


def profile_sessions(profile_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = (
            select(SessionRow)
            .where(SessionRow.profile_id == profile_id)
            .order_by(SessionRow.collected_at)
        )
        rows = session.execute(query).scalars().all()
        return [
            {"id": row.id, "collected_at": row.collected_at, "features": row.features, "payload": row.payload}
            for row in rows
        ]


def log_verification(mode: str, claimed: str | None, candidates: list[str], result: dict[str, Any]) -> str:
    event_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            VerificationEvent(id=event_id, mode=mode, claimed_profile_id=claimed, candidates=candidates, result=result)
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
    with session_scope() as session:
        session.add(
            ReviewSample(
                id=review_id, verification_event_id=event_id, mode=mode,
                claimed_profile_id=claimed_profile_id, predicted_profile_id=predicted_profile_id,
                candidate_ids=candidate_ids, payload=payload, features=features, result=result,
            )
        )
    return review_id


def _review_dict(row: ReviewSample, claimed_label: str | None, predicted_label: str | None, true_label: str | None) -> dict[str, Any]:
    return {
        "id": row.id, "mode": row.mode, "claimed_profile_id": row.claimed_profile_id,
        "predicted_profile_id": row.predicted_profile_id, "candidate_ids": row.candidate_ids,
        "result": row.result, "feedback_correct": row.feedback_correct, "true_profile_id": row.true_profile_id,
        "status": row.status, "promoted_session_id": row.promoted_session_id,
        "created_at": _iso(row.created_at), "reviewed_at": _iso(row.reviewed_at), "trained_at": _iso(row.trained_at),
        "claimed_label": claimed_label, "predicted_label": predicted_label, "true_label": true_label,
    }


def _review_query(session, extra_where=None):
    Claimed = Profile.__table__.alias("claimed")
    Predicted = Profile.__table__.alias("predicted")
    Truth = Profile.__table__.alias("truth")
    query = (
        select(ReviewSample, Claimed.c.label, Predicted.c.label, Truth.c.label)
        .outerjoin(Claimed, Claimed.c.id == ReviewSample.claimed_profile_id)
        .outerjoin(Predicted, Predicted.c.id == ReviewSample.predicted_profile_id)
        .outerjoin(Truth, Truth.c.id == ReviewSample.true_profile_id)
    )
    if extra_where is not None:
        query = query.where(extra_where)
    return query


def get_review_sample(review_id: str) -> dict[str, Any]:
    with session_scope() as session:
        row = session.execute(_review_query(session, ReviewSample.id == review_id)).first()
        if row is None:
            raise KeyError(review_id)
        review, claimed_label, predicted_label, true_label = row
        return _review_dict(review, claimed_label, predicted_label, true_label)


def get_review_sample_material(review_id: str) -> dict[str, Any]:
    """Return sensitive probe material for server-side comparison only."""
    with session_scope() as session:
        row = session.execute(
            select(ReviewSample.payload, ReviewSample.features).where(ReviewSample.id == review_id)
        ).first()
        if row is None:
            raise KeyError(review_id)
        return {"payload": row.payload, "features": row.features}


def list_review_samples(statuses: tuple[str, ...] = ("awaiting_feedback", "pending")) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = _review_query(session, ReviewSample.status.in_(statuses)).order_by(ReviewSample.created_at.desc())
        rows = session.execute(query).all()
        return [_review_dict(review, claimed_label, predicted_label, true_label) for review, claimed_label, predicted_label, true_label in rows]


def submit_review_feedback(review_id: str, prediction_correct: bool, true_profile_id: str | None) -> dict[str, Any]:
    with session_scope() as session:
        review = session.get(ReviewSample, review_id)
        if review is None:
            raise KeyError(review_id)
        if review.status in ("approved", "rejected"):
            raise ValueError("This sample has already been reviewed")
        target = true_profile_id or (review.predicted_profile_id if prediction_correct and review.predicted_profile_id else None)
        if target is not None:
            profile = session.get(Profile, target)
            if profile is None:
                raise KeyError(target)
            if profile.blacklisted:
                raise ValueError("Feedback cannot target a blacklisted profile")
        review.feedback_correct = prediction_correct
        review.true_profile_id = target
        review.status = "pending" if target else "rejected"
        review.reviewed_at = datetime.now(UTC)
    return get_review_sample(review_id)


def promote_review_sample(review_id: str, profile_id: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        review = session.get(ReviewSample, review_id)
        if review is None:
            raise KeyError(review_id)
        if review.status == "approved":
            raise ValueError("This sample has already been promoted")
        if review.status == "rejected":
            raise ValueError("A rejected sample cannot be promoted")
        target = profile_id or review.true_profile_id
        if not target:
            raise ValueError("Assign a true identity before approving this sample")
        profile = session.get(Profile, target)
        if profile is None:
            raise KeyError(str(target))
        if profile.blacklisted:
            raise ValueError("A blacklisted profile cannot receive training samples")
        session_id = str(uuid.uuid4())
        payload = review.payload
        session.add(
            SessionRow(
                id=session_id, profile_id=target, purpose="reviewed_verification",
                collected_at=str(payload.get("collected_at") or utcnow()),
                payload=payload, features=review.features,
            )
        )
        # SQLAlchemy's unit-of-work doesn't know `review_samples.promoted_session_id`
        # depends on this brand-new session row (no ORM relationship links them),
        # so without an explicit flush here the INSERT and the following UPDATE
        # can be emitted in the wrong order and trip the foreign key constraint.
        session.flush()
        now = datetime.now(UTC)
        profile.updated_at = now
        review.true_profile_id = target
        review.status = "approved"
        review.promoted_session_id = session_id
        review.reviewed_at = now
    return get_review_sample(review_id)


def reject_review_sample(review_id: str) -> dict[str, Any]:
    with session_scope() as session:
        review = session.get(ReviewSample, review_id)
        if review is None:
            raise KeyError(review_id)
        if review.status == "approved":
            raise ValueError("A promoted sample cannot be rejected")
        review.status = "rejected"
        review.reviewed_at = datetime.now(UTC)
    return get_review_sample(review_id)


def review_sample_counts() -> dict[str, int]:
    counts = {status: 0 for status in ("awaiting_feedback", "pending", "approved", "rejected")}
    with session_scope() as session:
        rows = session.execute(
            select(ReviewSample.status, func.count()).group_by(ReviewSample.status)
        ).all()
        counts.update({status: int(count) for status, count in rows})
        counts["available"] = counts["awaiting_feedback"] + counts["pending"]
        counts["ready_for_retrain"] = int(
            session.execute(
                select(func.count()).where(ReviewSample.status == "approved", ReviewSample.trained_at.is_(None))
            ).scalar_one()
        )
    return counts


def mark_approved_samples_trained() -> int:
    with session_scope() as session:
        result = session.execute(
            update(ReviewSample)
            .where(ReviewSample.status == "approved", ReviewSample.trained_at.is_(None))
            .values(trained_at=datetime.now(UTC))
        )
    return int(result.rowcount)


def verification_count() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count()).select_from(VerificationEvent)).scalar_one())
