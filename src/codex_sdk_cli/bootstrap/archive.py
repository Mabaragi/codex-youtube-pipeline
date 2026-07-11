from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.archive_publish.schemas import ArchivePublishModeLiteral
from codex_sdk_cli.domains.archive_publish.use_cases import (
    ArchivePublishStorageFactory,
    ArchivePublishUseCase,
)
from codex_sdk_cli.domains.operation_events.recorder import BestEffortOperationEventRecorder
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobRepositoryPort
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.infra.archive_publish.public_catalog import HttpArchivePublicCatalogSync
from codex_sdk_cli.infra.archive_publish.repository import SqlAlchemyArchivePublishRepository
from codex_sdk_cli.infra.archive_publish.storage import R2ArchivePublishStorage
from codex_sdk_cli.infra.micro_events.repository import SqlAlchemyMicroEventExtractionRepository
from codex_sdk_cli.infra.operation_events.repository import SQLAlchemyOperationEventRepository
from codex_sdk_cli.infra.timelines.repository import SqlAlchemyTimelineCompositionRepository
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.work.execution_repositories import (
    WorkPipelineJobRepository,
    WorkVideoTaskRepository,
)
from codex_sdk_cli.settings import CliSettings


def archive_publish_storage_factory(
    settings: CliSettings,
    publish_mode: ArchivePublishModeLiteral = "prod",
) -> ArchivePublishStorageFactory | None:
    if publish_mode == "dev":
        endpoint = settings.archive_publish_dev_r2_endpoint or settings.archive_publish_r2_endpoint
        access_key = (
            settings.archive_publish_dev_r2_access_key or settings.archive_publish_r2_access_key
        )
        secret_key = (
            settings.archive_publish_dev_r2_secret_key or settings.archive_publish_r2_secret_key
        )
        bucket = settings.archive_publish_dev_r2_bucket
        public_base_url = settings.archive_publish_dev_public_base_url
        secure = (
            settings.archive_publish_dev_r2_secure
            if settings.archive_publish_dev_r2_secure is not None
            else settings.archive_publish_r2_secure
        )
        if None in {endpoint, access_key, secret_key, bucket, public_base_url}:
            return None
        assert access_key is not None and secret_key is not None
        assert endpoint is not None and bucket is not None and public_base_url is not None
        return lambda: R2ArchivePublishStorage.from_values(
            endpoint=endpoint,
            access_key=access_key.get_secret_value(),
            secret_key=secret_key.get_secret_value(),
            bucket=bucket,
            public_base_url=public_base_url,
            secure=secure,
        )
    if (
        settings.archive_publish_r2_endpoint is None
        or settings.archive_publish_r2_access_key is None
        or settings.archive_publish_r2_secret_key is None
        or settings.archive_publish_r2_bucket is None
        or settings.archive_publish_public_base_url is None
    ):
        return None
    return lambda: R2ArchivePublishStorage.from_settings(settings)


def archive_publish_use_case(
    session: AsyncSession,
    settings: CliSettings,
    *,
    video_tasks: VideoTaskRepositoryPort | None = None,
    pipeline_jobs: PipelineJobRepositoryPort | None = None,
) -> ArchivePublishUseCase:
    public_catalog = (
        HttpArchivePublicCatalogSync(
            url=settings.archive_public_catalog_sync_url,
            token=settings.archive_public_catalog_sync_token.get_secret_value(),
            timeout_seconds=settings.archive_public_catalog_sync_timeout_seconds,
        )
        if settings.archive_public_catalog_sync_enabled
        and settings.archive_public_catalog_sync_url is not None
        and settings.archive_public_catalog_sync_token is not None
        else None
    )
    return ArchivePublishUseCase(
        videos=SqlAlchemyVideoRepository(session),
        video_tasks=video_tasks or WorkVideoTaskRepository(session),
        timelines=SqlAlchemyTimelineCompositionRepository(session),
        micro_events=SqlAlchemyMicroEventExtractionRepository(session),
        transcript_cues=SqlAlchemyTranscriptCueRepository(session),
        pipeline_jobs=pipeline_jobs or WorkPipelineJobRepository(session),
        archive=SqlAlchemyArchivePublishRepository(session),
        events=BestEffortOperationEventRecorder(SQLAlchemyOperationEventRepository(session)),
        timeout_seconds=settings.archive_publish_timeout_seconds,
        public_base_url=settings.archive_publish_public_base_url,
        prefix=settings.archive_publish_prefix,
        default_environment=settings.archive_publish_environment,
        default_schema_version=1,
        storage_factory=archive_publish_storage_factory(settings),
        storage_bucket=settings.archive_publish_r2_bucket,
        storage_endpoint=settings.archive_publish_r2_endpoint,
        dev_public_base_url=settings.archive_publish_dev_public_base_url,
        dev_prefix=settings.archive_publish_dev_prefix,
        dev_default_environment=settings.archive_publish_dev_environment,
        dev_storage_factory=archive_publish_storage_factory(settings, "dev"),
        dev_storage_bucket=settings.archive_publish_dev_r2_bucket,
        dev_storage_endpoint=(
            settings.archive_publish_dev_r2_endpoint or settings.archive_publish_r2_endpoint
        ),
        public_catalog_sync=public_catalog,
        public_catalog_sync_enabled=settings.archive_public_catalog_sync_enabled,
    )
