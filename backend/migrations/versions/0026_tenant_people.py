"""per-workspace contact directory, Feishu identities and stored chat messages

The same Feishu person can show up in two workspaces (each workspace has its own app),
so people and users.feishu_open_id are unique per workspace, not globally.
A message in a cross-company external group is stored once per workspace that received it.

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

DEFAULT = "00000000-0000-0000-0000-000000000001"

# 不依赖约束的自动命名：按列找出某张表某一列上的单列唯一约束并删掉
def _drop_single_unique(table: str, column: str) -> None:
    op.execute(f"""
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT con.conname FROM pg_constraint con
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
    WHERE con.conrelid = '{table}'::regclass AND con.contype = 'u'
      AND array_length(con.conkey, 1) = 1 AND a.attname = '{column}'
  LOOP
    EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
""")


def upgrade() -> None:
    op.add_column("people", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=DEFAULT))
    op.create_foreign_key("fk_people_tenant", "people", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.execute("ALTER TABLE people DROP CONSTRAINT IF EXISTS people_pkey")
    op.create_primary_key("people_pkey", "people", ["tenant_id", "open_id"])

    _drop_single_unique("users", "feishu_open_id")
    op.create_unique_constraint("uq_users_tenant_open_id", "users", ["tenant_id", "feishu_open_id"])
    op.create_index("ix_users_feishu_open_id", "users", ["feishu_open_id"])

    op.add_column("chat_messages", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=DEFAULT))
    op.create_foreign_key("fk_chat_messages_tenant", "chat_messages", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    _drop_single_unique("chat_messages", "message_id")
    op.create_unique_constraint("uq_chat_messages_tenant_message", "chat_messages", ["tenant_id", "message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_chat_messages_tenant_message", "chat_messages", type_="unique")
    op.execute(f"DELETE FROM chat_messages WHERE tenant_id <> '{DEFAULT}'")
    op.create_unique_constraint("chat_messages_message_id_key", "chat_messages", ["message_id"])
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_constraint("fk_chat_messages_tenant", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "tenant_id")
    op.drop_index("ix_users_feishu_open_id", table_name="users")
    op.drop_constraint("uq_users_tenant_open_id", "users", type_="unique")
    op.execute(f"DELETE FROM users WHERE tenant_id <> '{DEFAULT}' AND feishu_open_id IS NOT NULL")
    op.create_unique_constraint("users_feishu_open_id_key", "users", ["feishu_open_id"])
    op.execute(f"DELETE FROM people WHERE tenant_id <> '{DEFAULT}'")
    op.drop_constraint("people_pkey", "people", type_="primary")
    op.create_primary_key("people_pkey", "people", ["open_id"])
    op.drop_constraint("fk_people_tenant", "people", type_="foreignkey")
    op.drop_column("people", "tenant_id")
