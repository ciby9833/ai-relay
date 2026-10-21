"""Durable quality events and human closure reviews.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("assurance_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mission_id", sa.BigInteger(), sa.ForeignKey("missions.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("detail", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_assurance_events_kind_created", "assurance_events", ["kind", "created_at"])
    op.create_index("ix_assurance_events_mission_id", "assurance_events", ["mission_id"])
    # Marks observability coverage; do not imply old checks were observed.
    op.execute("INSERT INTO assurance_events (user_id, kind, detail) SELECT id, 'coverage_start', '{}'::jsonb FROM users ORDER BY created_at LIMIT 1")


def downgrade():
    op.drop_table("assurance_events")
