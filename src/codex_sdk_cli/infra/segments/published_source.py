from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.segments.ports import SegmentPublishedTimelineReaderPort
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel


class SqlAlchemyPublishedTimelineReader(SegmentPublishedTimelineReaderPort):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def latest(
        self, *, video_id: int, environment: str, variant: str, schema_version: int
    ) -> int | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(
                    func.coalesce(
                        ArchiveVideoArtifactModel.source_timeline_work_item_id,
                        ArchiveVideoArtifactModel.source_timeline_task_id,
                    )
                )
                .where(
                    ArchiveVideoArtifactModel.video_id == video_id,
                    ArchiveVideoArtifactModel.environment == environment,
                    ArchiveVideoArtifactModel.variant == variant,
                    ArchiveVideoArtifactModel.schema_version == schema_version,
                    ArchiveVideoArtifactModel.artifact_status == "ready",
                )
                .order_by(ArchiveVideoArtifactModel.id.desc())
                .limit(1)
            )
