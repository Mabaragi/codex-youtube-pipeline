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
from codex_sdk_cli.domains.archive_publish.use_cases import (
    ArchivePublishStorageFactory,
    ArchivePublishUseCase,
)
from codex_sdk_cli.infra.archive_publish.storage import R2ArchivePublishStorage
from codex_sdk_cli.settings import CliSettings


def archive_publish_storage_factory(
    settings: CliSettings,
) -> ArchivePublishStorageFactory | None:
    if (
        settings.archive_publish_r2_endpoint is None
        or settings.archive_publish_r2_access_key is None
        or settings.archive_publish_r2_secret_key is None
        or settings.archive_publish_r2_bucket is None
        or settings.archive_publish_public_base_url is None
    ):
        return None
    return lambda: R2ArchivePublishStorage.from_settings(settings)


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
    )


ArchivePublishUseCaseDep = Annotated[
    ArchivePublishUseCase,
    Depends(get_archive_publish_use_case),
]
