from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ArchivePublishRepositoryDep,
    MicroEventExtractionRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    TimelineCompositionRepositoryDep,
    TranscriptCueRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
)
from codex_sdk_cli.domains.archive_publish.schemas import ArchivePublishModeLiteral
from codex_sdk_cli.domains.archive_publish.use_cases import (
    ArchivePublishStorageFactory,
    ArchivePublishUseCase,
)
from codex_sdk_cli.infra.archive_publish.public_catalog import (
    HttpArchivePublicCatalogSync,
)
from codex_sdk_cli.infra.archive_publish.storage import R2ArchivePublishStorage
from codex_sdk_cli.settings import CliSettings


def archive_publish_storage_factory(
    settings: CliSettings,
    publish_mode: ArchivePublishModeLiteral = "prod",
) -> ArchivePublishStorageFactory | None:
    if publish_mode == "dev":
        return _dev_archive_publish_storage_factory(settings)
    if (
        settings.archive_publish_r2_endpoint is None
        or settings.archive_publish_r2_access_key is None
        or settings.archive_publish_r2_secret_key is None
        or settings.archive_publish_r2_bucket is None
        or settings.archive_publish_public_base_url is None
    ):
        return None
    return lambda: R2ArchivePublishStorage.from_settings(settings)


def _dev_archive_publish_storage_factory(
    settings: CliSettings,
) -> ArchivePublishStorageFactory | None:
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
    if (
        endpoint is None
        or access_key is None
        or secret_key is None
        or bucket is None
        or public_base_url is None
    ):
        return None
    return lambda: R2ArchivePublishStorage.from_values(
        endpoint=endpoint,
        access_key=access_key.get_secret_value(),
        secret_key=secret_key.get_secret_value(),
        bucket=bucket,
        public_base_url=public_base_url,
        secure=secure,
    )


def get_archive_publish_use_case(
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    timelines: TimelineCompositionRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    transcript_cues: TranscriptCueRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    archive: ArchivePublishRepositoryDep,
    events: OperationEventRecorderDep,
    settings: SettingsDep,
) -> ArchivePublishUseCase:
    return ArchivePublishUseCase(
        videos=videos,
        video_tasks=video_tasks,
        timelines=timelines,
        micro_events=micro_events,
        transcript_cues=transcript_cues,
        pipeline_jobs=pipeline_jobs,
        archive=archive,
        events=events,
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
        dev_storage_factory=archive_publish_storage_factory(settings, publish_mode="dev"),
        dev_storage_bucket=settings.archive_publish_dev_r2_bucket,
        dev_storage_endpoint=(
            settings.archive_publish_dev_r2_endpoint or settings.archive_publish_r2_endpoint
        ),
        public_catalog_sync=(
            HttpArchivePublicCatalogSync(
                url=settings.archive_public_catalog_sync_url,
                token=settings.archive_public_catalog_sync_token.get_secret_value(),
                timeout_seconds=settings.archive_public_catalog_sync_timeout_seconds,
            )
            if settings.archive_public_catalog_sync_enabled
            and settings.archive_public_catalog_sync_url is not None
            and settings.archive_public_catalog_sync_token is not None
            else None
        ),
        public_catalog_sync_enabled=settings.archive_public_catalog_sync_enabled,
    )


ArchivePublishUseCaseDep = Annotated[
    ArchivePublishUseCase,
    Depends(get_archive_publish_use_case),
]
