from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishConfigurationError,
)
from codex_sdk_cli.domains.archive_publish.use_cases import (
    ArchivePublishUseCase,
)
from codex_sdk_cli.domains.operation_events.recorder import BestEffortOperationEventRecorder
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobRepositoryPort
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    SqlAlchemyArchivePublicationCheckpointRepository,
)
from codex_sdk_cli.infra.archive_publish.repository import SqlAlchemyArchivePublishRepository
from codex_sdk_cli.infra.micro_events.repository import SqlAlchemyMicroEventExtractionRepository
from codex_sdk_cli.infra.operation_events.repository import SQLAlchemyOperationEventRepository
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.infra.publication.stages import PublicationStageService
from codex_sdk_cli.infra.publication_config.repository import (
    SqlAlchemyPublishConfigurationRepository,
)
from codex_sdk_cli.infra.timelines.repository import SqlAlchemyTimelineCompositionRepository
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.work.execution_repositories import (
    WorkPipelineJobRepository,
    WorkVideoTaskRepository,
)
from codex_sdk_cli.settings import CliSettings


def publication_stage_service(
    session: AsyncSession,
    settings: CliSettings,
    *,
    archive_repository: SqlAlchemyArchivePublishRepository | None = None,
) -> PublicationStageService:
    registry_path = settings.publish_connections_file
    if registry_path is None or not registry_path.is_file():
        raise ArchivePublishConfigurationError(
            "Publication connection registry is required; configure "
            "CODEX_CLI_PUBLISH_CONNECTIONS_FILE."
        )
    archive = archive_repository or SqlAlchemyArchivePublishRepository(session)
    return PublicationStageService(
        configuration=SqlAlchemyPublishConfigurationRepository(session),
        checkpoints=SqlAlchemyArchivePublicationCheckpointRepository(session),
        archive=archive,
        connections=PublicationConnectionFactory.from_settings(settings),
        artifact_store_ref=settings.publication_artifact_store_ref,
        staging_store_ref=settings.publication_staging_store_ref,
    )


def archive_publish_use_case(
    session: AsyncSession,
    settings: CliSettings,
    *,
    video_tasks: VideoTaskRepositoryPort | None = None,
    pipeline_jobs: PipelineJobRepositoryPort | None = None,
) -> ArchivePublishUseCase:
    archive_repository = SqlAlchemyArchivePublishRepository(session)
    routed_publication = publication_stage_service(
        session,
        settings,
        archive_repository=archive_repository,
    )
    return ArchivePublishUseCase(
        videos=SqlAlchemyVideoRepository(session),
        video_tasks=video_tasks or WorkVideoTaskRepository(session),
        timelines=SqlAlchemyTimelineCompositionRepository(session),
        micro_events=SqlAlchemyMicroEventExtractionRepository(session),
        transcript_cues=SqlAlchemyTranscriptCueRepository(session),
        pipeline_jobs=pipeline_jobs or WorkPipelineJobRepository(session),
        archive=archive_repository,
        events=BestEffortOperationEventRecorder(SQLAlchemyOperationEventRepository(session)),
        timeout_seconds=settings.archive_publish_timeout_seconds,
        public_base_url=None,
        prefix="archive",
        default_environment=settings.archive_publish_environment,
        default_schema_version=1,
        storage_factory=None,
        storage_bucket=None,
        storage_endpoint=None,
        dev_public_base_url=None,
        dev_prefix="archive-dev",
        dev_default_environment=settings.archive_publish_dev_environment,
        dev_storage_factory=None,
        dev_storage_bucket=None,
        dev_storage_endpoint=None,
        public_catalog_sync=None,
        public_catalog_sync_enabled=False,
        routed_publication=routed_publication,
    )


def archive_publish_execution_use_case(
    session: AsyncSession,
    settings: CliSettings,
    *,
    work_item_id: int,
    work_attempt_id: int,
) -> ArchivePublishUseCase:
    """Build a publisher that leaves current execution state to the work engine."""
    return archive_publish_use_case(
        session,
        settings,
        video_tasks=WorkVideoTaskRepository(
            session,
            current_work_item_id=work_item_id,
        ),
        pipeline_jobs=WorkPipelineJobRepository(
            session,
            current_work_item_id=work_item_id,
            current_work_attempt_id=work_attempt_id,
        ),
    )
