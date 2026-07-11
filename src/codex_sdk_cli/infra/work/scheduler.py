from __future__ import annotations

from typing import cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.scheduler.ports import (
    ScheduledChannel,
    ScheduledChannelReaderPort,
    SchedulerEvent,
    SchedulerEventRecorderPort,
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
from codex_sdk_cli.domains.videos.use_cases import CollectChannelVideosUseCase
from codex_sdk_cli.domains.work.models import JsonObject
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.infra.channels.repository import (
    ChannelModel,
    SqlAlchemyChannelRepository,
)
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import (
    SqlAlchemyExternalApiCallRepository,
)
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.operation_events.repository import (
    SQLAlchemyOperationEventRepository,
)
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.settings import CliSettings


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


class LegacyVideoCollector(VideoCollectorPort):
    """Temporary adapter until the video collection algorithm moves to application."""

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
        del work_item_id, work_attempt_id
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
                    SqlAlchemyPipelineJobRepository(session),
                    BestEffortOperationEventRecorder(
                        SQLAlchemyOperationEventRepository(session)
                    ),
                )
                response = await use_case.execute(
                    channel_id,
                    actor_type=_actor_type(actor_type),
                )
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
