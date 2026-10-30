"""workspaces (tenants), login accounts, invitations and per-workspace channel connections; users become workspace members

Revision ID: 0025
Revises: 0024
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

DEFAULT = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # 迁移前的所有用户都归入默认工作区（管理员之后可以改名）
    op.execute(f"INSERT INTO tenants (id, name, slug) VALUES ('{DEFAULT}', '默认工作区', 'default')")
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("users", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"),
                                     server_default=DEFAULT, nullable=False))
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.add_column("users", sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_users_account_id", "users", ["account_id"])
    op.create_unique_constraint("uq_users_tenant_account", "users", ["tenant_id", "account_id"])
    op.add_column("users", sa.Column("role", sa.String(16), server_default="member", nullable=False))
    op.add_column("users", sa.Column("status", sa.String(16), server_default="active", nullable=False))
    op.alter_column("users", "feishu_open_id", nullable=True)
    # 原来的管理员 → admin；最早的那位 → owner（工作区必须至少有一位 owner）
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin")
    op.execute("UPDATE users SET role = 'owner' WHERE id = (SELECT id FROM users WHERE is_admin ORDER BY created_at LIMIT 1)")
    # 已有的业务系统接入都属于默认工作区
    op.add_column("integrations", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                                            server_default=DEFAULT, nullable=False))
    op.create_table(
        "tenant_invitations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_invitations_tenant_id", "tenant_invitations", ["tenant_id"])
    op.create_table(
        "tenant_connections",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("secrets_enc", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="unverified", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_tenant_connection"),
    )


def downgrade() -> None:
    op.drop_table("tenant_connections")
    op.drop_table("tenant_invitations")
    op.drop_column("integrations", "tenant_id")
    op.execute("DELETE FROM users WHERE feishu_open_id IS NULL")
    op.alter_column("users", "feishu_open_id", nullable=False)
    op.drop_column("users", "status")
    op.drop_column("users", "role")
    op.drop_constraint("uq_users_tenant_account", "users")
    op.drop_index("ix_users_account_id", "users")
    op.drop_column("users", "account_id")
    op.drop_index("ix_users_tenant_id", "users")
    op.drop_column("users", "tenant_id")
    op.drop_table("accounts")
    op.drop_table("tenants")
