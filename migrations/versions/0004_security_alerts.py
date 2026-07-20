"""Phase 4: adds security_alerts (replay/far-spike/brute-force signals).

Revision ID: 0004_security_alerts
Revises: 0003_merge_events
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_security_alerts"
down_revision = "0003_merge_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="low"),
        sa.Column("details", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('replay_suspected','far_spike','brute_force')", name="ck_security_alerts_kind"
        ),
        sa.CheckConstraint("status IN ('open','ack','dismissed')", name="ck_security_alerts_status"),
    )
    op.create_index("idx_security_alerts_status", "security_alerts", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_security_alerts_status", table_name="security_alerts")
    op.drop_table("security_alerts")
