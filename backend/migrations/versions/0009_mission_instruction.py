"""mission instruction and due time

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('missions', sa.Column('instruction', sa.Text(), nullable=True))
    op.add_column('missions', sa.Column('due_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('missions', 'due_at')
    op.drop_column('missions', 'instruction')
