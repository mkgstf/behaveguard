"""Phase 1: auth. Adds organizations, users, refresh_tokens,
profile_claim_tokens, and a nullable/unique profiles.user_id.

Hand-written for the same reason 0001 was: safest to write explicitly and
review rather than trust autogenerate blindly for a migration this ordering-
sensitive (FKs to a brand-new `users` table).

Revision ID: 0002_auth
Revises: 0001_initial
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_auth"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("plan", sa.String(40), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("oauth_provider", sa.String(20), nullable=True),
        sa.Column("oauth_subject", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','org_admin','platform_admin')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('active','suspended','deleted')", name="ck_users_status"),
    )
    # Case-insensitive email uniqueness, matching the profiles.label pattern.
    op.execute("CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email))")
    # A given Google (or other provider) identity can only ever back one account.
    # Partial index: NULLs (password-only accounts) are never compared for uniqueness.
    op.execute(
        "CREATE UNIQUE INDEX ux_users_oauth_identity ON users (oauth_provider, oauth_subject) "
        "WHERE oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL"
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_refresh_tokens_user", "refresh_tokens", ["user_id"])

    op.create_table(
        "profile_claim_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "claimed_by_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "profiles",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    # One profile per user, enforced at the DB level. A plain UNIQUE
    # constraint (rather than a partial index) works fine here since NULL is
    # never considered equal to NULL in a unique constraint — many profiles
    # can have user_id IS NULL simultaneously.
    op.create_unique_constraint("uq_profiles_user_id", "profiles", ["user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_profiles_user_id", "profiles", type_="unique")
    op.drop_column("profiles", "user_id")
    op.drop_table("profile_claim_tokens")
    op.drop_index("idx_refresh_tokens_user", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.execute("DROP INDEX IF EXISTS ux_users_oauth_identity")
    op.execute("DROP INDEX IF EXISTS ux_users_email_lower")
    op.drop_table("users")
    op.drop_table("organizations")
