"""automations: task grants, auto actions and undo

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19 16:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('grants', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('pending_actions', sa.Column('scheduled_task_id', sa.BigInteger(), nullable=True))
    op.add_column('pending_actions', sa.Column('auto', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('pending_actions', sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('pending_actions_scheduled_task_id_fkey', 'pending_actions', 'scheduled_tasks',
                          ['scheduled_task_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_pending_actions_user_auto', 'pending_actions', ['user_id', 'auto'])


def downgrade() -> None:
    op.drop_index('ix_pending_actions_user_auto', table_name='pending_actions')
    op.drop_constraint('pending_actions_scheduled_task_id_fkey', 'pending_actions', type_='foreignkey')
    op.drop_column('pending_actions', 'undone_at')
    op.drop_column('pending_actions', 'auto')
    op.drop_column('pending_actions', 'scheduled_task_id')
    op.drop_column('scheduled_tasks', 'grants')
