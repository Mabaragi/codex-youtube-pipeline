"""create videos

Revision ID: 20260616_0007
Revises: 20260616_0006
Create Date: 2026-06-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260616_0007"
down_revision: str | None = "20260616_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("youtube_video_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration", sa.String(length=64), nullable=True),
        sa.Column("privacy_status", sa.String(length=64), nullable=True),
        sa.Column("upload_status", sa.String(length=64), nullable=True),
        sa.Column("live_broadcast_content", sa.String(length=64), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("source_search_api_call_id", sa.Integer(), nullable=True),
        sa.Column("source_details_api_call_id", sa.Integer(), nullable=True),
        sa.Column("source_job_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "view_count IS NULL OR view_count >= 0",
            name=op.f("videos_view_count_non_negative"),
        ),
        sa.CheckConstraint(
            "like_count IS NULL OR like_count >= 0",
            name=op.f("videos_like_count_non_negative"),
        ),
        sa.CheckConstraint(
            "comment_count IS NULL OR comment_count >= 0",
            name=op.f("videos_comment_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_details_api_call_id"],
            ["external_api_calls.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_job_id"],
            ["pipeline_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_search_api_call_id"],
            ["external_api_calls.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("youtube_video_id", name=op.f("uq_videos_youtube_video_id")),
    )
    op.create_index(op.f("ix_videos_channel_id"), "videos", ["channel_id"], unique=False)
    op.create_index(
        "ix_videos_channel_published",
        "videos",
        ["channel_id", "published_at", "id"],
        unique=False,
    )
    op.create_index(op.f("ix_videos_published_at"), "videos", ["published_at"], unique=False)
    op.create_index(
        op.f("ix_videos_source_details_api_call_id"),
        "videos",
        ["source_details_api_call_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_videos_source_job_id"),
        "videos",
        ["source_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_videos_source_search_api_call_id"),
        "videos",
        ["source_search_api_call_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_videos_source_search_api_call_id"), table_name="videos")
    op.drop_index(op.f("ix_videos_source_job_id"), table_name="videos")
    op.drop_index(op.f("ix_videos_source_details_api_call_id"), table_name="videos")
    op.drop_index(op.f("ix_videos_published_at"), table_name="videos")
    op.drop_index("ix_videos_channel_published", table_name="videos")
    op.drop_index(op.f("ix_videos_channel_id"), table_name="videos")
    op.drop_table("videos")
