from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.bootstrap.operations import cancel_pending_subject_work_use_case
from codex_sdk_cli.domains.operation_events.recorder import (
    BestEffortOperationEventRecorder,
)
from codex_sdk_cli.domains.video_availability.use_cases import (
    ProcessVideoAvailabilityCandidatesResult,
    ProcessVideoAvailabilityCandidatesUseCase,
    VerifyVideoAvailabilityUseCase,
)
from codex_sdk_cli.infra.automation.repository import SqlAlchemyAutomationRepository
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import (
    SqlAlchemyExternalApiCallRepository,
)
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.operation_events.repository import (
    SQLAlchemyOperationEventRepository,
)
from codex_sdk_cli.infra.video_availability.client import (
    VideoAvailabilityCandidateClient,
)
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.work.execution_repositories import WorkVideoTaskRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.settings import CliSettings


class VideoAvailabilityRuntime:
    def __init__(self, settings: CliSettings, *, worker_id: str) -> None:
        base_url = settings.archive_video_availability_api_base_url
        admin_token = settings.archive_video_availability_admin_token_value()
        youtube_api_key = settings.youtube_data_api_key_value()
        if base_url is None:
            raise ValueError("Archive video availability API base URL is not configured.")
        if admin_token is None:
            raise ValueError("Archive video availability admin token is not configured.")
        if youtube_api_key is None:
            raise ValueError("YouTube Data API key is not configured.")

        self.settings = settings
        self.worker_id = worker_id
        self._youtube_api_key = youtube_api_key
        self.database_engine: AsyncEngine = create_database_engine(
            settings.database_url,
            echo=settings.database_echo,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
            self.database_engine
        )
        self._inbox_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.archive_video_availability_timeout_seconds)
        )
        self._youtube_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.youtube_data_timeout_seconds)
        )
        self._inbox = VideoAvailabilityCandidateClient(
            self._inbox_http_client,
            base_url=base_url,
            admin_token=admin_token,
        )

    async def close(self) -> None:
        await self._inbox_http_client.aclose()
        await self._youtube_http_client.aclose()
        await self.database_engine.dispose()

    async def cleanup(self) -> int:
        return await self._inbox.cleanup()

    async def process_once(self) -> ProcessVideoAvailabilityCandidatesResult:
        state = await SqlAlchemyAutomationRepository(self.session_factory).get_state(
            now=datetime.now(UTC)
        )
        if state.runtime_state != "active":
            return ProcessVideoAvailabilityCandidatesResult(0, 0, 0, 0)
        async with self.session_factory() as session:
            api_calls = ExternalApiCallRecorder(
                SqlAlchemyExternalApiCallRepository(session),
                MinioExternalApiCallStorage.from_settings(self.settings),
                storage_prefix=self.settings.external_api_call_minio_prefix,
            )
            verifier = VerifyVideoAvailabilityUseCase(
                videos=SqlAlchemyVideoRepository(session),
                video_tasks=WorkVideoTaskRepository(session),
                pending_work=cancel_pending_subject_work_use_case(self.session_factory),
                youtube_data=YouTubeDataClient(
                    self._youtube_http_client,
                    api_key=self._youtube_api_key,
                    api_call_recorder=api_calls,
                ),
                events=BestEffortOperationEventRecorder(
                    SQLAlchemyOperationEventRepository(session)
                ),
            )
            return await ProcessVideoAvailabilityCandidatesUseCase(
                inbox=self._inbox,
                verifier=verifier,
                worker_id=self.worker_id,
                claim_limit=self.settings.archive_video_availability_claim_limit,
                lease_seconds=self.settings.archive_video_availability_lease_seconds,
            ).execute_once()
