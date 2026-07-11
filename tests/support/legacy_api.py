"""Legacy HTTP adapters used only to preserve deep domain regression tests.

The production application deliberately does not mount these routes. Tests that
exercise legacy use cases through HTTP use this app while the public-contract
tests continue to use ``codex_sdk_cli.api.main.create_app``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, status

from codex_sdk_cli.api.main import create_app as create_production_app
from codex_sdk_cli.api.routes.domain_knowledge import router as domain_knowledge_router
from codex_sdk_cli.api.routes.pipeline_jobs import router as pipeline_jobs_router
from codex_sdk_cli.api.routes.prompts import router as prompts_router
from codex_sdk_cli.api.routes.streamers import router as streamers_router
from codex_sdk_cli.api.routes.video_tasks import router as video_tasks_router
from codex_sdk_cli.api.routes.videos import router as videos_router
from codex_sdk_cli.api.routes.youtube_transcripts import router as transcripts_read_router
from codex_sdk_cli.api.use_case_dependencies.archive_publish import ArchivePublishUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.channels import (
    CreateChannelUseCaseDep,
    DeleteChannelUseCaseDep,
    GetChannelUseCaseDep,
    ListChannelsUseCaseDep,
    ListStreamerChannelsUseCaseDep,
    ResolveYouTubeChannelUseCaseDep,
    UpdateChannelUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.micro_events import ExtractVideoMicroEventsUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.ops import ListOpsVideoTasksUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.timelines import (
    ComposeTimelineUseCaseDep,
    PatchTimelineUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.video_tasks import GenerateTranscriptCueTasksUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.youtube_transcripts import (
    FetchYouTubeTranscriptUseCaseDep,
)
from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchivePublishRequest,
    ArchivePublishResponse,
)
from codex_sdk_cli.domains.channels.schemas import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    DeleteResponse,
    ResolveYouTubeChannelRequest,
    ResolveYouTubeChannelResponse,
)
from codex_sdk_cli.domains.micro_events.schemas import (
    MicroEventBatchExtractRequest,
    MicroEventBatchExtractResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
    MicroEventExtractionDetailResponse,
    MicroEventExtractRequest,
    MicroEventExtractResponse,
)
from codex_sdk_cli.domains.ops.schemas import OpsVideoTaskListResponse
from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
    TimelineCompositionResponse,
    TimelinePatchRequest,
    TimelinePatchResponse,
)
from codex_sdk_cli.domains.transcript_cues.schemas import TranscriptCueGenerateResponse
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptRequest, TranscriptResponse

legacy_router = APIRouter()


@legacy_router.post(
    "/streamers/{streamer_id}/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_streamer_channel(
    streamer_id: Annotated[int, Path(ge=1)],
    request: ChannelCreateRequest,
    use_case: CreateChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(streamer_id, request)


@legacy_router.get(
    "/streamers/{streamer_id}/channels",
    response_model=list[ChannelResponse],
)
async def list_streamer_channels(
    streamer_id: Annotated[int, Path(ge=1)],
    use_case: ListStreamerChannelsUseCaseDep,
) -> list[ChannelResponse]:
    return await use_case.execute(streamer_id)


@legacy_router.post(
    "/streamers/{streamer_id}/channels/resolve",
    response_model=ResolveYouTubeChannelResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["channels"],
)
async def resolve_streamer_channel(
    streamer_id: Annotated[int, Path(ge=1)],
    request: ResolveYouTubeChannelRequest,
    use_case: ResolveYouTubeChannelUseCaseDep,
) -> ResolveYouTubeChannelResponse:
    return await use_case.execute(streamer_id, request)


@legacy_router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(use_case: ListChannelsUseCaseDep) -> list[ChannelResponse]:
    return await use_case.execute()


@legacy_router.get("/channels/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: GetChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(channel_id)


@legacy_router.patch("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: Annotated[int, Path(ge=1)],
    request: ChannelUpdateRequest,
    use_case: UpdateChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(channel_id, request)


@legacy_router.delete("/channels/{channel_id}", response_model=DeleteResponse)
async def delete_channel(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: DeleteChannelUseCaseDep,
) -> DeleteResponse:
    return await use_case.execute(channel_id)


@legacy_router.post(
    "/videos/{video_id}/video-tasks/micro-event-extract",
    response_model=MicroEventExtractResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["micro-events"],
)
async def extract_video_micro_events(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventExtractRequest | None, Body()] = None,
) -> MicroEventExtractResponse:
    return await use_case.execute(video_id, request or MicroEventExtractRequest())


@legacy_router.post(
    "/video-tasks/micro-event-extract",
    response_model=MicroEventBatchExtractResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["micro-events"],
)
async def extract_all_video_micro_events(
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventBatchExtractRequest | None, Body()] = None,
) -> MicroEventBatchExtractResponse:
    return await use_case.execute_all(request or MicroEventBatchExtractRequest())


@legacy_router.post(
    "/video-tasks/micro-event-extract/enqueue",
    response_model=MicroEventEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["micro-events"],
)
async def enqueue_video_micro_events(
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventEnqueueRequest | None, Body()] = None,
) -> MicroEventEnqueueResponse:
    return await use_case.enqueue(request or MicroEventEnqueueRequest())


@legacy_router.get(
    "/videos/{video_id}/micro-event-extractions/latest",
    response_model=MicroEventExtractionDetailResponse,
    tags=["micro-events"],
)
async def get_latest_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_latest(video_id)


@legacy_router.get(
    "/videos/{video_id}/micro-event-extractions/{video_task_id}",
    response_model=MicroEventExtractionDetailResponse,
    tags=["micro-events"],
)
async def get_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    video_task_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=video_task_id)


@legacy_router.post(
    "/video-tasks/timeline-compose/enqueue",
    response_model=TimelineComposeEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["timelines"],
)
async def enqueue_timeline_compose(
    use_case: ComposeTimelineUseCaseDep,
    request: Annotated[TimelineComposeEnqueueRequest | None, Body()] = None,
) -> TimelineComposeEnqueueResponse:
    return await use_case.enqueue(request or TimelineComposeEnqueueRequest())


@legacy_router.get(
    "/videos/{video_id}/timelines/latest",
    response_model=TimelineCompositionResponse,
    tags=["timelines"],
)
async def get_latest_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_latest(video_id)


@legacy_router.get(
    "/videos/{video_id}/timelines/{video_task_id}",
    response_model=TimelineCompositionResponse,
    tags=["timelines"],
)
async def get_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    video_task_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=video_task_id)


@legacy_router.post(
    "/videos/{videoId}/timelines/{videoTaskId}/patch",
    response_model=TimelinePatchResponse,
    tags=["timelines"],
)
async def patch_video_timeline(
    video_id: Annotated[int, Path(ge=1, alias="videoId")],
    video_task_id: Annotated[int, Path(ge=1, alias="videoTaskId")],
    request: TimelinePatchRequest,
    use_case: PatchTimelineUseCaseDep,
) -> TimelinePatchResponse:
    return await use_case.execute(
        video_id=video_id,
        video_task_id=video_task_id,
        request=request,
    )


@legacy_router.post(
    "/video-tasks/archive-publish",
    response_model=ArchivePublishResponse,
)
async def publish_archive(
    use_case: ArchivePublishUseCaseDep,
    request: Annotated[ArchivePublishRequest | None, Body()] = None,
) -> ArchivePublishResponse:
    return await use_case.publish(request or ArchivePublishRequest())


@legacy_router.get("/ops/video-tasks", response_model=OpsVideoTaskListResponse)
async def list_ops_video_tasks(
    use_case: ListOpsVideoTasksUseCaseDep,
    channel_id: int | None = Query(default=None, alias="channelId", ge=1),
    task_name: str | None = Query(default=None, alias="taskName", min_length=1),
    task_status: str | None = Query(default=None, alias="status", min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> OpsVideoTaskListResponse:
    return await use_case.execute(
        channel_id=channel_id,
        task_name=task_name,
        status=task_status,
        limit=limit,
        offset=offset,
    )


transcript_write_router = APIRouter()


@transcript_write_router.post("", response_model=TranscriptResponse)
async def fetch_youtube_transcript(
    request: TranscriptRequest,
    use_case: FetchYouTubeTranscriptUseCaseDep,
) -> TranscriptResponse:
    return await use_case.execute(request)


@transcript_write_router.post(
    "/{transcript_id}/cues/generate",
    response_model=TranscriptCueGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_youtube_transcript_cues(
    transcript_id: Annotated[int, Path(ge=1)],
    use_case: GenerateTranscriptCueTasksUseCaseDep,
) -> TranscriptCueGenerateResponse:
    return await use_case.execute_for_transcript(transcript_id)


def create_legacy_app():
    app = create_production_app()
    app.include_router(domain_knowledge_router, tags=["domain-knowledge"])
    app.include_router(prompts_router, tags=["prompts"])
    app.include_router(streamers_router, tags=["streamers"])
    app.include_router(videos_router, tags=["videos"])
    app.include_router(video_tasks_router, tags=["video-tasks"])
    app.include_router(pipeline_jobs_router, prefix="/pipeline", tags=["pipeline-jobs"])
    app.include_router(legacy_router)
    app.include_router(
        transcripts_read_router,
        prefix="/youtube-transcripts",
        tags=["youtube-transcripts"],
    )
    app.include_router(
        transcript_write_router,
        prefix="/youtube-transcripts",
        tags=["youtube-transcripts"],
    )
    return app


app = create_legacy_app()
