from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.application.processing.executors import (
    MicroEventExtractionExecutor,
    TimelineCompositionExecutor,
)
from codex_sdk_cli.application.transcripts.executors import (
    TranscriptCollectExecutor,
    TranscriptCueGenerateExecutor,
)
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorFactory,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.workflows.archive import ArchivePublishExecutor
from codex_sdk_cli.application.workflows.coordinator import ProcessToPublishCoordinator
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.archive_execution import (
    InlineWorkExecutionRunner,
    LegacyArchivePublisher,
)
from codex_sdk_cli.infra.work.processing_execution import (
    LegacyMicroEventProcessor,
    LegacyTimelineProcessor,
)
from codex_sdk_cli.infra.work.transcript_execution import (
    StoredTranscriptCueGenerator,
    StoredYouTubeTranscriptFetcher,
)
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings

from .archive import archive_publish_use_case
from .processing import micro_event_use_case, timeline_use_case


class WorkRuntime:
    def __init__(self, settings: CliSettings) -> None:
        self.settings = settings
        self.database_engine: AsyncEngine = create_database_engine(
            settings.database_url,
            echo=settings.database_echo,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
            self.database_engine
        )

    async def close(self) -> None:
        await self.database_engine.dispose()

    def execution_engine(
        self,
        *,
        task_types: tuple[str, ...],
        worker_id: str,
    ) -> WorkExecutionEngine:
        factories: dict[str, WorkExecutorFactory] = {}
        if "transcript_collect" in task_types:
            factories["transcript_collect"] = self._transcript_executor
        if "transcript_cue_generate" in task_types:
            factories["transcript_cue_generate"] = self._cue_executor
        if "micro_event_extract" in task_types:
            factories["micro_event_extract"] = self._micro_event_executor
        if "timeline_compose" in task_types:
            factories["timeline_compose"] = self._timeline_executor
        if "archive_publish" in task_types:
            factories["archive_publish"] = self._archive_executor
        return WorkExecutionEngine(
            unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(self.session_factory),
            registry=WorkExecutorRegistry(factories),
            task_types=task_types,
            worker_id=worker_id,
        )

    def workflow_coordinator(self, *, worker_id: str) -> ProcessToPublishCoordinator:
        archive_engine = self.execution_engine(
            task_types=("archive_publish",),
            worker_id=f"{worker_id}:archive",
        )
        return ProcessToPublishCoordinator(
            unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(self.session_factory),
            inline_runner=InlineWorkExecutionRunner(archive_engine),
            worker_id=worker_id,
        )

    def _transcript_executor(self) -> TranscriptCollectExecutor:
        return TranscriptCollectExecutor(
            StoredYouTubeTranscriptFetcher(
                session_factory=self.session_factory,
                client=YouTubeTranscriptClient.from_settings(self.settings),
                storage=MinioTranscriptStorage.from_settings(self.settings),
                storage_prefix=self.settings.transcript_minio_prefix,
            )
        )

    def _cue_executor(self) -> TranscriptCueGenerateExecutor:
        return TranscriptCueGenerateExecutor(
            StoredTranscriptCueGenerator(
                session_factory=self.session_factory,
                storage=MinioTranscriptStorage.from_settings(self.settings),
            )
        )

    def _micro_event_executor(self) -> MicroEventExtractionExecutor:
        return MicroEventExtractionExecutor(
            LegacyMicroEventProcessor(
                session_factory=self.session_factory,
                use_case_factory=lambda session: micro_event_use_case(
                    session,
                    self.session_factory,
                    self.settings,
                ),
            )
        )

    def _timeline_executor(self) -> TimelineCompositionExecutor:
        return TimelineCompositionExecutor(
            LegacyTimelineProcessor(
                session_factory=self.session_factory,
                use_case_factory=lambda session: timeline_use_case(
                    session,
                    self.session_factory,
                    self.settings,
                ),
            )
        )

    def _archive_executor(self) -> ArchivePublishExecutor:
        return ArchivePublishExecutor(
            LegacyArchivePublisher(
                session_factory=self.session_factory,
                use_case_factory=lambda session: archive_publish_use_case(session, self.settings),
            )
        )
