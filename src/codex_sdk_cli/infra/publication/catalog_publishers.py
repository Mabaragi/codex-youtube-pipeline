from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.domains.archive_publish.ports import ArchivePublicCatalogVideoRow
from codex_sdk_cli.domains.publication.exceptions import PublicationCatalogPublishError
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationCatalogPublisherPort,
    PublicationCatalogReconcilerPort,
    PublicationCatalogRowVerification,
    PublicationCatalogVerifierPort,
    PublicationCatalogVideoKey,
)
from codex_sdk_cli.infra.archive_publish.public_catalog import (
    archive_public_catalog_payload,
)
from codex_sdk_cli.infra.publication.catalog_database.models import (
    PublishedTimelineBlockModel,
    PublishedTimelineEpisodeModel,
    PublishedTimelineMicroEventModel,
    PublishedTimelineTopicClusterModel,
    PublishedVideoModel,
)
from codex_sdk_cli.infra.publication.catalog_database.session import (
    create_catalog_engine,
    create_catalog_session_factory,
)

_PRIMARY_KEY_COLUMNS = (
    "profile_key",
    "publish_mode",
    "environment",
    "video_id",
    "variant",
)


class HttpPublicationCatalogPublisher(PublicationCatalogPublisherPort):
    def __init__(
        self,
        *,
        url: str,
        token: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @override
    async def upsert_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> None:
        del context  # Existing HTTP consumers intentionally receive the unchanged payload.
        headers = {"authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._url,
                    headers=headers,
                    json=archive_public_catalog_payload(row),
                )
        except httpx.HTTPError as exc:
            raise PublicationCatalogPublishError(f"Catalog publish request failed: {exc}") from exc
        if not response.is_success:
            raise PublicationCatalogPublishError(
                f"Catalog publish failed with HTTP {response.status_code}: "
                f"{_response_error_message(response)}"
            )


class SqlPublicationCatalogPublisher(
    PublicationCatalogPublisherPort,
    PublicationCatalogReconcilerPort,
    PublicationCatalogVerifierPort,
):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        owned_engine: AsyncEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._owned_engine = owned_engine

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        echo: bool = False,
    ) -> SqlPublicationCatalogPublisher:
        engine = create_catalog_engine(database_url, echo=echo)
        return cls(
            session_factory=create_catalog_session_factory(engine),
            owned_engine=engine,
        )

    @override
    async def upsert_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                scope = _scope(context, row)
                await _upsert_video(session, scope, row)
                await _replace_timeline_index(session, scope, row)
        except PublicationCatalogPublishError:
            raise
        except Exception as exc:
            raise PublicationCatalogPublishError("SQL catalog transaction failed.") from exc

    @override
    async def verify_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> PublicationCatalogRowVerification:
        try:
            async with self._session_factory() as session:
                return await _verify_video_projection(session, context, row)
        except PublicationCatalogPublishError:
            raise
        except Exception as exc:
            raise PublicationCatalogPublishError("SQL catalog verification failed.") from exc

    @override
    async def reconcile_videos(
        self,
        context: PublicationCatalogContext,
        *,
        environment: str,
        retained: tuple[PublicationCatalogVideoKey, ...],
    ) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                retained_keys = {(item.video_id, item.variant) for item in retained}
                existing = (
                    await session.execute(
                        select(PublishedVideoModel.video_id, PublishedVideoModel.variant).where(
                            PublishedVideoModel.profile_key == context.profile_key,
                            PublishedVideoModel.publish_mode == context.publish_mode,
                            PublishedVideoModel.environment == environment,
                        )
                    )
                ).all()
                for video_id, variant in existing:
                    if (video_id, variant) in retained_keys:
                        continue
                    await _delete_video_projection(
                        session,
                        {
                            "profile_key": context.profile_key,
                            "publish_mode": context.publish_mode,
                            "environment": environment,
                            "video_id": video_id,
                            "variant": variant,
                        },
                    )
        except PublicationCatalogPublishError:
            raise
        except Exception as exc:
            raise PublicationCatalogPublishError("SQL catalog reconciliation failed.") from exc

    async def aclose(self) -> None:
        if self._owned_engine is not None:
            await self._owned_engine.dispose()


async def _upsert_video(
    session: AsyncSession,
    scope: dict[str, object],
    row: ArchivePublicCatalogVideoRow,
) -> None:
    values = {
        **_video_projection_values(scope, row),
        "updated_at": datetime.now(UTC),
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(PublishedVideoModel).values(values)
    elif dialect == "sqlite":
        statement = sqlite_insert(PublishedVideoModel).values(values)
    else:
        raise PublicationCatalogPublishError(f"Unsupported SQL catalog dialect: {dialect}")
    update_values = {
        column: getattr(statement.excluded, column)
        for column in values
        if column not in _PRIMARY_KEY_COLUMNS
    }
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=list(_PRIMARY_KEY_COLUMNS),
            set_=update_values,
        )
    )


def _video_projection_values(
    scope: dict[str, object],
    row: ArchivePublicCatalogVideoRow,
) -> dict[str, object]:
    return {
        **scope,
        "youtube_video_id": row.youtube_video_id,
        "title": row.title,
        "streamer_id": row.streamer_id,
        "streamer_name": row.streamer_name,
        "channel_id": row.channel_id,
        "channel_name": row.channel_name,
        "channel_handle": row.channel_handle,
        "youtube_channel_id": row.youtube_channel_id,
        "published_at": row.published_at,
        "duration_text": row.duration_text,
        "duration_seconds": row.duration_seconds,
        "thumbnail_url": row.thumbnail_url,
        "is_embeddable": row.is_embeddable,
        "display_title": row.display_title,
        "display_summary": row.display_summary,
        "main_topics": row.main_topics,
        "episode_count": row.episode_count,
        "micro_event_count": row.micro_event_count,
        "topic_cluster_count": row.topic_cluster_count,
        "block_count": row.block_count,
        "timeline_version": row.timeline_version,
        "timeline_url": row.timeline_url,
        "artifact_sha256": row.artifact_sha256,
        "artifact_byte_size": row.artifact_byte_size,
        "projection_updated_at": _parse_datetime(row.updated_at),
    }


async def _replace_timeline_index(
    session: AsyncSession,
    scope: dict[str, object],
    row: ArchivePublicCatalogVideoRow,
) -> None:
    child_models = (
        PublishedTimelineMicroEventModel,
        PublishedTimelineTopicClusterModel,
        PublishedTimelineEpisodeModel,
        PublishedTimelineBlockModel,
    )
    for model in child_models:
        await session.execute(delete(model).filter_by(**scope))

    index = row.timeline_index
    if index is None:
        return
    session.add_all(
        [
            PublishedTimelineBlockModel(
                **scope,
                block_id=block.block_id,
                block_index=block.block_index,
                block_type=block.block_type,
                title=block.title,
                display_title=block.display_title,
                start_ms=block.start_ms,
                end_ms=block.end_ms,
                episode_count=block.episode_count,
            )
            for block in index.blocks
        ]
    )
    session.add_all(
        [
            PublishedTimelineEpisodeModel(
                **scope,
                episode_id=episode.episode_id,
                block_id=episode.block_id,
                episode_index=episode.episode_index,
                start_ms=episode.start_ms,
                end_ms=episode.end_ms,
                title=episode.title,
                display_title=episode.display_title,
                program_mode=episode.program_mode,
                content_kind=episode.content_kind,
                visibility=episode.visibility,
                topics=episode.topics,
                viewer_tags=episode.viewer_tags,
                micro_event_count=episode.micro_event_count,
            )
            for episode in index.episodes
        ]
    )
    session.add_all(
        [
            PublishedTimelineMicroEventModel(
                **scope,
                micro_event_id=event.micro_event_id,
                episode_id=event.episode_id,
                event_index=event.event_index,
                start_ms=event.start_ms,
                end_ms=event.end_ms,
                text=event.text,
                program_mode=event.program_mode,
                content_kind=event.content_kind,
            )
            for event in index.micro_events
        ]
    )
    session.add_all(
        [
            PublishedTimelineTopicClusterModel(
                **scope,
                topic_id=topic.topic_id,
                label=topic.label,
                display_label=topic.display_label,
                episode_ids=topic.episode_ids,
            )
            for topic in index.topic_clusters
        ]
    )


async def _delete_video_projection(
    session: AsyncSession,
    scope: dict[str, object],
) -> None:
    for model in (
        PublishedTimelineMicroEventModel,
        PublishedTimelineTopicClusterModel,
        PublishedTimelineEpisodeModel,
        PublishedTimelineBlockModel,
    ):
        await session.execute(delete(model).filter_by(**scope))
    await session.execute(delete(PublishedVideoModel).filter_by(**scope))


async def _verify_video_projection(
    session: AsyncSession,
    context: PublicationCatalogContext,
    row: ArchivePublicCatalogVideoRow,
) -> PublicationCatalogRowVerification:
    scope = _scope(context, row)
    model = await session.scalar(select(PublishedVideoModel).filter_by(**scope))
    if model is None:
        return PublicationCatalogRowVerification(
            exists=False,
            matches=False,
            detail="published_video_missing",
        )
    for column, expected in _video_projection_values(scope, row).items():
        if column == "projection_updated_at":
            continue
        actual = getattr(model, column)
        if actual != expected:
            return PublicationCatalogRowVerification(
                exists=True,
                matches=False,
                detail=f"published_video_{column}_mismatch",
            )
    child_mismatch = await _timeline_child_mismatch(session, scope, row)
    if child_mismatch is not None:
        return PublicationCatalogRowVerification(
            exists=True,
            matches=False,
            detail=child_mismatch,
        )
    return PublicationCatalogRowVerification(exists=True, matches=True)


async def _timeline_child_mismatch(
    session: AsyncSession,
    scope: dict[str, object],
    row: ArchivePublicCatalogVideoRow,
) -> str | None:
    index = row.timeline_index
    expected_blocks = (
        {
            item.block_id: (
                item.block_index,
                item.block_type,
                item.title,
                item.display_title,
                item.start_ms,
                item.end_ms,
                item.episode_count,
            )
            for item in index.blocks
        }
        if index is not None
        else {}
    )
    blocks = (await session.scalars(select(PublishedTimelineBlockModel).filter_by(**scope))).all()
    actual_blocks = {
        item.block_id: (
            item.block_index,
            item.block_type,
            item.title,
            item.display_title,
            item.start_ms,
            item.end_ms,
            item.episode_count,
        )
        for item in blocks
    }
    if actual_blocks != expected_blocks:
        return "published_timeline_blocks_mismatch"

    expected_episodes = (
        {
            item.episode_id: (
                item.block_id,
                item.episode_index,
                item.start_ms,
                item.end_ms,
                item.title,
                item.display_title,
                item.program_mode,
                item.content_kind,
                item.visibility,
                item.topics,
                item.viewer_tags,
                item.micro_event_count,
            )
            for item in index.episodes
        }
        if index is not None
        else {}
    )
    episodes = (
        await session.scalars(select(PublishedTimelineEpisodeModel).filter_by(**scope))
    ).all()
    actual_episodes = {
        item.episode_id: (
            item.block_id,
            item.episode_index,
            item.start_ms,
            item.end_ms,
            item.title,
            item.display_title,
            item.program_mode,
            item.content_kind,
            item.visibility,
            item.topics,
            item.viewer_tags,
            item.micro_event_count,
        )
        for item in episodes
    }
    if actual_episodes != expected_episodes:
        return "published_timeline_episodes_mismatch"

    expected_events = (
        {
            item.micro_event_id: (
                item.episode_id,
                item.event_index,
                item.start_ms,
                item.end_ms,
                item.text,
                item.program_mode,
                item.content_kind,
            )
            for item in index.micro_events
        }
        if index is not None
        else {}
    )
    events = (
        await session.scalars(select(PublishedTimelineMicroEventModel).filter_by(**scope))
    ).all()
    actual_events = {
        item.micro_event_id: (
            item.episode_id,
            item.event_index,
            item.start_ms,
            item.end_ms,
            item.text,
            item.program_mode,
            item.content_kind,
        )
        for item in events
    }
    if actual_events != expected_events:
        return "published_timeline_micro_events_mismatch"

    expected_topics = (
        {
            item.topic_id: (item.label, item.display_label, item.episode_ids)
            for item in index.topic_clusters
        }
        if index is not None
        else {}
    )
    topics = (
        await session.scalars(select(PublishedTimelineTopicClusterModel).filter_by(**scope))
    ).all()
    actual_topics = {
        item.topic_id: (item.label, item.display_label, item.episode_ids) for item in topics
    }
    if actual_topics != expected_topics:
        return "published_timeline_topic_clusters_mismatch"
    return None


def _scope(
    context: PublicationCatalogContext,
    row: ArchivePublicCatalogVideoRow,
) -> dict[str, object]:
    return {
        "profile_key": context.profile_key,
        "publish_mode": context.publish_mode,
        "environment": row.environment,
        "video_id": row.video_id,
        "variant": row.variant,
    }


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationCatalogPublishError(
            "Catalog row updated_at must be an ISO-8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _response_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, Mapping) and isinstance(payload.get("error"), str):
        return payload["error"]
    return str(payload)[:500]
