from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update, delete as sa_delete
from sqlalchemy.exc import IntegrityError

from .config import CLAIM_TOKEN_EXPIRE_DAYS
from .db.engine import engine, session_scope
from .db.models import (
    Base,
    MergeEvent,
    ModelVersion,
    Profile,
    ProfileClaimToken,
    RefreshToken,
    ReviewSample,
    SecurityAlert,
    Session as SessionRow,
    User,
    VerificationEvent,
)


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
        "user_id": profile.user_id,
        "blacklisted": int(profile.blacklisted),
        "created_at": _iso(profile.created_at),
        "updated_at": _iso(profile.updated_at),
        "enrollment_count": int(enrollment_count),
        "last_enrollment": last_enrollment,
    }


def create_profile(label: str, user_id: str | None = None) -> dict[str, Any]:
    """`user_id=None` preserves the Phase-0 behavior (admin/import-created,
    unowned profile). Self-service enrollment (Phase 1) passes the
    registering user's id; the `uq_profiles_user_id` DB constraint enforces
    one profile per user regardless of caller."""
    profile_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(Profile(id=profile_id, label=label.strip(), user_id=user_id))
    return get_profile(profile_id)


def _list_profiles_query(session, include_blacklisted: bool, owner_user_id: str | None = None):
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
    if owner_user_id is not None:
        query = query.where(Profile.user_id == owner_user_id)
    return session.execute(query).all()


def list_profiles(include_blacklisted: bool = True, owner_user_id: str | None = None) -> list[dict[str, Any]]:
    """`owner_user_id` restricts results to profiles owned by that user —
    used by the API layer to implement "a `user`-role caller only sees their
    own profile(s)" without duplicating the join/aggregation logic."""
    with session_scope() as session:
        rows = _list_profiles_query(session, include_blacklisted, owner_user_id)
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


def get_profile_by_user(user_id: str) -> dict[str, Any] | None:
    """Returns the caller's own profile, or None if they haven't enrolled
    yet. Relies on the DB-level `uq_profiles_user_id` constraint guaranteeing
    at most one match."""
    with session_scope() as session:
        row = session.execute(select(Profile.id).where(Profile.user_id == user_id)).first()
    return get_profile(row[0]) if row else None


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


# --- Phase 1: users, refresh tokens, profile claim tokens -------------------


def _user_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "org_id": user.org_id,
        "email": user.email,
        "oauth_provider": user.oauth_provider,
        "role": user.role,
        "status": user.status,
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
    }


def create_user(
    email: str,
    password_hash: str | None = None,
    oauth_provider: str | None = None,
    oauth_subject: str | None = None,
) -> dict[str, Any]:
    """Always creates `role='user'`. There is deliberately no parameter to
    set a different role here — promotion only happens via
    `promote_user_role`, which is only ever invoked from the CLI."""
    user_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            User(
                id=user_id,
                email=email.strip().lower(),
                password_hash=password_hash,
                oauth_provider=oauth_provider,
                oauth_subject=oauth_subject,
            )
        )
    return get_user(user_id)


def get_user(user_id: str) -> dict[str, Any]:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            raise KeyError(user_id)
        return _user_dict(user)


def get_user_password_hash(user_id: str) -> str | None:
    """Separate accessor so `_user_dict`/`get_user` never leaks the hash into
    API responses by accident."""
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            raise KeyError(user_id)
        return user.password_hash


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.execute(select(User.id).where(func.lower(User.email) == email.strip().lower())).first()
    return get_user(row[0]) if row else None


def get_user_credentials_by_email(email: str) -> tuple[dict[str, Any], str | None] | None:
    """Login needs the password hash in the same lookup as the public user
    dict, without a second round trip or leaking the hash through
    `get_user_by_email`."""
    with session_scope() as session:
        row = session.execute(select(User).where(func.lower(User.email) == email.strip().lower())).first()
        if row is None:
            return None
        user = row[0]
        return _user_dict(user), user.password_hash


def get_user_by_oauth(provider: str, subject: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.execute(
            select(User.id).where(User.oauth_provider == provider, User.oauth_subject == subject)
        ).first()
    return get_user(row[0]) if row else None


def link_oauth_identity(user_id: str, provider: str, subject: str) -> dict[str, Any]:
    """Attaches a Google identity to an existing password account with a
    matching, verified email — 'same person, two ways to log in', per the
    Phase 1 spec."""
    with session_scope() as session:
        result = session.execute(
            update(User)
            .where(User.id == user_id)
            .values(oauth_provider=provider, oauth_subject=subject, updated_at=datetime.now(UTC))
        )
        if result.rowcount == 0:
            raise KeyError(user_id)
    return get_user(user_id)


def promote_user_role(email: str, role: str) -> dict[str, Any]:
    """The *only* path by which a user ever becomes 'org_admin' or
    'platform_admin' — invoked exclusively by the `promote-admin` CLI
    command, never reachable over HTTP."""
    if role not in ("user", "org_admin", "platform_admin"):
        raise ValueError(f"Invalid role: {role}")
    user = get_user_by_email(email)
    if user is None:
        raise KeyError(email)
    with session_scope() as session:
        session.execute(
            update(User).where(User.id == user["id"]).values(role=role, updated_at=datetime.now(UTC))
        )
    return get_user(user["id"])


def store_refresh_token(user_id: str, token_hash: str, expires_at: datetime) -> str:
    token_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(RefreshToken(id=token_id, user_id=user_id, token_hash=token_hash, expires_at=expires_at))
    return token_id


def get_active_refresh_token(token_hash: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(UTC),
            )
        ).first()
        if row is None:
            return None
        token = row[0]
        return {"id": token.id, "user_id": token.user_id, "expires_at": _iso(token.expires_at)}


def revoke_refresh_token(token_hash: str) -> None:
    with session_scope() as session:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )


def revoke_all_refresh_tokens_for_user(user_id: str) -> int:
    with session_scope() as session:
        result = session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    return int(result.rowcount)


# --- Profile claim tokens ----------------------------------------------------


def create_claim_token(profile_id: str) -> str:
    """Generates a one-time link an operator hands to the real owner of a
    pre-existing/legacy profile. Raises if that profile is already owned or
    already has a live (unexpired, unclaimed) token — matches the DB's
    `profile_claim_tokens.profile_id UNIQUE` constraint, checked here first
    for a clean error message instead of a raw IntegrityError."""
    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise KeyError(profile_id)
        if profile.user_id is not None:
            raise ValueError("This profile is already claimed by an account")
        existing = session.execute(
            select(ProfileClaimToken).where(ProfileClaimToken.profile_id == profile_id)
        ).first()
        if existing is not None:
            session.execute(sa_delete(ProfileClaimToken).where(ProfileClaimToken.profile_id == profile_id))
        raw_token = secrets.token_urlsafe(32)
        session.add(
            ProfileClaimToken(
                id=str(uuid.uuid4()),
                profile_id=profile_id,
                token=raw_token,
                expires_at=datetime.now(UTC) + timedelta(days=CLAIM_TOKEN_EXPIRE_DAYS),
            )
        )
    return raw_token


def claim_profile(token: str, user_id: str) -> dict[str, Any]:
    """Links a pre-existing profile to the calling (already-registered,
    already-logged-in) user's account. Never creates an account — only ever
    connects one that already exists to a profile."""
    with session_scope() as session:
        claim = session.execute(select(ProfileClaimToken).where(ProfileClaimToken.token == token)).first()
        if claim is None:
            raise KeyError("Invalid claim token")
        claim = claim[0]
        if claim.claimed_at is not None:
            raise ValueError("This claim token has already been used")
        if claim.expires_at < datetime.now(UTC):
            raise ValueError("This claim token has expired")
        existing_owner = session.execute(select(Profile.user_id).where(Profile.id == claim.profile_id)).scalar_one()
        if existing_owner is not None:
            raise ValueError("This profile has already been claimed")
        already_owns = session.execute(select(Profile.id).where(Profile.user_id == user_id)).first()
        if already_owns is not None:
            raise ValueError("Your account is already linked to a profile")
        session.execute(
            update(Profile).where(Profile.id == claim.profile_id).values(user_id=user_id, updated_at=datetime.now(UTC))
        )
        claim.claimed_by_user_id = user_id
        claim.claimed_at = datetime.now(UTC)
        profile_id = claim.profile_id
    return get_profile(profile_id)


# --- Phase 2: automatic merge audit trail + revert ---------------------------


def _merge_event_dict(event: MergeEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "source_label": event.source_label,
        "source_user_id": event.source_user_id,
        "target_profile_id": event.target_profile_id,
        "similarity_score": event.similarity_score,
        "method": event.method,
        "session_ids_moved": event.session_ids_moved,
        "status": event.status,
        "created_at": _iso(event.created_at),
        "reverted_at": _iso(event.reverted_at),
    }


def merge_profiles_with_tracking(
    source_label: str, target_label: str, similarity_score: float, method: str
) -> dict[str, Any]:
    """Same effect as `merge_profiles`, but first snapshots which sessions
    belonged to the source profile and records a `MergeEvent`, so the merge
    can later be undone with `revert_merge_event` — this is what makes
    "no human approves a merge before it runs" an acceptable default instead
    of a risk: nothing is approved beforehand, but everything is undoable
    afterward.
    """
    source = get_profile_by_label(source_label)
    target_before = get_profile_by_label(target_label)
    with session_scope() as session:
        session_ids = [
            row[0] for row in session.execute(select(SessionRow.id).where(SessionRow.profile_id == source["id"]))
        ]
    merge_profiles(source_label, target_label)
    with session_scope() as session:
        event = MergeEvent(
            id=str(uuid.uuid4()),
            source_label=source["label"],
            source_user_id=source["user_id"],
            target_profile_id=target_before["id"],
            similarity_score=similarity_score,
            method=method,
            session_ids_moved=session_ids,
        )
        session.add(event)
        event_id = event.id
    return get_merge_event(event_id)


def get_merge_event(event_id: str) -> dict[str, Any]:
    with session_scope() as session:
        event = session.get(MergeEvent, event_id)
        if event is None:
            raise KeyError(event_id)
        return _merge_event_dict(event)


def list_merge_events() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(select(MergeEvent).order_by(MergeEvent.created_at.desc())).scalars().all()
        return [_merge_event_dict(row) for row in rows]


def revert_merge_event(event_id: str) -> dict[str, Any]:
    """Recreates the source profile (same label, same owning user if any)
    and moves its originally-merged sessions back off the target profile.
    Cannot undo any *new* sessions the target accumulated after the merge —
    only the ones captured in `session_ids_moved` at merge time move back."""
    with session_scope() as session:
        event = session.get(MergeEvent, event_id)
        if event is None:
            raise KeyError(event_id)
        if event.status == "reverted":
            raise ValueError("This merge has already been reverted")
        restored_id = str(uuid.uuid4())
        try:
            session.add(
                Profile(id=restored_id, label=event.source_label, user_id=event.source_user_id)
            )
            session.flush()
        except IntegrityError as error:
            raise ValueError(
                "Cannot revert: the original label or user is no longer available "
                "(likely reused since the merge happened)"
            ) from error
        if event.session_ids_moved:
            session.execute(
                update(SessionRow)
                .where(SessionRow.id.in_(event.session_ids_moved))
                .values(profile_id=restored_id)
            )
        event.status = "reverted"
        event.reverted_at = datetime.now(UTC)
    return get_merge_event(event_id)


# --- Phase 3: model version registry ----------------------------------------


def _model_version_dict(row: ModelVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "artifact_uri": row.artifact_uri,
        "config_fingerprint": row.config_fingerprint,
        "dataset_fingerprint": row.dataset_fingerprint,
        "metrics": row.metrics,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "promoted_at": _iso(row.promoted_at),
    }


def create_model_version(
    kind: str,
    artifact_uri: str | None,
    metrics: dict[str, Any] | None,
    status: str = "candidate",
    config_fingerprint: str | None = None,
    dataset_fingerprint: str | None = None,
) -> dict[str, Any]:
    version_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            ModelVersion(
                id=version_id, kind=kind, artifact_uri=artifact_uri, metrics=metrics, status=status,
                config_fingerprint=config_fingerprint, dataset_fingerprint=dataset_fingerprint,
                promoted_at=datetime.now(UTC) if status == "active" else None,
            )
        )
    return get_model_version(version_id)


def get_model_version(version_id: str) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(ModelVersion, version_id)
        if row is None:
            raise KeyError(version_id)
        return _model_version_dict(row)


def get_active_model_version(kind: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.execute(
            select(ModelVersion)
            .where(ModelVersion.kind == kind, ModelVersion.status == "active")
            .order_by(ModelVersion.promoted_at.desc())
        ).scalars().first()
        return _model_version_dict(row) if row else None


def promote_model_version(version_id: str) -> dict[str, Any]:
    """Marks `version_id` active and retires any other active version of the
    same kind — there is at most one active version per model kind."""
    with session_scope() as session:
        row = session.get(ModelVersion, version_id)
        if row is None:
            raise KeyError(version_id)
        session.execute(
            update(ModelVersion)
            .where(ModelVersion.kind == row.kind, ModelVersion.status == "active")
            .values(status="retired")
        )
        row.status = "active"
        row.promoted_at = datetime.now(UTC)
    return get_model_version(version_id)


def list_model_versions(kind: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = select(ModelVersion).order_by(ModelVersion.created_at.desc())
        if kind is not None:
            query = query.where(ModelVersion.kind == kind)
        return [_model_version_dict(row) for row in session.execute(query).scalars().all()]


# --- Phase 4: security alerts ------------------------------------------------


def _security_alert_dict(row: SecurityAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "profile_id": row.profile_id,
        "kind": row.kind,
        "severity": row.severity,
        "details": row.details,
        "status": row.status,
        "created_at": _iso(row.created_at),
    }


def create_security_alert(
    kind: str, severity: str, details: dict[str, Any], profile_id: str | None = None
) -> dict[str, Any]:
    alert_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            SecurityAlert(id=alert_id, profile_id=profile_id, kind=kind, severity=severity, details=details)
        )
    return get_security_alert(alert_id)


def get_security_alert(alert_id: str) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(SecurityAlert, alert_id)
        if row is None:
            raise KeyError(alert_id)
        return _security_alert_dict(row)


def list_security_alerts(statuses: tuple[str, ...] = ("open",)) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = (
            select(SecurityAlert)
            .where(SecurityAlert.status.in_(statuses))
            .order_by(SecurityAlert.created_at.desc())
        )
        return [_security_alert_dict(row) for row in session.execute(query).scalars().all()]


def update_security_alert_status(alert_id: str, status: str) -> dict[str, Any]:
    if status not in ("open", "ack", "dismissed"):
        raise ValueError(f"Invalid status: {status}")
    with session_scope() as session:
        result = session.execute(
            update(SecurityAlert).where(SecurityAlert.id == alert_id).values(status=status)
        )
        if result.rowcount == 0:
            raise KeyError(alert_id)
    return get_security_alert(alert_id)
