"""content hub core tables

Revision ID: 0001_content_hub_core
Revises:
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_content_hub_core"
down_revision = None
branch_labels = None
depends_on = None


jsonb_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_post_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_media_group_id", sa.String(length=255), nullable=True),
        sa.Column("telegram_message_ids", jsonb_type, nullable=False),
        sa.Column("telegram_url", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("telegram_posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "post_type",
            sa.Enum("text", "photo", "video", "carousel", "mixed", name="post_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("video_count", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("telegram_channel", name="post_source", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "saving_media",
                "saved",
                "queued",
                "partially_published",
                "published",
                "error",
                name="post_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "website_status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "instagram_status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "facebook_status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "vk_status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "story_status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id", "telegram_media_group_id", name="uq_posts_telegram_media_group"),
        sa.UniqueConstraint("telegram_chat_id", "telegram_post_id", name="uq_posts_telegram_chat_post"),
    )

    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("photo", "video", name="media_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("telegram_file_id", sa.Text(), nullable=False),
        sa.Column("telegram_file_unique_id", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_media_post_id"), "media", ["post_id"], unique=False)

    op.create_table(
        "publication_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "website",
                "instagram",
                "facebook",
                "vk",
                "telegram_story",
                "whatsapp",
                name="publication_platform",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("Waiting", "Publishing", "Success", "Error", "Retry", name="platform_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_api_response", jsonb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_publication_jobs_platform"), "publication_jobs", ["platform"], unique=False)
    op.create_index(op.f("ix_publication_jobs_post_id"), "publication_jobs", ["post_id"], unique=False)
    op.create_index(op.f("ix_publication_jobs_status"), "publication_jobs", ["status"], unique=False)

    op.create_table(
        "publication_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column(
            "level",
            sa.Enum("info", "warning", "error", name="publication_log_level", native_enum=False),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("api_response", jsonb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["publication_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_publication_logs_job_id"), "publication_logs", ["job_id"], unique=False)
    op.create_index(op.f("ix_publication_logs_post_id"), "publication_logs", ["post_id"], unique=False)
    op.create_index(op.f("ix_publication_logs_service"), "publication_logs", ["service"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_publication_logs_service"), table_name="publication_logs")
    op.drop_index(op.f("ix_publication_logs_post_id"), table_name="publication_logs")
    op.drop_index(op.f("ix_publication_logs_job_id"), table_name="publication_logs")
    op.drop_table("publication_logs")
    op.drop_index(op.f("ix_publication_jobs_status"), table_name="publication_jobs")
    op.drop_index(op.f("ix_publication_jobs_post_id"), table_name="publication_jobs")
    op.drop_index(op.f("ix_publication_jobs_platform"), table_name="publication_jobs")
    op.drop_table("publication_jobs")
    op.drop_index(op.f("ix_media_post_id"), table_name="media")
    op.drop_table("media")
    op.drop_table("posts")
