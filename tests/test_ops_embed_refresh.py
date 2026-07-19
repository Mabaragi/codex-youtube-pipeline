from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.ops.ports import OpsPendingWorkCancelerPort
from codex_sdk_cli.domains.ops.schemas import OpsRefreshVideoEmbedStatusRequest
from codex_sdk_cli.domains.ops.use_cases import RefreshOpsVideoEmbedStatusUseCase
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeDataClientPort,
    YouTubeVideoDetails,
    YouTubeVideoDetailsBatch,
)


def test_embed_refresh_cancels_pending_unified_work() -> None:
    now = datetime.now(UTC)
    video = VideoRecord(
        id=1,
        channel_id=1,
        youtube_video_id="abcdefghijk",
        title="Test",
        description="",
        published_at=now,
        duration=None,
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=now,
        updated_at=now,
    )
    videos = _Videos(video)
    pending_work = _PendingWork()
    events = _Events()
    use_case = RefreshOpsVideoEmbedStatusUseCase(
        videos=cast(VideoRepositoryPort, videos),
        video_tasks=cast(VideoTaskRepositoryPort, _VideoTasks()),
        pending_work=cast(OpsPendingWorkCancelerPort, pending_work),
        youtube_data=cast(YouTubeDataClientPort, _YouTubeData()),
        events=cast(OperationEventRecorderPort, events),
    )

    result = asyncio.run(
        use_case.execute(OpsRefreshVideoEmbedStatusRequest(videoIds=[video.id], limit=1))
    )

    assert result.updated_count == 1
    assert result.items[0].is_embeddable is False
    assert result.items[0].canceled_pending_task_count == 1
    assert pending_work.outcome_code == "not_embeddable"
    assert pending_work.subject_id == video.id
    assert events.events[0].metadata_json["canceledPendingTaskCount"] == 1


def test_embed_refresh_marks_video_omitted_by_youtube_as_unavailable() -> None:
    now = datetime.now(UTC)
    video = VideoRecord(
        id=1,
        channel_id=1,
        youtube_video_id="abcdefghijk",
        title="Test",
        description="",
        published_at=now,
        duration=None,
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=now,
        updated_at=now,
    )
    videos = _Videos(video)
    pending_work = _PendingWork()
    use_case = RefreshOpsVideoEmbedStatusUseCase(
        videos=cast(VideoRepositoryPort, videos),
        video_tasks=cast(VideoTaskRepositoryPort, _VideoTasks()),
        pending_work=cast(OpsPendingWorkCancelerPort, pending_work),
        youtube_data=cast(YouTubeDataClientPort, _MissingYouTubeData()),
        events=cast(OperationEventRecorderPort, _Events()),
    )

    result = asyncio.run(
        use_case.execute(OpsRefreshVideoEmbedStatusRequest(videoIds=[video.id], limit=1))
    )

    assert result.updated_count == 1
    assert result.failed_count == 0
    assert result.items[0].is_embeddable is False
    assert result.items[0].source_api_call_id == 778
    assert pending_work.outcome_code == "not_returned"


class _Videos:
    def __init__(self, video: VideoRecord) -> None:
        self.video = video

    async def list_videos_for_embed_status_refresh(
        self,
        *,
        video_ids: tuple[int, ...] | None,
        limit: int,
    ) -> list[VideoRecord]:
        assert video_ids == (self.video.id,)
        assert limit == 1
        return [self.video]

    async def get_video_by_youtube_video_id(
        self,
        youtube_video_id: str,
    ) -> VideoRecord | None:
        return self.video if youtube_video_id == self.video.youtube_video_id else None

    async def update_embed_status(
        self,
        video_id: int,
        *,
        is_embeddable: bool | None,
        checked_at: datetime,
        source_api_call_id: int | None,
    ) -> VideoRecord:
        assert video_id == self.video.id
        self.video = replace(
            self.video,
            is_embeddable=is_embeddable,
            embed_status_checked_at=checked_at,
            source_embed_status_api_call_id=source_api_call_id,
        )
        return self.video


class _VideoTasks:
    async def cancel_pending_tasks_for_video(self, **_kwargs: object) -> list[object]:
        return []


class _PendingWork:
    subject_id: int | None = None
    outcome_code: str | None = None

    async def execute(self, **kwargs: object) -> int:
        self.subject_id = cast(int, kwargs["subject_id"])
        self.outcome_code = cast(str, kwargs["outcome_code"])
        return 1


class _YouTubeData:
    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        del pipeline_job_attempt_id
        return YouTubeVideoDetailsBatch(
            videos=(
                YouTubeVideoDetails(
                    youtube_video_id=youtube_video_ids[0],
                    duration=None,
                    source_api_call_id=777,
                    is_embeddable=False,
                ),
            ),
            source_api_call_id=777,
        )


class _MissingYouTubeData:
    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        del youtube_video_ids, pipeline_job_attempt_id
        return YouTubeVideoDetailsBatch(videos=(), source_api_call_id=778)


class _Events:
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)
