from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.channels.commands import ResolveChannelUseCase
from codex_sdk_cli.application.channels.executors import ChannelResolveExecutor
from codex_sdk_cli.application.processing.commands import (
    ComposeTimelinesUseCase,
    ExtractMicroEventsUseCase,
)
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsUseCase,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.application.videos.commands import CollectVideosUseCase
from codex_sdk_cli.application.videos.executors import VideoCollectExecutor
from codex_sdk_cli.application.work.commands import (
    CancelPendingSubjectWorkUseCase,
    CancelWorkItemUseCase,
    RetryWorkItemUseCase,
)
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorRegistry,
    WorkUnitOfWorkFactory,
)
from codex_sdk_cli.application.work.queries import (
    GetWorkBatchUseCase,
    GetWorkflowRunUseCase,
    GetWorkItemUseCase,
    ListWorkItemsUseCase,
)
from codex_sdk_cli.infra.work.archive_execution import InlineWorkExecutionRunner
from codex_sdk_cli.infra.work.channel_execution import LegacyChannelResolver
from codex_sdk_cli.infra.work.scheduler import LegacyVideoCollector
from codex_sdk_cli.infra.work.transcript_execution import YouTubeTranscriptMetadataReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings


def work_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> WorkUnitOfWorkFactory:
    def create() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    return create


def collect_transcripts_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> CollectTranscriptsUseCase:
    return CollectTranscriptsUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def generate_transcript_cues_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GenerateTranscriptCuesUseCase:
    return GenerateTranscriptCuesUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        transcripts=YouTubeTranscriptMetadataReader(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def extract_micro_events_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> ExtractMicroEventsUseCase:
    return ExtractMicroEventsUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def compose_timelines_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> ComposeTimelinesUseCase:
    return ComposeTimelinesUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def collect_videos_use_case(
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> CollectVideosUseCase:
    unit_of_work = work_unit_of_work_factory(session_factory)
    engine = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work,
        registry=WorkExecutorRegistry(
            {
                "video_collect": lambda: VideoCollectExecutor(
                    LegacyVideoCollector(
                        session_factory=session_factory,
                        settings=settings,
                    ),
                    actor_type="manual_api",
                )
            }
        ),
        task_types=("video_collect",),
        worker_id="video-collect:manual-api",
    )
    return CollectVideosUseCase(
        unit_of_work_factory=unit_of_work,
        inline_runner=InlineWorkExecutionRunner(engine),
    )


def resolve_channel_use_case(
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> ResolveChannelUseCase:
    unit_of_work = work_unit_of_work_factory(session_factory)
    engine = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work,
        registry=WorkExecutorRegistry(
            {
                "channel_resolve": lambda: ChannelResolveExecutor(
                    LegacyChannelResolver(
                        session_factory=session_factory,
                        settings=settings,
                    )
                )
            }
        ),
        task_types=("channel_resolve",),
        worker_id="channel-resolve:manual-api",
    )
    return ResolveChannelUseCase(
        unit_of_work_factory=unit_of_work,
        inline_runner=InlineWorkExecutionRunner(engine),
    )


def list_work_items_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> ListWorkItemsUseCase:
    return ListWorkItemsUseCase(work_unit_of_work_factory(session_factory))


def get_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GetWorkItemUseCase:
    return GetWorkItemUseCase(work_unit_of_work_factory(session_factory))


def retry_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> RetryWorkItemUseCase:
    return RetryWorkItemUseCase(work_unit_of_work_factory(session_factory))


def cancel_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> CancelWorkItemUseCase:
    return CancelWorkItemUseCase(work_unit_of_work_factory(session_factory))


def cancel_pending_subject_work_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> CancelPendingSubjectWorkUseCase:
    return CancelPendingSubjectWorkUseCase(work_unit_of_work_factory(session_factory))


def get_work_batch_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GetWorkBatchUseCase:
    return GetWorkBatchUseCase(work_unit_of_work_factory(session_factory))


def get_workflow_run_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GetWorkflowRunUseCase:
    return GetWorkflowRunUseCase(work_unit_of_work_factory(session_factory))
