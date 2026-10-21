"""attention tiers: rules and per-item attention

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attention_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_attention_rules_user_id", "attention_rules", ["user_id"])
    op.add_column("follow_ups", sa.Column("attention", sa.String(16), nullable=True))
    op.add_column("follow_ups", sa.Column("attention_note", sa.Text(), nullable=True))
    op.add_column("follow_ups", sa.Column("facets", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False))
    op.add_column("follow_ups", sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("follow_ups", sa.Column("pushed_importance", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("follow_ups", "pushed_importance")
    op.drop_column("follow_ups", "pushed_at")
    op.drop_column("follow_ups", "facets")
    op.drop_column("follow_ups", "attention_note")
    op.drop_column("follow_ups", "attention")
    op.drop_index("ix_attention_rules_user_id", table_name="attention_rules")
    op.drop_table("attention_rules")
