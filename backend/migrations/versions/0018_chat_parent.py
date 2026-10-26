"""chat messages remember which message they reply to

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("parent_message_id", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "parent_message_id")
