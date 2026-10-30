"""per-member data sources that don't need Feishu: standard mailbox (IMAP/SMTP) and calendar subscription (ICS)

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_connections",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("secrets_enc", sa.Text()),
        sa.Column("status", sa.String(16), server_default="unverified", nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_connection"),
    )
    op.create_index("ix_user_connections_user_id", "user_connections", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_connections")
