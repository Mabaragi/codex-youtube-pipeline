from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.work.execution import WorkExecutionEngine, WorkRunResult
from codex_sdk_cli.application.workflows.ports import (
    ArchivePublisherPort,
    InlineWorkRunnerPort,
    PublishedArchive,
)
from codex_sdk_cli.domains.archive_publish.use_cases import ArchivePublishUseCase
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel

ArchivePublishUseCaseFactory = Callable[[AsyncSession, int, int], ArchivePublishUseCase]


class WorkArchivePublisher(ArchivePublisherPort):

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
        del video_id, publish_mode, environment, variant, schema_version
        async with self._session_factory() as session:
            output = await self._use_case_factory(
                session, work_item_id, work_attempt_id
            ).execute_claimed_work_item(work_item_id)
            artifact_id = output.get("artifactId")
            public_url = output.get("publicUrl")
            if not isinstance(artifact_id, int) or not isinstance(public_url, str):
                raise RuntimeError("Archive publish did not produce an artifact.")
            artifact = await session.get(ArchiveVideoArtifactModel, artifact_id)
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
            video_id=artifact.video_id,
            artifact_id=artifact_id,
            public_url=public_url,
        )


class InlineWorkExecutionRunner(InlineWorkRunnerPort):
    def __init__(self, engine: WorkExecutionEngine) -> None:
        self._engine = engine

    @override
    async def run(self, work_item_id: int) -> WorkRunResult:
        return await self._engine.run_inline(work_item_id)
