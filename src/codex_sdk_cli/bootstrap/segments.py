from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.segments.backfill import BackfillSegmentsUseCase
from codex_sdk_cli.application.segments.commands import ClassifySegmentsUseCase
from codex_sdk_cli.application.segments.executors import SegmentClassificationExecutor
from codex_sdk_cli.application.segments.inputs import PrepareSegmentInputUseCase
from codex_sdk_cli.application.segments.ports import SegmentInputPlannerPort
from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.infra.segments.published_source import SqlAlchemyPublishedTimelineReader
from codex_sdk_cli.infra.segments.repository import SqlAlchemySegmentResultStore
from codex_sdk_cli.infra.segments.source import SqlAlchemySegmentSourceReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings

from .processing import _recording_runtime


class SegmentInputPlanner(SegmentInputPlannerPort):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def prepare(
        self,
        *,
        video_id: int,
        timeline_work_item_id: int,
        model: str,
        reasoning_effort: str,
        prompt_version_id: int | None,
        taxonomy_version: str,
    ) -> dict[str, object]:
        async with self._sessions() as session:
            return await PrepareSegmentInputUseCase(
                SqlAlchemySegmentSourceReader(self._sessions),
                PromptResolver(
                    SqlAlchemyPromptRepository(session), cache=PromptCache(), ttl_seconds=0
                ),
            ).prepare(
                video_id=video_id,
                timeline_work_item_id=timeline_work_item_id,
                model=model,
                reasoning_effort=reasoning_effort,
                prompt_version_id=prompt_version_id,
                taxonomy_version=taxonomy_version,
            )


def classify_segments_use_case(
    sessions: async_sessionmaker[AsyncSession],
) -> ClassifySegmentsUseCase:
    return ClassifySegmentsUseCase(
        videos=SqlAlchemyVideoSelection(sessions),
        unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(sessions),
        planner=SegmentInputPlanner(sessions),
    )


def backfill_segments_use_case(
    sessions: async_sessionmaker[AsyncSession],
) -> BackfillSegmentsUseCase:
    return BackfillSegmentsUseCase(
        videos=SqlAlchemyVideoSelection(sessions),
        unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(sessions),
        planner=SegmentInputPlanner(sessions),
        published_sources=SqlAlchemyPublishedTimelineReader(sessions),
    )


def segment_executor(
    sessions: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> SegmentClassificationExecutor:
    return SegmentClassificationExecutor(
        source=SqlAlchemySegmentSourceReader(sessions),
        results=SqlAlchemySegmentResultStore(sessions),
        runtime=_recording_runtime(sessions, settings),
    )
