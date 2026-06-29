from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import VideoTaskRepositoryDep
from codex_sdk_cli.api.use_case_dependencies.archive_publish import (
    ArchivePublishUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.micro_events import (
    ExtractVideoMicroEventsUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.timelines import ComposeTimelineUseCaseDep
from codex_sdk_cli.domains.process_publish.use_cases import ProcessToPublishUseCase


def get_process_to_publish_use_case(
    micro_events: ExtractVideoMicroEventsUseCaseDep,
    timelines: ComposeTimelineUseCaseDep,
    archive_publish: ArchivePublishUseCaseDep,
    video_tasks: VideoTaskRepositoryDep,
) -> ProcessToPublishUseCase:
    return ProcessToPublishUseCase(
        micro_events=micro_events,
        timelines=timelines,
        archive_publish=archive_publish,
        video_tasks=video_tasks,
    )


ProcessToPublishUseCaseDep = Annotated[
    ProcessToPublishUseCase,
    Depends(get_process_to_publish_use_case),
]
