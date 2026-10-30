"""delegations between members of the same workspace, with a change log

Revision ID: 0027
Revises: 0026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delegations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("deliverable", sa.Text(), nullable=False),
        sa.Column("acceptance", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("materials", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="requested", nullable=False),
        sa.Column("proposal", postgresql.JSONB()),
        sa.Column("submission", postgresql.JSONB()),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_delegations_tenant_status", "delegations", ["tenant_id", "status"])
    op.create_index("ix_delegations_requester_id", "delegations", ["requester_id"])
    op.create_index("ix_delegations_assignee_id", "delegations", ["assignee_id"])
    op.create_table(
        "delegation_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("delegation_id", sa.BigInteger(), sa.ForeignKey("delegations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_delegation_events_delegation_id", "delegation_events", ["delegation_id"])


def downgrade() -> None:
    op.drop_table("delegation_events")
    op.drop_table("delegations")
