from __future__ import annotations

from collections.abc import Callable
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.work.execution import WorkExecutionEngine, WorkRunResult
from codex_sdk_cli.application.workflows.ports import (
    ArchivePublisherPort,
    InlineWorkRunnerPort,
    PublishedArchive,
)
from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchivePublishModeLiteral,
    ArchivePublishRequest,
)
from codex_sdk_cli.domains.archive_publish.use_cases import ArchivePublishUseCase
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel

ArchivePublishUseCaseFactory = Callable[[AsyncSession], ArchivePublishUseCase]


class LegacyArchivePublisher(ArchivePublisherPort):
    """Bridge the new work contract to the proven R2/D1 publisher during cutover."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        use_case_factory: ArchivePublishUseCaseFactory,
    ) -> None:
        self._session_factory = session_factory
        self._use_case_factory = use_case_factory

    @override
    async def publish(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_timeline_work_item_id: int,
        publish_mode: str,
        environment: str,
        variant: str,
        schema_version: int,
    ) -> PublishedArchive:
        if publish_mode not in {"prod", "dev"}:
            raise ValueError("publishMode must be prod or dev.")
        async with self._session_factory() as session:
            response = await self._use_case_factory(session).publish(
                ArchivePublishRequest(
                    target="selected_videos",
                    videoIds=[video_id],
                    limit=1,
                    publishMode=cast(ArchivePublishModeLiteral, publish_mode),
                    environment=environment,
                    variant=variant,
                    schemaVersion=schema_version,
                    retryFailed=True,
                    regenerateSucceeded=False,
                )
            )
            item = next((item for item in response.items if item.video_id == video_id), None)
            if item is None:
                raise RuntimeError("Archive publisher returned no result for the selected video.")
            if item.artifact_id is None or item.public_url is None:
                detail = item.error_message or item.reason
                raise RuntimeError(f"Archive publish did not produce an artifact: {detail}")
            artifact = await session.get(ArchiveVideoArtifactModel, item.artifact_id)
            if artifact is None:
                raise RuntimeError("Published archive artifact was not found.")
            artifact.source_timeline_work_item_id = source_timeline_work_item_id
            artifact.publish_work_item_id = work_item_id
            artifact.publish_work_attempt_id = work_attempt_id
            source_micro_work_item_id = await session.scalar(
                select(TimelineCompositionModel.source_micro_event_work_item_id).where(
                    TimelineCompositionModel.work_item_id == source_timeline_work_item_id
                )
            )
            artifact.source_micro_event_work_item_id = source_micro_work_item_id
            await session.commit()
        return PublishedArchive(
            video_id=video_id,
            artifact_id=item.artifact_id,
            public_url=item.public_url,
        )


class InlineWorkExecutionRunner(InlineWorkRunnerPort):
    def __init__(self, engine: WorkExecutionEngine) -> None:
        self._engine = engine

    @override
    async def run(self, work_item_id: int) -> WorkRunResult:
        return await self._engine.run_inline(work_item_id)
