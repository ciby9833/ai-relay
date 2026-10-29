"""generated files become background jobs: status, stage, drive upload and its read-back verification

Revision ID: 0024
Revises: 0023
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("generated_files", "content", nullable=True)
    op.alter_column("generated_files", "verified", server_default="{}")
    op.add_column("generated_files", sa.Column("status", sa.String(16), server_default="done", nullable=False))
    op.add_column("generated_files", sa.Column("stage", sa.String(64), nullable=True))
    op.add_column("generated_files", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("generated_files", sa.Column("save_to_drive", postgresql.JSONB(), nullable=True))
    op.add_column("generated_files", sa.Column("drive", postgresql.JSONB(), nullable=True))
    op.add_column("generated_files", sa.Column("notify", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("generated_files", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("generated_files", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_generated_files_status", "generated_files", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generated_files_status", "generated_files")
    for column in ("updated_at", "attempts", "notify", "drive", "save_to_drive", "error", "stage", "status"):
        op.drop_column("generated_files", column)
