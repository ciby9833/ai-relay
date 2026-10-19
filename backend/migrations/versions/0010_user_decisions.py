"""user decisions

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19 14:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_decisions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('subject', sa.String(length=32), nullable=False),
        sa.Column('category', sa.String(length=255), nullable=True),
        sa.Column('decision', sa.String(length=32), nullable=False),
        sa.Column('via', sa.String(length=16), nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=True),
        sa.Column('action_id', sa.BigInteger(), nullable=True),
        sa.Column('seconds_to_decide', sa.Integer(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_decisions_user_created', 'user_decisions', ['user_id', 'created_at'])
    op.create_index('ix_user_decisions_user_category', 'user_decisions', ['user_id', 'subject', 'category'])


def downgrade() -> None:
    op.drop_index('ix_user_decisions_user_category', table_name='user_decisions')
    op.drop_index('ix_user_decisions_user_created', table_name='user_decisions')
    op.drop_table('user_decisions')
