from __future__ import annotations

from typing import cast

import httpx
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.scheduler.ports import (
    AutomationScheduleState,
    PublishedPromptSnapshotPort,
    ScheduledChannel,
    ScheduledChannelReaderPort,
    SchedulerEvent,
    SchedulerEventRecorderPort,
    WorkflowCandidateReaderPort,
)
from codex_sdk_cli.application.videos.ports import (
    VideoCollectionResult,
    VideoCollectorPort,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventCreate,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.recorder import (
    BestEffortOperationEventRecorder,
)
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.videos.use_cases import CollectChannelVideosUseCase
from codex_sdk_cli.domains.work.models import JsonObject, WorkItemStatus
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.infra.channels.repository import (
    ChannelModel,
    SqlAlchemyChannelRepository,
)
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import (
    ExternalApiCallModel,
    SqlAlchemyExternalApiCallRepository,
)
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.operation_events.repository import (
    OperationEventModel,
    SQLAlchemyOperationEventRepository,
)
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository, VideoModel
from codex_sdk_cli.infra.work.models import WorkflowRunModel, WorkItemModel
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.settings import CliSettings

from .execution_repositories import WorkPipelineJobRepository


class SqlAlchemyScheduledChannelReader(ScheduledChannelReaderPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def list_scheduled_channels(self) -> list[ScheduledChannel]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(ChannelModel.id, ChannelModel.youtube_channel_id)
                        .where(ChannelModel.youtube_channel_id.is_not(None))
                        .order_by(ChannelModel.id)
                    )
                ).all()
            )
        return [
            ScheduledChannel(id=channel_id, youtube_channel_id=youtube_channel_id)
            for channel_id, youtube_channel_id in rows
            if youtube_channel_id is not None
        ]


class SqlAlchemySchedulerEventRecorder(SchedulerEventRecorderPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def record(self, event: SchedulerEvent) -> None:
        async with self._session_factory() as session:
            recorder = BestEffortOperationEventRecorder(
                SQLAlchemyOperationEventRepository(session)
            )
            await recorder.record_event(
                OperationEventCreate(
                    event_type=event.event_type,
                    severity=_severity(event.severity),
                    message=event.message,
                    actor_type="system",
                    source="pipeline_scheduler",
                    channel_id=event.channel_id,
                    subject_type=event.subject_type,
                    subject_id=event.subject_id,
                    external_key=event.external_key,
                    error_type=event.error_type,
                    error_message=event.error_message,
                    metadata_json=event.metadata_json or {},
                )
            )


class SqlAlchemyWorkflowCandidateReader(WorkflowCandidateReaderPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def list_candidates(
        self,
        *,
        state: AutomationScheduleState,
        limit: int,
    ) -> list[VideoRecord]:
        published = exists(
            select(WorkItemModel.id).where(
                WorkItemModel.task_type == "archive_publish",
                WorkItemModel.subject_type == "video",
                WorkItemModel.subject_id == VideoModel.id,
                WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                WorkItemModel.outcome_code.is_(None),
            )
        )
        active_workflow = exists(
            select(WorkflowRunModel.id).where(
                WorkflowRunModel.video_id == VideoModel.id,
                WorkflowRunModel.workflow_type == "process_to_publish",
                WorkflowRunModel.workflow_version == "v2",
                WorkflowRunModel.status.in_(("pending", "running", "waiting")),
            )
        )
        terminal_automation_workflow = exists(
            select(WorkflowRunModel.id).where(
                WorkflowRunModel.video_id == VideoModel.id,
                WorkflowRunModel.workflow_type == "process_to_publish",
                WorkflowRunModel.workflow_version == "v2",
                WorkflowRunModel.options_json["automation_mode"].as_string() == state.mode,
                WorkflowRunModel.status.in_(("failed", "blocked", "canceled")),
            )
        )
        async with self._session_factory() as session:
            statement = (
                select(VideoModel)
                .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                .where(
                    VideoModel.is_embeddable.is_not(False),
                    ~published,
                    ~active_workflow,
                    ~terminal_automation_workflow,
                )
            )
            if state.mode == "backfill":
                statement = statement.where(VideoModel.created_at <= state.backfill_started_at)
            else:
                statement = statement.where(VideoModel.created_at > state.backfill_started_at)
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
        from codex_sdk_cli.infra.videos.repository import video_record_from_model

        return [video_record_from_model(model) for model in models]


class SqlAlchemyPublishedPromptSnapshot(PublishedPromptSnapshotPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def active_version_ids(self) -> tuple[int, int]:
        async with self._session_factory() as session:
            repository = SqlAlchemyPromptRepository(session)
            micro = await repository.get_active_version("micro_event_extract")
            timeline = await repository.get_active_version("timeline_compose")
        if micro is None or timeline is None:
            raise RuntimeError(
                "Published database prompts are required for automatic pipeline workflows."
            )
        return micro.id, timeline.id


class WorkVideoCollector(VideoCollectorPort):

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: CliSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    @override
    async def collect(
        self,
        *,
        channel_id: int,
        work_item_id: int,
        work_attempt_id: int,
        actor_type: str,
    ) -> VideoCollectionResult:
        api_key = self._settings.youtube_data_api_key_value()
        if api_key is None:
            raise YouTubeDataConfigurationError("YouTube Data API key is not configured.")
        async with self._session_factory() as session:
            recorder = ExternalApiCallRecorder(
                SqlAlchemyExternalApiCallRepository(session),
                MinioExternalApiCallStorage.from_settings(self._settings),
                storage_prefix=self._settings.external_api_call_minio_prefix,
            )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.youtube_data_timeout_seconds)
            ) as http_client:
                use_case = CollectChannelVideosUseCase(
                    YouTubeDataClient(
                        http_client,
                        api_key=api_key,
                        api_call_recorder=recorder,
                    ),
                    SqlAlchemyChannelRepository(session),
                    SqlAlchemyVideoRepository(session),
                    WorkPipelineJobRepository(
                        session,
                        current_work_item_id=work_item_id,
                        current_work_attempt_id=work_attempt_id,
                    ),
                    BestEffortOperationEventRecorder(
                        SQLAlchemyOperationEventRepository(session)
                    ),
                )
                response = await use_case.execute(
                    channel_id,
                    actor_type=_actor_type(actor_type),
                )
            await session.execute(
                update(VideoModel)
                .where(VideoModel.source_job_id == response.job_id)
                .values(source_work_item_id=work_item_id)
            )
            await session.execute(
                update(ExternalApiCallModel)
                .where(
                    ExternalApiCallModel.pipeline_job_attempt_id == response.job_attempt_id
                )
                .values(work_attempt_id=work_attempt_id)
            )
            await session.execute(
                update(OperationEventModel)
                .where(OperationEventModel.job_attempt_id == response.job_attempt_id)
                .values(work_item_id=work_item_id, work_attempt_id=work_attempt_id)
            )
            await session.commit()
        return VideoCollectionResult(
            created_count=response.created_count,
            output_json=cast(JsonObject, response.model_dump(by_alias=True)),
        )


def _severity(value: str) -> OperationEventSeverity:
    if value == "error":
        return "error"
    if value == "warning":
        return "warning"
    return "info"


def _actor_type(value: str) -> OperationEventActorType:
    if value == "manual_api":
        return "manual_api"
    if value == "retry_executor":
        return "retry_executor"
    return "system"
