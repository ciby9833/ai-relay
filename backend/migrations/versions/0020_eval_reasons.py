"""evaluation feedback becomes thumbs up/down with an optional reason and note

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_labels", sa.Column("reason", sa.String(32), nullable=True))
    op.add_column("eval_labels", sa.Column("note", sa.Text(), nullable=True))
    # 旧的三选一（上线不久、通常为空）换成 👍/👎 + 原因
    op.execute("UPDATE eval_labels SET reason = 'wrong_detail', label = 'down' WHERE label = 'state'")
    op.execute("UPDATE eval_labels SET reason = 'not_mine', label = 'down' WHERE label = 'noise'")
    op.execute("UPDATE eval_labels SET label = 'up' WHERE label = 'ok'")


def downgrade() -> None:
    op.drop_column("eval_labels", "note")
    op.drop_column("eval_labels", "reason")
