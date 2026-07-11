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
from codex_sdk_cli.domains.micro_events.schemas import MicroEventEnqueueRequest
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.timelines.ports import CopyStyle
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest
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
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository

MicroEventUseCaseFactory = Callable[[AsyncSession], ExtractVideoMicroEventsUseCase]
TimelineUseCaseFactory = Callable[[AsyncSession], ComposeTimelineUseCase]


class LegacyMicroEventProcessor(MicroEventProcessorPort):
    """Transition adapter until legacy task tables are removed at contract cutover."""

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
            use_case = self._use_case_factory(session)
            queued = await use_case.enqueue(
                MicroEventEnqueueRequest(
                    target="selected_videos",
                    videoIds=[video_id],
                    limit=1,
                    retryFailed=True,
                    regenerateSucceeded=True,
                    windowMinutes=window_minutes,
                    overlapMinutes=overlap_minutes,
                    model=model,
                    reasoningEffort=reasoning_effort,
                    promptVersionId=prompt_version_id,
                )
            )
            item = queued.items[0] if queued.items else None
            if item is None or item.video_task_id is None:
                raise RuntimeError(item.reason if item is not None else "micro_event_not_queued")
            legacy_task_id = item.video_task_id
            task = await SqlAlchemyVideoTaskRepository(session).claim_pending_task(
                legacy_task_id,
                worker_id=f"work-item:{work_item_id}",
            )
            if task is None:
                raise RuntimeError("Legacy micro-event task could not be claimed.")
            response = await use_case.execute_claimed_task(
                task,
                worker_id=f"work-item:{work_item_id}",
            )
            if response.status != "succeeded":
                raise RuntimeError(response.error_message or response.reason)
            await _link_micro_event_provenance(
                session,
                legacy_task_id=legacy_task_id,
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


class LegacyTimelineProcessor(TimelineProcessorPort):
    """Transition adapter until timeline persistence is work-item native."""

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
            legacy_source_task_id = await session.scalar(
                select(MicroEventExtractionWindowModel.video_task_id)
                .where(
                    MicroEventExtractionWindowModel.work_item_id == source_micro_event_work_item_id
                )
                .order_by(MicroEventExtractionWindowModel.id.asc())
                .limit(1)
            )
            if legacy_source_task_id is None:
                raise RuntimeError("Source micro-event extraction was not found.")
            use_case = self._use_case_factory(session)
            queued = await use_case.enqueue(
                TimelineComposeEnqueueRequest(
                    target="selected_videos",
                    videoIds=[video_id],
                    limit=1,
                    retryFailed=True,
                    regenerateSucceeded=True,
                    model=model,
                    reasoningEffort=reasoning_effort,
                    copyStyle=copy_style,
                    promptVersionId=prompt_version_id,
                )
            )
            item = queued.items[0] if queued.items else None
            if item is None or item.video_task_id is None:
                raise RuntimeError(item.reason if item is not None else "timeline_not_queued")
            legacy_task_id = item.video_task_id
            task = await SqlAlchemyVideoTaskRepository(session).claim_pending_task(
                legacy_task_id,
                worker_id=f"work-item:{work_item_id}",
            )
            if task is None:
                raise RuntimeError("Legacy timeline task could not be claimed.")
            response = await use_case.execute_claimed_task(
                task,
                worker_id=f"work-item:{work_item_id}",
            )
            await _link_timeline_provenance(
                session,
                legacy_task_id=legacy_task_id,
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
