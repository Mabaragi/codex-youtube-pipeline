from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from codex_sdk_cli.infra.publication.catalog_database.base import CatalogBase

_PARENT_COLUMNS = ("profile_key", "publish_mode", "environment", "video_id", "variant")
_PARENT_TARGETS = tuple(f"published_videos.{column}" for column in _PARENT_COLUMNS)


class PublishedVideoModel(CatalogBase):
    __tablename__ = "published_videos"
    __table_args__ = (
        PrimaryKeyConstraint(*_PARENT_COLUMNS),
        Index(
            "ix_published_videos_profile_environment_updated",
            "profile_key",
            "publish_mode",
            "environment",
            "updated_at",
        ),
        Index("ix_published_videos_youtube_video_id", "youtube_video_id"),
    )

    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    streamer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    streamer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_embeddable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    display_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False)
    micro_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_cluster_count: Mapped[int] = mapped_column(Integer, nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    timeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    timeline_url: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    projection_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PublishedTimelineBlockModel(CatalogBase):
    __tablename__ = "published_timeline_blocks"
    __table_args__ = (
        PrimaryKeyConstraint(*_PARENT_COLUMNS, "block_id"),
        ForeignKeyConstraint(_PARENT_COLUMNS, _PARENT_TARGETS, ondelete="CASCADE"),
        Index(
            "ix_published_timeline_blocks_order",
            *_PARENT_COLUMNS,
            "block_index",
        ),
    )

    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False)


class PublishedTimelineEpisodeModel(CatalogBase):
    __tablename__ = "published_timeline_episodes"
    __table_args__ = (
        PrimaryKeyConstraint(*_PARENT_COLUMNS, "episode_id"),
        ForeignKeyConstraint(_PARENT_COLUMNS, _PARENT_TARGETS, ondelete="CASCADE"),
        Index(
            "ix_published_timeline_episodes_order",
            *_PARENT_COLUMNS,
            "episode_index",
        ),
    )

    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    episode_id: Mapped[str] = mapped_column(String(128), nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    content_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(64), nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    viewer_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    micro_event_count: Mapped[int] = mapped_column(Integer, nullable=False)


class PublishedTimelineMicroEventModel(CatalogBase):
    __tablename__ = "published_timeline_micro_events"
    __table_args__ = (
        PrimaryKeyConstraint(*_PARENT_COLUMNS, "micro_event_id"),
        ForeignKeyConstraint(_PARENT_COLUMNS, _PARENT_TARGETS, ondelete="CASCADE"),
        Index(
            "ix_published_timeline_micro_events_order",
            *_PARENT_COLUMNS,
            "episode_id",
            "event_index",
        ),
    )

    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    micro_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    episode_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    program_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    content_kind: Mapped[str] = mapped_column(String(64), nullable=False)


class PublishedTimelineTopicClusterModel(CatalogBase):
    __tablename__ = "published_timeline_topic_clusters"
    __table_args__ = (
        PrimaryKeyConstraint(*_PARENT_COLUMNS, "topic_id"),
        ForeignKeyConstraint(_PARENT_COLUMNS, _PARENT_TARGETS, ondelete="CASCADE"),
    )

    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_id: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    display_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
