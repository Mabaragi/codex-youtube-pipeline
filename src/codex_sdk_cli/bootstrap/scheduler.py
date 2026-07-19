from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.application.scheduler.use_cases import (
    PipelineSchedulerConfig,
    RunPipelineSchedulerTickUseCase,
)
from codex_sdk_cli.application.transcripts.commands import CollectTranscriptsUseCase
from codex_sdk_cli.application.videos.executors import VideoCollectExecutor
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.workflows.commands import StartProcessToPublishUseCase
from codex_sdk_cli.infra.automation.repository import SqlAlchemyAutomationRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.scheduler import (
    SqlAlchemyPublishedPromptSnapshot,
    SqlAlchemyScheduledChannelReader,
    SqlAlchemySchedulerEventRecorder,
    SqlAlchemyWorkflowAdmissionGuard,
    SqlAlchemyWorkflowCandidateReader,
    WorkVideoCollector,
)
from codex_sdk_cli.infra.work.transcript_execution import YouTubeTranscriptMetadataReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings


class PipelineSchedulerRuntime:
    def __init__(self, settings: CliSettings, *, worker_id: str) -> None:
        self.settings = settings
        self.worker_id = worker_id
        self.database_engine: AsyncEngine = create_database_engine(
            settings.database_url,
            echo=settings.database_echo,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
            self.database_engine
        )

    async def close(self) -> None:
        await self.database_engine.dispose()

    def use_case(self) -> RunPipelineSchedulerTickUseCase:
        def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
            return SqlAlchemyWorkUnitOfWork(self.session_factory)

        inline_runner = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry({"video_collect": self._video_collect_executor}),
            task_types=("video_collect",),
            worker_id=self.worker_id,
        )
        return RunPipelineSchedulerTickUseCase(
            channels=SqlAlchemyScheduledChannelReader(self.session_factory),
            collect_transcripts=CollectTranscriptsUseCase(
                videos=SqlAlchemyVideoSelection(self.session_factory),
                transcripts=YouTubeTranscriptMetadataReader(self.session_factory),
                unit_of_work_factory=unit_of_work_factory,
            ),
            unit_of_work_factory=unit_of_work_factory,
            inline_runner=inline_runner,
            events=SqlAlchemySchedulerEventRecorder(self.session_factory),
            start_workflows=StartProcessToPublishUseCase(
                videos=SqlAlchemyVideoSelection(self.session_factory),
                unit_of_work_factory=unit_of_work_factory,
            ),
            workflow_candidates=SqlAlchemyWorkflowCandidateReader(self.session_factory),
            workflow_admission_guard=SqlAlchemyWorkflowAdmissionGuard(
                self.session_factory
            ),
            automation_state=SqlAlchemyAutomationRepository(self.session_factory),
            prompts=SqlAlchemyPublishedPromptSnapshot(self.session_factory),
            config=PipelineSchedulerConfig(
                channel_interval_seconds=(
                    self.settings.pipeline_scheduler_channel_interval_seconds
                ),
                transcript_limit=self.settings.pipeline_scheduler_transcript_limit,
                no_transcript_recheck_interval_seconds=(
                    self.settings.pipeline_scheduler_no_transcript_recheck_interval_seconds
                ),
                no_transcript_limit=self.settings.pipeline_scheduler_no_transcript_limit,
                workflow_limit=self.settings.pipeline_scheduler_workflow_limit,
                daily_workflow_limit=(
                    self.settings.pipeline_scheduler_daily_workflow_limit
                ),
                channel_daily_minimum=(
                    self.settings.pipeline_scheduler_channel_daily_minimum
                ),
                quota_timezone=self.settings.pipeline_scheduler_quota_timezone,
                transcript_fallback_grace_seconds=(
                    self.settings.pipeline_scheduler_transcript_fallback_grace_seconds
                ),
                transcript_recheck_interval_seconds=(
                    self.settings.pipeline_scheduler_transcript_recheck_interval_seconds
                ),
            ),
        )

    def _video_collect_executor(self) -> VideoCollectExecutor:
        return VideoCollectExecutor(
            WorkVideoCollector(
                session_factory=self.session_factory,
                settings=self.settings,
            )
        )
