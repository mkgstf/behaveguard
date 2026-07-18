from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..config import EMBEDDING_DIM


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    """Optional tenancy grouping. A solo user has `org_id = NULL` on their
    `users` row; org-scoped features become meaningful once real team
    accounts exist. Not required for Phase 1's core auth flow."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan: Mapped[str] = mapped_column(String(40), nullable=False, default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class User(Base):
    """A real login. Always created via self-service /auth/register or
    /auth/google/callback — there is deliberately no admin-creates-user path.
    `role` starts at 'user' for every account; promotion to
    'org_admin'/'platform_admin' happens only via the `promote-admin` CLI
    command, run directly against the database, never over HTTP."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # NULL for OAuth-only accounts (no password ever set).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    oauth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        CheckConstraint("role IN ('user','org_admin','platform_admin')", name="ck_users_role"),
        CheckConstraint("status IN ('active','suspended','deleted')", name="ck_users_status"),
        # Case-insensitive email uniqueness + the (provider, subject) uniqueness
        # for linked OAuth identities are created as indexes in the Alembic
        # migration, same pattern as `profiles.label` in Phase 0.
    )


class RefreshToken(Base):
    """Opaque, rotated-on-use refresh tokens. Stored hashed — never the raw
    token — so a database leak alone can't be used to mint sessions."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (Index("idx_refresh_tokens_user", "user_id"),)


class ProfileClaimToken(Base):
    """One-time link an operator generates (via the `generate-claim-token`
    CLI command) to let the real owner of a pre-existing/legacy profile
    connect it to their own self-registered account. The account itself is
    always created by the person, through the normal register/Google flow —
    this table only ever authorizes the *link*, not the account."""

    __tablename__ = "profile_claim_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Profile(Base):
    """A biometric identity, now optionally owned by a real logged-in user.
    `user_id` is nullable so Phase-0-era profiles (created by the XLSX
    importer, with no owner) remain valid — they're claimable via
    `ProfileClaimToken` rather than requiring a breaking migration."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )

    # Case-insensitive uniqueness on `label` (equivalent to SQLite's
    # `UNIQUE ... COLLATE NOCASE`) is created as a functional index
    # (`lower(label)`) directly in the Alembic migration rather than here,
    # since a same-class declarative `Index` can't cleanly reference
    # `func.lower(label)` before the class exists.
    # `user_id UNIQUE` enforces the Phase 1 "one profile per user" rule at
    # the database level, not just in application code.


class MergeEvent(Base):
    """Audit trail for an automatic profile merge — replaces the manual
    `merge-profiles` CLI as the primary path (that command still exists for
    one-off manual use, but the scan in `merging.py` is what runs normally).
    No human approves a merge before it executes; this table is what makes
    it reversible instead, via `session_ids_moved` + `revert_merge_event`."""

    __tablename__ = "merge_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    source_label: Mapped[str] = mapped_column(String(80), nullable=False)
    source_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    target_profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    session_ids_moved: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('applied','reverted')", name="ck_merge_events_status"),
    )


class Session(Base):
    """One recorded behavioral session: raw payload + derived features.

    `payload`/`features` stay inline JSONB in Phase 0 for parity with the
    SQLite prototype. Moving the raw payload out to S3/GCS (leaving only a
    `raw_payload_uri` pointer here) is a later-phase change, not a Phase 0
    concern.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    # Kept as free-form text (not a parsed timestamp) because it originates
    # from client-supplied payloads and isn't guaranteed to be strict ISO-8601.
    collected_at: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    profile: Mapped["Profile"] = relationship(back_populates="sessions")

    __table_args__ = (Index("idx_sessions_profile", "profile_id"),)


class VerificationEvent(Base):
    """Audit log of every 1:1/1:N attempt (unchanged from v1's semantics)."""

    __tablename__ = "verification_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    claimed_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class ReviewSample(Base):
    """The v1 quarantine queue. Kept as-is in Phase 0 (unused logic is not
    being touched yet); it is removed/replaced by the direct-enroll +
    audit-log flow in Phase 2."""

    __tablename__ = "review_samples"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    verification_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("verification_events.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    claimed_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    predicted_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    candidate_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    feedback_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    true_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="awaiting_feedback")
    promoted_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_feedback','pending','approved','rejected')",
            name="ck_review_samples_status",
        ),
        Index("idx_review_samples_status", "status", "created_at"),
    )


class ModelVersion(Base):
    """Model registry row. Not wired into modeling.py's scoring path yet —
    scaffolded now so Embedding/ProfileTemplate have somewhere to point, and
    so the retraining-pipeline phase has a table to write to."""

    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('candidate','active','retired')", name="ck_model_versions_status"),
    )


class Embedding(Base):
    """Per-session embedding vector, indexed for ANN search. Not populated by
    the scoring path yet (that wiring is a later phase) — table exists now so
    the schema is stable and future migrations don't need to add pgvector
    columns after the fact."""

    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    model_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    modality: Mapped[str] = mapped_column(String(20), nullable=False, default="fused")
    vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class ProfileTemplate(Base):
    """Versioned enrollment template (centroid) per profile per model
    version. Not populated yet — `modeling.py` still writes its centroid into
    the joblib artifact for now; wiring this table in is a later-phase change
    so that 1:N search can become a real pgvector ANN query."""

    __tablename__ = "profile_templates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    model_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    centroid: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    dispersion: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    threshold_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("profile_id", "model_version_id", name="uq_profile_template_version"),)
