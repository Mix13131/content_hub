"""add post public visibility flag

Revision ID: 0003_add_post_is_public
Revises: 0002_pub_jobs_post_platform
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_post_is_public"
down_revision = "0002_pub_jobs_post_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("posts", "is_public")
