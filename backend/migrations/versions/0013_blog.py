"""Database-backed blog documents and media.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blog_posts",
        sa.Column("slug", sa.String(160), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("cover", sa.Text(), nullable=True),
        sa.Column("bundle_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "blog_assets",
        sa.Column("post_slug", sa.String(160), sa.ForeignKey("blog_posts.slug", ondelete="CASCADE"), primary_key=True),
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("blog_assets")
    op.drop_table("blog_posts")
