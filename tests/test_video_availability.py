from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import httpx

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.video_availability.ports import (
    VideoAvailabilityCandidate,
    VideoAvailabilityCandidateInboxPort,
    VideoAvailabilityResolution,
    VideoPendingWorkCancelerPort,
)
from codex_sdk_cli.domains.video_availability.use_cases import (
    ProcessVideoAvailabilityCandidatesResult,
    ProcessVideoAvailabilityCandidatesUseCase,
    VerifyVideoAvailabilityUseCase,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeDataClientPort,
    YouTubeVideoDetails,
    YouTubeVideoDetailsBatch,
)
from codex_sdk_cli.infra.video_availability.client import (
    VideoAvailabilityCandidateClient,
)
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.video_availability import run_worker


def test_video_availability_worker_is_disabled_by_default() -> None:
    asyncio.run(run_worker(settings=CliSettings(), stop_after_one=True))


def test_video_availability_worker_cleans_on_startup() -> None:
    runtime = _WorkerRuntime()

    asyncio.run(
        run_worker(
            settings=CliSettings(archive_video_availability_enabled=True),
            runtime=runtime,
            stop_after_one=True,
        )
    )

    assert runtime.cleanup_count == 1
    assert runtime.process_count == 1
    assert runtime.closed is True


def test_candidate_batch_uses_one_youtube_call_and_resolves_mixed_results() -> None:
    videos = _Videos([_video(index) for index in range(50)])
    youtube = _YouTubeData(
        statuses={
            **{f"video-{index:05d}": True for index in range(50)},
            "video-00001": False,
        },
        omitted={"video-00002"},
    )
    inbox = _Inbox(
        tuple(
            VideoAvailabilityCandidate(
                candidate_id=index + 1,
                lease_token=f"lease-{index}",
                environment="prod",
                video_id=index + 1,
                youtube_video_id=f"video-{index:05d}",
            )
            for index in range(50)
        )
    )
    pending_work = _PendingWork()
    use_case = ProcessVideoAvailabilityCandidatesUseCase(
        inbox=cast(VideoAvailabilityCandidateInboxPort, inbox),
        verifier=VerifyVideoAvailabilityUseCase(
            videos=cast(VideoRepositoryPort, videos),
            video_tasks=cast(VideoTaskRepositoryPort, _VideoTasks()),
            pending_work=cast(VideoPendingWorkCancelerPort, pending_work),
            youtube_data=cast(YouTubeDataClientPort, youtube),
            events=cast(OperationEventRecorderPort, _Events()),
        ),
        worker_id="worker-1",
        claim_limit=50,
        lease_seconds=120,
    )

    result = asyncio.run(use_case.execute_once())

    assert youtube.calls == 1
    assert len(youtube.requested_ids[0]) == 50
    assert result.claimed_count == 50
    assert result.available_count == 48
    assert result.unavailable_count == 2
    assert result.retry_count == 0
    assert inbox.claim_args == ("worker-1", 50, 120)
    assert {item.reason for item in inbox.resolutions if item.outcome == "unavailable"} == {
        "not_embeddable",
        "not_returned",
    }
    assert videos.by_youtube_id["video-00001"].is_embeddable is False
    assert videos.by_youtube_id["video-00002"].is_embeddable is False
    assert pending_work.outcomes == ["not_embeddable", "not_returned"]


def test_youtube_failure_resolves_candidate_as_retry_without_local_update() -> None:
    video = _video(0)
    videos = _Videos([video])
    inbox = _Inbox(
        (
            VideoAvailabilityCandidate(
                candidate_id=1,
                lease_token="lease",
                environment="prod",
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
            ),
        )
    )
    use_case = ProcessVideoAvailabilityCandidatesUseCase(
        inbox=cast(VideoAvailabilityCandidateInboxPort, inbox),
        verifier=VerifyVideoAvailabilityUseCase(
            videos=cast(VideoRepositoryPort, videos),
            video_tasks=cast(VideoTaskRepositoryPort, _VideoTasks()),
            pending_work=cast(VideoPendingWorkCancelerPort, _PendingWork()),
            youtube_data=cast(YouTubeDataClientPort, _FailingYouTubeData()),
            events=cast(OperationEventRecorderPort, _Events()),
        ),
        worker_id="worker-1",
        claim_limit=50,
        lease_seconds=120,
    )

    result = asyncio.run(use_case.execute_once())

    assert result.retry_count == 1
    assert inbox.resolutions[0].reason == "youtube_api_error"
    assert videos.update_count == 0


def test_candidate_client_uses_admin_contract() -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = cast(dict[str, object], json.loads(request.content))
        requests.append((request.url.path, body))
        assert request.headers["authorization"] == "Bearer TOKEN"
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "candidateId": 7,
                            "leaseToken": "lease-7",
                            "environment": "prod",
                            "videoId": 11,
                            "youtubeVideoId": "abcdefghijk",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/cleanup"):
            return httpx.Response(200, json={"recoveredCount": 2})
        return httpx.Response(200, json={"resolvedCount": 1})

    async def exercise() -> tuple[tuple[VideoAvailabilityCandidate, ...], int]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = VideoAvailabilityCandidateClient(
                http_client,
                base_url="https://planetip.test/api/admin/archive/video-availability/",
                admin_token="TOKEN",
            )
            candidates = await client.claim(
                worker_id="worker-1",
                limit=50,
                lease_seconds=120,
            )
            await client.resolve(
                (
                    VideoAvailabilityResolution(
                        candidate_id=7,
                        lease_token="lease-7",
                        outcome="unavailable",
                        reason="not_returned",
                        checked_at=datetime(2026, 7, 19, tzinfo=UTC),
                    ),
                )
            )
            return candidates, await client.cleanup()

    candidates, recovered = asyncio.run(exercise())

    assert candidates[0].youtube_video_id == "abcdefghijk"
    assert recovered == 2
    assert requests[0] == (
        "/api/admin/archive/video-availability/claim",
        {"workerId": "worker-1", "limit": 50, "leaseSeconds": 120},
    )
    assert requests[1][0].endswith("/resolve")
    assert requests[1][1]["results"] == [
        {
            "candidateId": 7,
            "leaseToken": "lease-7",
            "outcome": "unavailable",
            "reason": "not_returned",
            "checkedAt": "2026-07-19T00:00:00+00:00",
        }
    ]
    assert requests[2] == ("/api/admin/archive/video-availability/cleanup", {})


def _video(index: int) -> VideoRecord:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return VideoRecord(
        id=index + 1,
        channel_id=1,
        youtube_video_id=f"video-{index:05d}",
        title=f"Video {index}",
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


class _Videos:
    def __init__(self, videos: list[VideoRecord]) -> None:
        self.by_youtube_id = {video.youtube_video_id: video for video in videos}
        self.update_count = 0

    async def get_video_by_youtube_video_id(
        self,
        youtube_video_id: str,
    ) -> VideoRecord | None:
        return self.by_youtube_id.get(youtube_video_id)

    async def update_embed_status(
        self,
        video_id: int,
        *,
        is_embeddable: bool | None,
        checked_at: datetime,
        source_api_call_id: int | None,
    ) -> VideoRecord:
        current = next(video for video in self.by_youtube_id.values() if video.id == video_id)
        updated = replace(
            current,
            is_embeddable=is_embeddable,
            embed_status_checked_at=checked_at,
            source_embed_status_api_call_id=source_api_call_id,
        )
        self.by_youtube_id[updated.youtube_video_id] = updated
        self.update_count += 1
        return updated


class _VideoTasks:
    async def cancel_pending_tasks_for_video(self, **_kwargs: object) -> list[object]:
        return []


class _PendingWork:
    def __init__(self) -> None:
        self.outcomes: list[str] = []

    async def execute(self, **kwargs: object) -> int:
        self.outcomes.append(cast(str, kwargs["outcome_code"]))
        return 1


class _YouTubeData:
    def __init__(self, *, statuses: dict[str, bool], omitted: set[str]) -> None:
        self.statuses = statuses
        self.omitted = omitted
        self.calls = 0
        self.requested_ids: list[tuple[str, ...]] = []

    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        del pipeline_job_attempt_id
        self.calls += 1
        self.requested_ids.append(youtube_video_ids)
        return YouTubeVideoDetailsBatch(
            videos=tuple(
                YouTubeVideoDetails(
                    youtube_video_id=youtube_video_id,
                    duration=None,
                    source_api_call_id=99,
                    is_embeddable=self.statuses[youtube_video_id],
                )
                for youtube_video_id in youtube_video_ids
                if youtube_video_id not in self.omitted
            ),
            source_api_call_id=99,
        )


class _FailingYouTubeData:
    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        del youtube_video_ids, pipeline_job_attempt_id
        raise RuntimeError("upstream unavailable")


class _Inbox:
    def __init__(self, candidates: tuple[VideoAvailabilityCandidate, ...]) -> None:
        self.candidates = candidates
        self.claim_args: tuple[str, int, int] | None = None
        self.resolutions: tuple[VideoAvailabilityResolution, ...] = ()

    async def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[VideoAvailabilityCandidate, ...]:
        self.claim_args = (worker_id, limit, lease_seconds)
        return self.candidates[:limit]

    async def resolve(
        self,
        resolutions: tuple[VideoAvailabilityResolution, ...],
    ) -> None:
        self.resolutions = resolutions


class _Events:
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


class _WorkerRuntime:
    def __init__(self) -> None:
        self.cleanup_count = 0
        self.process_count = 0
        self.closed = False

    async def cleanup(self) -> int:
        self.cleanup_count += 1
        return 0

    async def process_once(self) -> ProcessVideoAvailabilityCandidatesResult:
        self.process_count += 1
        return ProcessVideoAvailabilityCandidatesResult(0, 0, 0, 0)

    async def close(self) -> None:
        self.closed = True
