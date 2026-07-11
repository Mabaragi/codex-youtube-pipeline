from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.operations.selection import (
    ChannelVideos,
    FilteredVideos,
    NextEligibleVideos,
    SelectedVideos,
    VideoSelection,
    VideoSelectionPort,
)
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.infra.videos.repository import VideoModel, video_record_from_model


class SqlAlchemyVideoSelection(VideoSelectionPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def select(self, selection: VideoSelection) -> list[VideoRecord]:
        async with self._session_factory() as session:
            if isinstance(selection, SelectedVideos):
                return await _selected(session, selection)
            statement = select(VideoModel)
            limit: int
            if isinstance(selection, ChannelVideos):
                statement = statement.where(VideoModel.channel_id == selection.channel_id)
                limit = selection.limit
            elif isinstance(selection, FilteredVideos):
                if selection.channel_id is not None:
                    statement = statement.where(VideoModel.channel_id == selection.channel_id)
                if selection.search:
                    pattern = f"%{selection.search.strip()}%"
                    statement = statement.where(
                        or_(
                            VideoModel.title.ilike(pattern),
                            VideoModel.youtube_video_id.ilike(pattern),
                        )
                    )
                limit = selection.limit
            elif isinstance(selection, NextEligibleVideos):
                limit = selection.limit
            else:
                raise TypeError(f"Unsupported video selection: {type(selection).__name__}")
            models = list(
                (
                    await session.scalars(
                        statement.order_by(
                            VideoModel.published_at.desc(),
                            VideoModel.id.desc(),
                        ).limit(limit)
                    )
                ).all()
            )
        return [video_record_from_model(model) for model in models]


async def _selected(
    session: AsyncSession,
    selection: SelectedVideos,
) -> list[VideoRecord]:
    if not selection.video_ids:
        return []
    models = list(
        (
            await session.scalars(select(VideoModel).where(VideoModel.id.in_(selection.video_ids)))
        ).all()
    )
    by_id = {model.id: model for model in models}
    return [
        video_record_from_model(by_id[video_id])
        for video_id in selection.video_ids
        if video_id in by_id
    ]
