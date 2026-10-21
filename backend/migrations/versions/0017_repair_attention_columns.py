"""repair: columns added to 0014 after some databases had already applied it

0014 was extended (follow_ups.pushed_at / pushed_importance, attention_rules.status / evidence)
after a development database had already run the first version of it. Alembic never re-runs an
applied revision, so those databases are missing the columns. Add them only where absent —
a no-op on databases that ran the final 0014 (production).

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS pushed_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS pushed_importance VARCHAR(16)")
    op.execute("ALTER TABLE attention_rules ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE attention_rules ADD COLUMN IF NOT EXISTS evidence TEXT")


def downgrade() -> None:
    pass  # 只是补齐 0014 应有的列，回退由 0014 负责
