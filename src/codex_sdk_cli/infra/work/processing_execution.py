from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.processing.ports import (
    MicroEventProcessorPort,
    MicroEventProcessResult,
    TimelineProcessorPort,
    TimelineProcessResult,
)
from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.timelines.ports import CopyStyle
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.infra.codex_usage.repository import CodexRunUsageModel
from codex_sdk_cli.infra.micro_events.repository import (
    AsrCorrectionCandidateModel,
    MicroEventCandidateModel,
    MicroEventExcludedRangeModel,
    MicroEventExtractionWindowModel,
)
from codex_sdk_cli.infra.operation_events.repository import OperationEventModel
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel
from codex_sdk_cli.infra.work.execution_repositories import WorkVideoTaskRepository
from codex_sdk_cli.infra.work.models import WorkItemModel

MicroEventUseCaseFactory = Callable[
    [AsyncSession, int, int], ExtractVideoMicroEventsUseCase
]
TimelineUseCaseFactory = Callable[[AsyncSession, int, int], ComposeTimelineUseCase]


class WorkMicroEventProcessor(MicroEventProcessorPort):

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        use_case_factory: MicroEventUseCaseFactory,
    ) -> None:
        self._session_factory = session_factory
        self._use_case_factory = use_case_factory

    @override
    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        transcript_id: int,
        window_minutes: int,
        overlap_minutes: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        prompt_version_id: int | None,
    ) -> MicroEventProcessResult:
        async with self._session_factory() as session:
            use_case = self._use_case_factory(session, work_item_id, work_attempt_id)
            task = await WorkVideoTaskRepository(session).get_task(work_item_id)
            if task is None or task.status != "running":
                raise RuntimeError("Running micro-event work item was not found.")
            response = await use_case.execute_claimed_task(
                task,
                worker_id=f"work-item:{work_item_id}",
            )
            if response.status != "succeeded":
                raise RuntimeError(response.error_message or response.reason)
            await _link_micro_event_provenance(
                session,
                legacy_task_id=work_item_id,
                work_item_id=work_item_id,
                work_attempt_id=work_attempt_id,
            )
            warning_count = await session.scalar(
                select(func.count())
                .select_from(MicroEventExtractionWindowModel)
                .where(
                    MicroEventExtractionWindowModel.work_item_id == work_item_id,
                    MicroEventExtractionWindowModel.validation_error.is_not(None),
                )
            )
            await session.commit()
        return MicroEventProcessResult(
            video_id=video_id,
            transcript_id=response.transcript_id or transcript_id,
            window_count=response.window_count or 0,
            micro_event_count=response.micro_event_count or 0,
            validation_warning_count=warning_count or 0,
        )


class WorkTimelineProcessor(TimelineProcessorPort):

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        use_case_factory: TimelineUseCaseFactory,
    ) -> None:
        self._session_factory = session_factory
        self._use_case_factory = use_case_factory

    @override
    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_micro_event_work_item_id: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        copy_style: CopyStyle,
        prompt_version_id: int | None,
    ) -> TimelineProcessResult:
        async with self._session_factory() as session:
            source_exists = await session.scalar(
                select(WorkItemModel.id).where(
                    WorkItemModel.id == source_micro_event_work_item_id
                )
            )
            if source_exists is None:
                raise RuntimeError("Source micro-event work item was not found.")
            use_case = self._use_case_factory(session, work_item_id, work_attempt_id)
            task = await WorkVideoTaskRepository(session).get_task(work_item_id)
            if task is None or task.status != "running":
                raise RuntimeError("Running timeline work item was not found.")
            response = await use_case.execute_claimed_task(
                task,
                worker_id=f"work-item:{work_item_id}",
            )
            await _link_timeline_provenance(
                session,
                legacy_task_id=work_item_id,
                work_item_id=work_item_id,
                work_attempt_id=work_attempt_id,
                source_micro_event_work_item_id=source_micro_event_work_item_id,
            )
            composition = await session.scalar(
                select(TimelineCompositionModel).where(
                    TimelineCompositionModel.work_item_id == work_item_id
                )
            )
            if composition is None:
                raise RuntimeError("Timeline composition was not persisted.")
            await session.commit()
        return TimelineProcessResult(
            video_id=video_id,
            composition_id=composition.id,
            title=response.title,
            block_count=len(response.blocks),
            episode_count=len(response.episodes),
            topic_cluster_count=len(response.topic_clusters),
            review_flag_count=len(response.review_flags),
            validation_warning_count=len(response.validation_warnings),
            timeline_state=response.timeline_state,
            empty_reason=response.empty_reason,
            generation_mode=response.generation_mode,
        )


async def _link_micro_event_provenance(
    session: AsyncSession,
    *,
    legacy_task_id: int,
    work_item_id: int,
    work_attempt_id: int,
) -> None:
    for model in (
        MicroEventExtractionWindowModel,
        MicroEventCandidateModel,
        MicroEventExcludedRangeModel,
        AsrCorrectionCandidateModel,
    ):
        await session.execute(
            update(model)
            .where(model.video_task_id == legacy_task_id)
            .values(work_item_id=work_item_id)
        )
    await session.execute(
        update(MicroEventExtractionWindowModel)
        .where(MicroEventExtractionWindowModel.video_task_id == legacy_task_id)
        .values(source_work_attempt_id=work_attempt_id)
    )
    await _link_observability(
        session,
        legacy_task_id=legacy_task_id,
        work_item_id=work_item_id,
        work_attempt_id=work_attempt_id,
    )


async def _link_timeline_provenance(
    session: AsyncSession,
    *,
    legacy_task_id: int,
    work_item_id: int,
    work_attempt_id: int,
    source_micro_event_work_item_id: int,
) -> None:
    await session.execute(
        update(TimelineCompositionModel)
        .where(TimelineCompositionModel.video_task_id == legacy_task_id)
        .values(
            work_item_id=work_item_id,
            source_micro_event_work_item_id=source_micro_event_work_item_id,
            source_work_attempt_id=work_attempt_id,
        )
    )
    await _link_observability(
        session,
        legacy_task_id=legacy_task_id,
        work_item_id=work_item_id,
        work_attempt_id=work_attempt_id,
    )


async def _link_observability(
    session: AsyncSession,
    *,
    legacy_task_id: int,
    work_item_id: int,
    work_attempt_id: int,
) -> None:
    await session.execute(
        update(CodexRunUsageModel)
        .where(
            CodexRunUsageModel.video_task_id == legacy_task_id,
            CodexRunUsageModel.work_item_id.is_(None),
        )
        .values(
            work_item_id=work_item_id,
            work_attempt_id=work_attempt_id,
        )
    )
    await session.execute(
        update(OperationEventModel)
        .where(
            OperationEventModel.video_task_id == legacy_task_id,
            OperationEventModel.work_item_id.is_(None),
        )
        .values(
            work_item_id=work_item_id,
            work_attempt_id=work_attempt_id,
        )
    )
