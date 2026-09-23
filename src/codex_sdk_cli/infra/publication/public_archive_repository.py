from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from codex_sdk_cli.application.public_archive.queries import (
    PublicArchiveRepositoryPort,
    PublicArchiveScope,
    PublicArchiveStreamer,
    PublicArchiveTimelineVariant,
    PublicArchiveTopicMatch,
    PublicArchiveVideo,
    PublicArchiveVideoPage,
    PublicArchiveVideoQuery,
)
from codex_sdk_cli.infra.publication.catalog_database.models import (
    PublishedTimelineTopicClusterModel,
    PublishedVideoModel,
)

_SEARCH_SEPARATOR = re.compile(r"[^\w\s]", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class _Cursor:
    published_at: str
    video_id: int


class SqlAlchemyPublicArchiveRepository(PublicArchiveRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_videos(
        self,
        query: PublicArchiveVideoQuery,
    ) -> PublicArchiveVideoPage:
        predicates = list(_scope_predicates(query.scope))
        predicates.append(PublishedVideoModel.is_embeddable.is_not(False))
        if query.youtube_video_id is not None:
            predicates.append(PublishedVideoModel.youtube_video_id == query.youtube_video_id)
        if query.streamer_id is not None:
            predicates.append(PublishedVideoModel.streamer_id == query.streamer_id)
        if query.channel_id is not None:
            predicates.append(PublishedVideoModel.channel_id == query.channel_id)

        search_tokens = _search_tokens(query.query)
        predicates.extend(_search_predicate(query.scope, token) for token in search_tokens)
        count_statement = select(func.count()).select_from(PublishedVideoModel).where(*predicates)
        total_count = await self._session.scalar(count_statement) or 0

        page_predicates = list(predicates)
        cursor = _decode_cursor(query.cursor)
        if cursor is not None:
            published_at = func.coalesce(PublishedVideoModel.published_at, "")
            if query.sort == "latest":
                page_predicates.append(
                    or_(
                        published_at < cursor.published_at,
                        and_(
                            published_at == cursor.published_at,
                            PublishedVideoModel.video_id < cursor.video_id,
                        ),
                    )
                )
            else:
                page_predicates.append(
                    or_(
                        published_at > cursor.published_at,
                        and_(
                            published_at == cursor.published_at,
                            PublishedVideoModel.video_id > cursor.video_id,
                        ),
                    )
                )

        statement = select(PublishedVideoModel).where(*page_predicates)
        published_at = func.coalesce(PublishedVideoModel.published_at, "")
        if query.sort == "oldest":
            statement = statement.order_by(
                published_at.asc(),
                PublishedVideoModel.video_id.asc(),
            )
        else:
            statement = statement.order_by(
                published_at.desc(),
                PublishedVideoModel.video_id.desc(),
            )
        statement = statement.limit(query.limit + 1)
        rows = list((await self._session.scalars(statement)).all())
        page_rows = rows[: query.limit]
        topic_matches = await self._topic_matches(query.scope, page_rows, search_tokens)
        items = tuple(
            _to_video(row, topic_matches.get((row.video_id, row.variant), ())) for row in page_rows
        )
        next_cursor = (
            _encode_cursor(page_rows[-1]) if len(rows) > query.limit and page_rows else None
        )
        return PublicArchiveVideoPage(
            items=items,
            next_cursor=next_cursor,
            total_count=total_count,
        )

    async def get_video(
        self,
        *,
        scope: PublicArchiveScope,
        identifier: str,
    ) -> PublicArchiveVideo | None:
        identifier_predicate = (
            PublishedVideoModel.video_id == int(identifier)
            if identifier.isdigit() and int(identifier) > 0
            else PublishedVideoModel.youtube_video_id == identifier
        )
        statement = (
            select(PublishedVideoModel)
            .where(
                *_scope_predicates(scope),
                PublishedVideoModel.is_embeddable.is_not(False),
                identifier_predicate,
            )
            .order_by(
                (PublishedVideoModel.variant != "control").asc(),
                PublishedVideoModel.variant.asc(),
            )
            .limit(1)
        )
        row = await self._session.scalar(statement)
        return _to_video(row) if row is not None else None

    async def list_streamers(
        self,
        scope: PublicArchiveScope,
    ) -> tuple[PublicArchiveStreamer, ...]:
        statement = (
            select(
                PublishedVideoModel.streamer_id,
                PublishedVideoModel.streamer_name,
                func.count().label("video_count"),
            )
            .where(
                *_scope_predicates(scope),
                PublishedVideoModel.is_embeddable.is_not(False),
                PublishedVideoModel.streamer_id.is_not(None),
            )
            .group_by(PublishedVideoModel.streamer_id, PublishedVideoModel.streamer_name)
            .order_by(func.count().desc(), PublishedVideoModel.streamer_name.asc())
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            PublicArchiveStreamer(
                id=streamer_id,
                name=streamer_name,
                video_count=video_count,
            )
            for streamer_id, streamer_name, video_count in rows
        )

    async def catalog_version(self, scope: PublicArchiveScope) -> str:
        statement = select(
            func.count().label("video_count"),
            func.max(PublishedVideoModel.updated_at).label("latest_update"),
        ).where(*_scope_predicates(scope))
        video_count, latest = (await self._session.execute(statement)).one()
        if latest is None:
            return "0:0"
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)
        return f"{int(latest.timestamp() * 1_000_000)}:{video_count}"

    async def _topic_matches(
        self,
        scope: PublicArchiveScope,
        videos: list[PublishedVideoModel],
        tokens: tuple[str, ...],
    ) -> dict[tuple[int, str], tuple[PublicArchiveTopicMatch, ...]]:
        if not videos or not tokens:
            return {}
        keys = {(video.video_id, video.variant) for video in videos}
        statement = (
            select(PublishedTimelineTopicClusterModel)
            .where(
                *_topic_scope_predicates(scope),
                or_(
                    *[
                        func.lower(
                            func.coalesce(
                                PublishedTimelineTopicClusterModel.display_label,
                                PublishedTimelineTopicClusterModel.label,
                            )
                        ).contains(token.casefold())
                        for token in tokens
                    ]
                ),
            )
            .order_by(
                PublishedTimelineTopicClusterModel.video_id,
                PublishedTimelineTopicClusterModel.variant,
                PublishedTimelineTopicClusterModel.topic_id,
            )
        )
        matches: dict[tuple[int, str], list[PublicArchiveTopicMatch]] = {}
        for row in (await self._session.scalars(statement)).all():
            key = (row.video_id, row.variant)
            if key not in keys:
                continue
            values = matches.setdefault(key, [])
            if len(values) < 3:
                values.append(
                    PublicArchiveTopicMatch(
                        id=row.topic_id,
                        label=row.display_label or row.label,
                    )
                )
        return {key: tuple(value) for key, value in matches.items()}


def _scope_predicates(scope: PublicArchiveScope) -> tuple[ColumnElement[bool], ...]:
    return (
        PublishedVideoModel.profile_key == scope.profile_key,
        PublishedVideoModel.publish_mode == scope.publish_mode,
        PublishedVideoModel.environment == scope.environment,
    )


def _topic_scope_predicates(scope: PublicArchiveScope) -> tuple[ColumnElement[bool], ...]:
    return (
        PublishedTimelineTopicClusterModel.profile_key == scope.profile_key,
        PublishedTimelineTopicClusterModel.publish_mode == scope.publish_mode,
        PublishedTimelineTopicClusterModel.environment == scope.environment,
    )


def _search_predicate(scope: PublicArchiveScope, token: str) -> ColumnElement[bool]:
    pattern = f"%{token.casefold()}%"
    topic_match = exists(
        select(1).where(
            *_topic_scope_predicates(scope),
            PublishedTimelineTopicClusterModel.video_id == PublishedVideoModel.video_id,
            PublishedTimelineTopicClusterModel.variant == PublishedVideoModel.variant,
            func.lower(
                func.coalesce(
                    PublishedTimelineTopicClusterModel.display_label,
                    PublishedTimelineTopicClusterModel.label,
                )
            ).like(pattern),
        )
    )
    return or_(
        func.lower(PublishedVideoModel.title).like(pattern),
        func.lower(func.coalesce(PublishedVideoModel.display_title, "")).like(pattern),
        func.lower(func.coalesce(PublishedVideoModel.display_summary, "")).like(pattern),
        func.lower(func.coalesce(PublishedVideoModel.streamer_name, "")).like(pattern),
        func.lower(func.coalesce(PublishedVideoModel.channel_name, "")).like(pattern),
        topic_match,
    )


def _search_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = _SEARCH_SEPARATOR.sub(" ", normalized)
    return tuple(token for token in cleaned.split() if token)[:6]


def _decode_cursor(value: str | None) -> _Cursor | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        published_at = payload.get("publishedAt", "")
        video_id = payload.get("videoId", 0)
        if not isinstance(published_at, str) or not isinstance(video_id, int):
            return None
        return _Cursor(published_at=published_at, video_id=video_id)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _encode_cursor(row: PublishedVideoModel) -> str:
    payload = json.dumps(
        {"publishedAt": row.published_at or "", "videoId": row.video_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _to_video(
    row: PublishedVideoModel,
    topic_matches: tuple[PublicArchiveTopicMatch, ...] = (),
) -> PublicArchiveVideo:
    return PublicArchiveVideo(
        environment=row.environment,
        id=row.video_id,
        youtube_id=row.youtube_video_id,
        title=row.title,
        streamer_id=row.streamer_id,
        streamer_name=row.streamer_name,
        channel_id=row.channel_id,
        channel_name=row.channel_name,
        channel_handle=row.channel_handle,
        youtube_channel_id=row.youtube_channel_id,
        published_at=row.published_at,
        duration_text=row.duration_text,
        duration_seconds=row.duration_seconds,
        thumbnail_url=row.thumbnail_url,
        is_embeddable=row.is_embeddable,
        display_title=row.display_title,
        display_summary=row.display_summary,
        main_topics=tuple(row.main_topics),
        episode_count=row.episode_count,
        event_count=row.micro_event_count,
        topic_cluster_count=row.topic_cluster_count,
        block_count=row.block_count,
        timeline_variants=(
            PublicArchiveTimelineVariant(
                key=row.variant,
                url=row.timeline_url,
                version=row.timeline_version,
            ),
        ),
        timeline_url=row.timeline_url,
        updated_at=row.updated_at,
        search_matches=topic_matches,
    )
