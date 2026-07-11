from __future__ import annotations

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.channels.ports import ChannelResolverPort, ResolvedChannel
from codex_sdk_cli.domains.channels.schemas import ResolveYouTubeChannelRequest
from codex_sdk_cli.domains.channels.use_cases import ResolveYouTubeChannelUseCase
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.infra.channels.repository import ChannelModel, SqlAlchemyChannelRepository
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import (
    ExternalApiCallModel,
    SqlAlchemyExternalApiCallRepository,
)
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.settings import CliSettings


class LegacyChannelResolver(ChannelResolverPort):
    """Bridge channel resolution while preserving existing API-call raw storage."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: CliSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    @override
    async def resolve(
        self,
        *,
        streamer_id: int,
        handle: str,
        work_item_id: int,
        work_attempt_id: int,
    ) -> ResolvedChannel:
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
                response = await ResolveYouTubeChannelUseCase(
                    YouTubeDataClient(
                        http_client,
                        api_key=api_key,
                        api_call_recorder=recorder,
                    ),
                    SqlAlchemyChannelRepository(session),
                    SqlAlchemyStreamerRepository(session),
                    SqlAlchemyPipelineJobRepository(session),
                ).execute(streamer_id, ResolveYouTubeChannelRequest(handle=handle))
            await session.execute(
                update(ChannelModel)
                .where(ChannelModel.id == response.channel_id)
                .values(source_work_item_id=work_item_id)
            )
            await session.execute(
                update(ExternalApiCallModel)
                .where(
                    ExternalApiCallModel.pipeline_job_attempt_id == response.job_attempt_id
                )
                .values(work_attempt_id=work_attempt_id)
            )
            await session.commit()
        return ResolvedChannel(
            channel_id=response.channel_id,
            streamer_id=response.streamer_id,
            handle=response.handle,
            name=response.name,
            youtube_channel_id=response.youtube_channel_id,
            uploads_playlist_id=response.uploads_playlist_id,
        )
