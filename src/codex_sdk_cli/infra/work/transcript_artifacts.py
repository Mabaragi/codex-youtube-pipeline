from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.workflows.ports import (
    TranscriptArtifact,
    TranscriptArtifactReaderPort,
)
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    YouTubeTranscriptRecordModel,
)


class SqlAlchemyTranscriptArtifactReader(TranscriptArtifactReaderPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def find_latest(self, *, youtube_video_id: str) -> TranscriptArtifact | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(YouTubeTranscriptRecordModel)
                .where(YouTubeTranscriptRecordModel.video_id == youtube_video_id)
                .order_by(
                    YouTubeTranscriptRecordModel.created_at.desc(),
                    YouTubeTranscriptRecordModel.id.desc(),
                )
                .limit(1)
            )
        if model is None:
            return None
        return TranscriptArtifact(
            transcript_id=model.id,
            response_sha256=model.response_sha256,
        )
