"""add post seo fields

Revision ID: 0004_add_post_seo_fields
Revises: 0003_add_post_is_public
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_post_seo_fields"
down_revision = "0003_add_post_is_public"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("slug", sa.String(length=255), nullable=True))
    op.add_column("posts", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column(
        "posts",
        sa.Column("meta_description", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "posts",
        sa.Column("image_alt_text", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_posts_slug_unique", "posts", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_posts_slug_unique", table_name="posts")
    op.drop_column("posts", "image_alt_text")
    op.drop_column("posts", "meta_description")
    op.drop_column("posts", "title")
    op.drop_column("posts", "slug")
