"""add unique publication job platform per post

Revision ID: 0002_pub_jobs_post_platform
Revises: 0001_content_hub_core
Create Date: 2026-06-26
"""

from alembic import op


revision = "0002_pub_jobs_post_platform"
down_revision = "0001_content_hub_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_publication_jobs_post_platform",
        "publication_jobs",
        ["post_id", "platform"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_publication_jobs_post_platform",
        "publication_jobs",
        type_="unique",
    )
