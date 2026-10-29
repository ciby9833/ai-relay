"""feishu cards remember when they were last refreshed, so each item keeps one live card

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feishu_cards", sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_feishu_cards_user_created", "feishu_cards", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feishu_cards_user_created", "feishu_cards")
    op.drop_column("feishu_cards", "refreshed_at")
