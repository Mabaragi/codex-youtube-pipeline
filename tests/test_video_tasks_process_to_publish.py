from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.process_publish import (
    get_process_to_publish_use_case,
)
from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchivePublishItemResponse,
    ArchivePublishRequest,
    ArchivePublishResponse,
)
from codex_sdk_cli.domains.micro_events.schemas import (
    MicroEventEnqueueItemResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
)
from codex_sdk_cli.domains.process_publish.schemas import (
    ProcessToPublishItemResponse,
    ProcessToPublishRequest,
    ProcessToPublishResponse,
    ProcessToPublishStageResponse,
)
from codex_sdk_cli.domains.process_publish.use_cases import ProcessToPublishUseCase
from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueItemResponse,
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord, VideoTaskStatus


@dataclass(slots=True)
class FakeMicroEvents:
    response: MicroEventEnqueueResponse
    requests: list[MicroEventEnqueueRequest] = field(default_factory=list)

    async def enqueue(self, request: MicroEventEnqueueRequest) -> MicroEventEnqueueResponse:
        self.requests.append(request)
        return self.response


@dataclass(slots=True)
class FakeTimelines:
    response: TimelineComposeEnqueueResponse
    requests: list[TimelineComposeEnqueueRequest] = field(default_factory=list)

    async def enqueue(
        self,
        request: TimelineComposeEnqueueRequest,
    ) -> TimelineComposeEnqueueResponse:
        self.requests.append(request)
        return self.response


@dataclass(slots=True)
class FakeArchivePublish:
    response: ArchivePublishResponse
    requests: list[ArchivePublishRequest] = field(default_factory=list)

    async def publish(self, request: ArchivePublishRequest) -> ArchivePublishResponse:
        self.requests.append(request)
        return self.response


@dataclass(slots=True)
class FakeVideoTasks:
    tasks: dict[int, VideoTaskRecord]
    requested: list[int] = field(default_factory=list)

    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        self.requested.append(task_id)
        return self.tasks.get(task_id)


@dataclass(slots=True)
class FakeProcessToPublishRouteUseCase:
    request: ProcessToPublishRequest | None = None

    async def execute(
        self,
        request: ProcessToPublishRequest,
    ) -> ProcessToPublishResponse:
        self.request = request
        return ProcessToPublishResponse(
            requestedCount=1,
            microSucceededCount=1,
            timelineSucceededCount=1,
            publishedCount=1,
            failedCount=0,
            skippedCount=0,
            items=[
                ProcessToPublishItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    status="succeeded",
                    reason="published",
                    publish=ProcessToPublishStageResponse(
                        videoTaskId=30,
                        status="succeeded",
                        reason="published",
                        publicUrl="https://cdn/video.json",
                    ),
                )
            ],
        )


@dataclass(slots=True)
class AdvancingClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def test_process_to_publish_api_route() -> None:
    asyncio.run(_test_process_to_publish_api_route())


async def _test_process_to_publish_api_route() -> None:
    use_case = FakeProcessToPublishRouteUseCase()
    app = create_app()
    app.dependency_overrides[get_process_to_publish_use_case] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/video-tasks/process-to-publish",
            json={
                "videoIds": [1],
                "microReasoning": "high",
                "timelineReasoning": "medium",
                "retryFailed": True,
                "publishMode": "dev",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["publish"]["publicUrl"] == "https://cdn/video.json"
    assert use_case.request is not None
    assert use_case.request.micro_reasoning == "high"
    assert use_case.request.retry_failed is True
    assert use_case.request.publish_mode == "dev"


def test_process_to_publish_runs_successful_stages_and_publish() -> None:
    result = asyncio.run(_process_success())

    assert result["payload"]["items"][0]["status"] == "succeeded"
    assert result["payload"]["items"][0]["publish"]["publicUrl"] == "https://cdn/video.json"
    assert result["micro"].requests[0].retry_failed is True
    assert result["micro"].requests[0].reasoning_effort == "high"
    assert result["timeline"].requests[0].reasoning_effort == "medium"
    assert result["archive"].requests[0].video_ids == [1]
    assert result["archive"].requests[0].retry_failed is True
    assert result["archive"].requests[0].publish_mode == "dev"
    assert result["archive"].requests[0].environment == "dev"
    assert result["archive"].requests[0].variant == "dev-preview"


async def _process_success():
    micro = FakeMicroEvents(
        MicroEventEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=1,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=0,
            skippedFailedCount=0,
            ineligibleCount=0,
            items=[
                MicroEventEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=10,
                    status="pending",
                    reason="enqueued",
                    model="gpt-5.5",
                    reasoningEffort="high",
                    transcriptId=3,
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )
    )
    timeline = FakeTimelines(
        TimelineComposeEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=1,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=0,
            retryQueuedCount=0,
            regeneratedCount=0,
            failedSkippedCount=0,
            ineligibleCount=0,
            items=[
                TimelineComposeEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=20,
                    status="pending",
                    reason="enqueued",
                    sourceMicroEventTaskId=10,
                    model="gpt-5.5",
                    reasoningEffort="medium",
                    copyStyle="LIGHT_FANDOM_V1",
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )
    )
    archive = FakeArchivePublish(
        ArchivePublishResponse(
            requestedCount=1,
            scannedCount=1,
            processedCount=1,
            publishedCount=1,
            alreadyPublishedCount=0,
            regeneratedCount=0,
            failedCount=0,
            failedSkippedCount=0,
            ineligibleCount=0,
            items=[
                ArchivePublishItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=30,
                    status="succeeded",
                    reason="published",
                    sourceTimelineTaskId=20,
                    sourceTimelineCompositionId=40,
                    environment="prod",
                    variant="control",
                    schemaVersion=1,
                    artifactId=50,
                    publicUrl="https://cdn/video.json",
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )
    )
    use_case = ProcessToPublishUseCase(
        micro_events=micro,
        timelines=timeline,
        archive_publish=archive,
        video_tasks=FakeVideoTasks(
            {
                10: _task(10, 1, "micro_event_extract", "succeeded"),
                20: _task(20, 1, "timeline_compose", "succeeded"),
            }
        ),
    )
    response = await use_case.execute(
        ProcessToPublishRequest(
            videoIds=[1],
            retryFailed=True,
            microReasoning="high",
            timelineReasoning="medium",
            publishMode="dev",
        )
    )
    return {
        "payload": response.model_dump(by_alias=True, mode="json"),
        "micro": micro,
        "timeline": timeline,
        "archive": archive,
    }


def test_process_to_publish_skips_after_micro_failure() -> None:
    payload, timeline, archive = asyncio.run(_process_micro_failure())

    assert payload["items"][0]["status"] == "skipped"
    assert payload["items"][0]["reason"] == "previously_failed"
    assert timeline.requests == []
    assert archive.requests == []


async def _process_micro_failure():
    micro = FakeMicroEvents(
        MicroEventEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=0,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=0,
            skippedFailedCount=1,
            ineligibleCount=0,
            items=[
                MicroEventEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=10,
                    status="skipped",
                    reason="previously_failed",
                    model="gpt-5.5",
                    reasoningEffort="medium",
                    transcriptId=3,
                    errorType="ValidationError",
                    errorMessage="invalid",
                )
            ],
        )
    )
    timeline = FakeTimelines(_empty_timeline_response())
    archive = FakeArchivePublish(_empty_archive_response())
    use_case = ProcessToPublishUseCase(
        micro_events=micro,
        timelines=timeline,
        archive_publish=archive,
        video_tasks=FakeVideoTasks({}),
    )
    response = await use_case.execute(ProcessToPublishRequest(videoIds=[1]))
    return response.model_dump(by_alias=True, mode="json"), timeline, archive


def test_process_to_publish_skips_publish_after_timeline_failure() -> None:
    payload, archive = asyncio.run(_process_timeline_failure())

    assert payload["items"][0]["status"] == "skipped"
    assert payload["items"][0]["reason"] == "failed_skipped"
    assert archive.requests == []


async def _process_timeline_failure():
    micro = FakeMicroEvents(
        MicroEventEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=0,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=1,
            skippedFailedCount=0,
            ineligibleCount=0,
            items=[
                MicroEventEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=10,
                    status="skipped",
                    reason="already_succeeded",
                    model="gpt-5.5",
                    reasoningEffort="medium",
                    transcriptId=3,
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )
    )
    timeline = FakeTimelines(
        TimelineComposeEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=0,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=0,
            retryQueuedCount=0,
            regeneratedCount=0,
            failedSkippedCount=1,
            ineligibleCount=0,
            items=[
                TimelineComposeEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=20,
                    status="failed",
                    reason="failed_skipped",
                    sourceMicroEventTaskId=10,
                    model="gpt-5.5",
                    reasoningEffort="medium",
                    copyStyle="LIGHT_FANDOM_V1",
                    errorType="TimelineError",
                    errorMessage="failed",
                )
            ],
        )
    )
    archive = FakeArchivePublish(_empty_archive_response())
    use_case = ProcessToPublishUseCase(
        micro_events=micro,
        timelines=timeline,
        archive_publish=archive,
        video_tasks=FakeVideoTasks({10: _task(10, 1, "micro_event_extract", "succeeded")}),
    )
    response = await use_case.execute(ProcessToPublishRequest(videoIds=[1]))
    return response.model_dump(by_alias=True, mode="json"), archive


def test_process_to_publish_micro_wait_timeout_does_not_cancel_task() -> None:
    payload, video_tasks = asyncio.run(_process_micro_timeout())

    assert payload["items"][0]["status"] == "failed"
    assert payload["items"][0]["reason"] == "micro_wait_timeout"
    assert payload["items"][0]["micro"]["status"] == "wait_timeout"
    assert video_tasks.tasks[10].status == "running"
    assert video_tasks.requested == [10, 10]


async def _process_micro_timeout():
    micro = FakeMicroEvents(
        MicroEventEnqueueResponse(
            requestedCount=1,
            scannedCount=1,
            enqueuedCount=1,
            alreadyPendingCount=0,
            alreadyRunningCount=0,
            alreadySucceededCount=0,
            skippedFailedCount=0,
            ineligibleCount=0,
            items=[
                MicroEventEnqueueItemResponse(
                    videoId=1,
                    youtubeVideoId="yt-1",
                    videoTaskId=10,
                    status="pending",
                    reason="enqueued",
                    model="gpt-5.5",
                    reasoningEffort="medium",
                    transcriptId=3,
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )
    )
    video_tasks = FakeVideoTasks({10: _task(10, 1, "micro_event_extract", "running")})
    clock = AdvancingClock(datetime(2026, 1, 1, tzinfo=UTC))
    use_case = ProcessToPublishUseCase(
        micro_events=micro,
        timelines=FakeTimelines(_empty_timeline_response()),
        archive_publish=FakeArchivePublish(_empty_archive_response()),
        video_tasks=video_tasks,
        sleep=clock.sleep,
        clock=clock,
    )
    response = await use_case.execute(
        ProcessToPublishRequest(
            videoIds=[1],
            waitTimeoutMinutes=1,
            pollIntervalSeconds=60,
        )
    )
    return response.model_dump(by_alias=True, mode="json"), video_tasks


def _empty_timeline_response() -> TimelineComposeEnqueueResponse:
    return TimelineComposeEnqueueResponse(
        requestedCount=0,
        scannedCount=0,
        enqueuedCount=0,
        alreadyPendingCount=0,
        alreadyRunningCount=0,
        alreadySucceededCount=0,
        retryQueuedCount=0,
        regeneratedCount=0,
        failedSkippedCount=0,
        ineligibleCount=0,
        items=[],
    )


def _empty_archive_response() -> ArchivePublishResponse:
    return ArchivePublishResponse(
        requestedCount=0,
        scannedCount=0,
        processedCount=0,
        publishedCount=0,
        alreadyPublishedCount=0,
        regeneratedCount=0,
        failedCount=0,
        failedSkippedCount=0,
        ineligibleCount=0,
        items=[],
    )


def _task(
    task_id: int,
    video_id: int,
    task_name: str,
    status: str,
) -> VideoTaskRecord:
    now = datetime.now(UTC)
    return VideoTaskRecord(
        id=task_id,
        video_id=video_id,
        task_name=task_name,
        task_version="v1",
        input_hash="hash",
        status=cast(VideoTaskStatus, status),
        worker_id=None,
        timeout_seconds=600,
        job_id=task_id + 100,
        job_attempt_id=task_id + 200,
        output_transcript_id=None,
        output_json=None,
        error_type=None,
        error_message=None,
        started_at=now,
        completed_at=now if status == "succeeded" else None,
        created_at=now,
        updated_at=now,
        input_json={},
    )
