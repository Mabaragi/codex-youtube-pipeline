from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind

PublicArchiveSort = Literal["latest", "oldest"]


@dataclass(frozen=True, slots=True)
class PublicArchiveScope:
    profile_key: str
    publish_mode: str
    environment: str
    additional_profile_keys: tuple[str, ...] = ()

    @property
    def profile_keys(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.profile_key, *self.additional_profile_keys)))


@dataclass(frozen=True, slots=True)
class PublicArchiveVideoQuery:
    scope: PublicArchiveScope
    sort: PublicArchiveSort = "latest"
    limit: int = 30
    cursor: str | None = None
    query: str | None = None
    streamer_id: str | None = None
    channel_id: int | None = None
    youtube_video_id: str | None = None
    include_stats: bool = False


@dataclass(frozen=True, slots=True)
class PublicArchiveTimelineVariant:
    key: str
    url: str
    version: str


@dataclass(frozen=True, slots=True)
class PublicArchiveTopicMatch:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class PublicArchiveVideo:
    environment: str
    id: int
    youtube_id: str
    title: str
    streamer_id: str | None
    streamer_name: str | None
    channel_id: int | None
    channel_name: str | None
    channel_handle: str | None
    youtube_channel_id: str | None
    published_at: str | None
    duration_text: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    is_embeddable: bool | None
    display_title: str | None
    display_summary: str | None
    main_topics: tuple[str, ...]
    episode_count: int
    event_count: int
    topic_cluster_count: int
    block_count: int
    timeline_variants: tuple[PublicArchiveTimelineVariant, ...]
    timeline_url: str
    updated_at: datetime
    open_count: int = 0
    timeline_load_count: int = 0
    episode_click_count: int = 0
    search_matches: tuple[PublicArchiveTopicMatch, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicArchiveVideoPage:
    items: tuple[PublicArchiveVideo, ...]
    next_cursor: str | None
    total_count: int


@dataclass(frozen=True, slots=True)
class PublicArchiveStreamer:
    id: str | None
    name: str | None
    video_count: int


class PublicArchiveRepositoryPort(Protocol):
    async def list_videos(
        self,
        query: PublicArchiveVideoQuery,
    ) -> PublicArchiveVideoPage: ...

    async def get_video(
        self,
        *,
        scope: PublicArchiveScope,
        identifier: str,
    ) -> PublicArchiveVideo | None: ...

    async def list_streamers(
        self,
        scope: PublicArchiveScope,
    ) -> tuple[PublicArchiveStreamer, ...]: ...

    async def catalog_version(self, scope: PublicArchiveScope) -> str: ...


class ListPublicArchiveVideosUseCase:
    def __init__(self, repository: PublicArchiveRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, query: PublicArchiveVideoQuery) -> PublicArchiveVideoPage:
        return await self._repository.list_videos(query)


class GetPublicArchiveVideoUseCase:
    def __init__(self, repository: PublicArchiveRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        scope: PublicArchiveScope,
        identifier: str,
    ) -> PublicArchiveVideo:
        video = await self._repository.get_video(scope=scope, identifier=identifier)
        if video is None:
            raise ApplicationError(
                code="public_archive_video_not_found",
                message="Archive video not found.",
                kind=ErrorKind.NOT_FOUND,
            )
        return video


class ListPublicArchiveStreamersUseCase:
    def __init__(self, repository: PublicArchiveRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        scope: PublicArchiveScope,
    ) -> tuple[PublicArchiveStreamer, ...]:
        return await self._repository.list_streamers(scope)


class GetPublicArchiveCatalogVersionUseCase:
    def __init__(self, repository: PublicArchiveRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, scope: PublicArchiveScope) -> str:
        return await self._repository.catalog_version(scope)
