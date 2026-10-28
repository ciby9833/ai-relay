"""commitment ledger (shadow) and per-user evaluation labels

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    user = lambda: sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # noqa: E731
    now = lambda name: sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)  # noqa: E731
    op.create_table(
        "ledger_matters",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), user(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("people", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ledger_matters_user_id", "ledger_matters", ["user_id"])
    op.create_table(
        "ledger_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), user(),
        sa.Column("ref", sa.String(160), nullable=False),
        sa.Column("matter_id", sa.BigInteger(), sa.ForeignKey("ledger_matters.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(24), nullable=False), sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("stream", sa.String(255), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False), sa.Column("verdict", sa.String(16), nullable=False),
        now("created_at"),
        sa.UniqueConstraint("user_id", "ref", name="uq_ledger_events_user_ref"),
    )
    op.create_index("ix_ledger_events_matter", "ledger_events", ["matter_id"])
    op.create_table(
        "ledger_commitments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), user(),
        sa.Column("matter_id", sa.BigInteger(), sa.ForeignKey("ledger_matters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner", sa.String(8), nullable=False), sa.Column("party", sa.String(255), nullable=False),
        sa.Column("what", sa.Text(), nullable=False), sa.Column("due", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ledger_commitments_user_id", "ledger_commitments", ["user_id"])
    op.create_index("ix_ledger_commitments_matter_id", "ledger_commitments", ["matter_id"])
    op.create_table(
        "eval_labels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), user(),
        sa.Column("target", sa.String(16), nullable=False), sa.Column("target_key", sa.String(600), nullable=False),
        sa.Column("label", sa.String(16), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        now("created_at"), now("updated_at"),
        sa.UniqueConstraint("user_id", "target", "target_key", name="uq_eval_labels_target"),
    )
    op.create_index("ix_eval_labels_user_id", "eval_labels", ["user_id"])
    op.create_table(
        "eval_feedback",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), user(),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("text", sa.Text(), nullable=False), now("created_at"),
    )
    op.create_index("ix_eval_feedback_user_id", "eval_feedback", ["user_id"])


def downgrade() -> None:
    for table in ("eval_feedback", "eval_labels", "ledger_commitments", "ledger_events", "ledger_matters"):
        op.drop_table(table)
