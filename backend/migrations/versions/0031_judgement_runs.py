"""judgement runs: every background model call (input, output, prompt version, model, latency, error) for accuracy and replay

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judgement_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(48), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("subject", sa.String(200)),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("model", sa.String(100)),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("seconds", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_judgement_runs_name_created", "judgement_runs", ["name", "created_at"])
    op.create_index("ix_judgement_runs_user_id", "judgement_runs", ["user_id"])
    op.create_index("ix_judgement_runs_subject", "judgement_runs", ["subject"])


def downgrade() -> None:
    op.drop_table("judgement_runs")
