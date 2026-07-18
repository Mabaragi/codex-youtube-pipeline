"""create the dedicated public catalog projection schema

Revision ID: 20260718_catalog_0001
Revises: None
Create Date: 2026-07-18 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_catalog_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_COLUMNS = (
    sa.Column("profile_key", sa.String(length=128), nullable=False),
    sa.Column("publish_mode", sa.String(length=32), nullable=False),
    sa.Column("environment", sa.String(length=64), nullable=False),
    sa.Column("video_id", sa.BigInteger(), nullable=False),
    sa.Column("variant", sa.String(length=64), nullable=False),
)
_SCOPE_NAMES = ("profile_key", "publish_mode", "environment", "video_id", "variant")
_VIDEO_TARGETS = tuple(f"published_videos.{name}" for name in _SCOPE_NAMES)


def upgrade() -> None:
    op.create_table(
        "published_videos",
        *_scope_columns(),
        sa.Column("youtube_video_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("streamer_id", sa.String(length=128), nullable=True),
        sa.Column("streamer_name", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_name", sa.Text(), nullable=True),
        sa.Column("channel_handle", sa.String(length=255), nullable=True),
        sa.Column("youtube_channel_id", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.String(length=64), nullable=True),
        sa.Column("duration_text", sa.String(length=64), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("is_embeddable", sa.Boolean(), nullable=True),
        sa.Column("display_title", sa.Text(), nullable=True),
        sa.Column("display_summary", sa.Text(), nullable=True),
        sa.Column("main_topics", sa.JSON(), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.Column("micro_event_count", sa.Integer(), nullable=False),
        sa.Column("topic_cluster_count", sa.Integer(), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("timeline_version", sa.String(length=64), nullable=False),
        sa.Column("timeline_url", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("projection_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint(*_SCOPE_NAMES),
    )
    op.create_index(
        "ix_published_videos_profile_environment_updated",
        "published_videos",
        ["profile_key", "publish_mode", "environment", "updated_at"],
    )
    op.create_index(
        "ix_published_videos_youtube_video_id",
        "published_videos",
        ["youtube_video_id"],
    )

    op.create_table(
        "published_timeline_blocks",
        *_scope_columns(),
        sa.Column("block_id", sa.String(length=128), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("display_title", sa.Text(), nullable=True),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(_SCOPE_NAMES, _VIDEO_TARGETS, ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(*_SCOPE_NAMES, "block_id"),
    )
    op.create_index(
        "ix_published_timeline_blocks_order",
        "published_timeline_blocks",
        [*_SCOPE_NAMES, "block_index"],
    )

    op.create_table(
        "published_timeline_episodes",
        *_scope_columns(),
        sa.Column("episode_id", sa.String(length=128), nullable=False),
        sa.Column("block_id", sa.String(length=128), nullable=False),
        sa.Column("episode_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("display_title", sa.Text(), nullable=True),
        sa.Column("program_mode", sa.String(length=64), nullable=False),
        sa.Column("content_kind", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=64), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("viewer_tags", sa.JSON(), nullable=False),
        sa.Column("micro_event_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(_SCOPE_NAMES, _VIDEO_TARGETS, ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(*_SCOPE_NAMES, "episode_id"),
    )
    op.create_index(
        "ix_published_timeline_episodes_order",
        "published_timeline_episodes",
        [*_SCOPE_NAMES, "episode_index"],
    )

    op.create_table(
        "published_timeline_micro_events",
        *_scope_columns(),
        sa.Column("micro_event_id", sa.String(length=128), nullable=False),
        sa.Column("episode_id", sa.String(length=128), nullable=False),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("program_mode", sa.String(length=64), nullable=False),
        sa.Column("content_kind", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(_SCOPE_NAMES, _VIDEO_TARGETS, ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(*_SCOPE_NAMES, "micro_event_id"),
    )
    op.create_index(
        "ix_published_timeline_micro_events_order",
        "published_timeline_micro_events",
        [*_SCOPE_NAMES, "episode_id", "event_index"],
    )

    op.create_table(
        "published_timeline_topic_clusters",
        *_scope_columns(),
        sa.Column("topic_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=True),
        sa.Column("episode_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(_SCOPE_NAMES, _VIDEO_TARGETS, ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(*_SCOPE_NAMES, "topic_id"),
    )


def downgrade() -> None:
    op.drop_table("published_timeline_topic_clusters")
    op.drop_index(
        "ix_published_timeline_micro_events_order",
        table_name="published_timeline_micro_events",
    )
    op.drop_table("published_timeline_micro_events")
    op.drop_index(
        "ix_published_timeline_episodes_order",
        table_name="published_timeline_episodes",
    )
    op.drop_table("published_timeline_episodes")
    op.drop_index(
        "ix_published_timeline_blocks_order",
        table_name="published_timeline_blocks",
    )
    op.drop_table("published_timeline_blocks")
    op.drop_index("ix_published_videos_youtube_video_id", table_name="published_videos")
    op.drop_index(
        "ix_published_videos_profile_environment_updated",
        table_name="published_videos",
    )
    op.drop_table("published_videos")


def _scope_columns() -> tuple[sa.Column[object], ...]:
    return tuple(column._copy() for column in _SCOPE_COLUMNS)
