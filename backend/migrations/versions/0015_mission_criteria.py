"""mission acceptance criteria and completion check rounds

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("missions", sa.Column("check_rounds", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("missions", "check_rounds")
    op.drop_column("missions", "criteria")
