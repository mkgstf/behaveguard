"""Phase 2: adds merge_events (the auto-merge audit trail / revert log).

Revision ID: 0003_merge_events
Revises: 0002_auth
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_merge_events"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merge_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("source_label", sa.String(80), nullable=False),
        sa.Column("source_user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "target_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("session_ids_moved", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="applied"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('applied','reverted')", name="ck_merge_events_status"),
    )
    op.create_index("idx_merge_events_target", "merge_events", ["target_profile_id"])


def downgrade() -> None:
    op.drop_index("idx_merge_events_target", table_name="merge_events")
    op.drop_table("merge_events")
