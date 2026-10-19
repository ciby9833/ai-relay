"""private chat messages belong to one user

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('owner_user_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('chat_messages_owner_user_id_fkey', 'chat_messages', 'users', ['owner_user_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_chat_messages_owner', 'chat_messages', ['owner_user_id', 'processed'])


def downgrade() -> None:
    op.drop_index('ix_chat_messages_owner', table_name='chat_messages')
    op.drop_constraint('chat_messages_owner_user_id_fkey', 'chat_messages', type_='foreignkey')
    op.drop_column('chat_messages', 'owner_user_id')
