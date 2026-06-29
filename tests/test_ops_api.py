from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_codex_usage_repository,
    get_operation_event_repository,
    get_ops_repository,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.codex_usage.ports import (
    CodexUsageCreate,
    CodexUsageJobSummaryRecord,
    CodexUsageListQuery,
    CodexUsageListResult,
    CodexUsageRecord,
    CodexUsageRepositoryPort,
    CodexUsageSummaryRecord,
    CodexUsageVideoSummaryRecord,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventListQuery,
    OperationEventRecord,
    OperationEventRepositoryPort,
)
from codex_sdk_cli.domains.ops.ports import (
    OpsCandidateListQuery,
    OpsChannelRecord,
    OpsLatestEventRecord,
    OpsMicroEventReadyCandidateListResult,
    OpsMicroEventReadyCandidateRecord,
    OpsRecentFailureRecord,
    OpsRepositoryPort,
    OpsSchemaGraphRecord,
    OpsStatusCountRecord,
    OpsStuckTaskListResult,
    OpsStuckTaskQuery,
    OpsStuckTaskRecord,
    OpsSummaryCountsRecord,
    OpsTaskSummaryRecord,
    OpsTimelineReadyCandidateListResult,
    OpsTimelineReadyCandidateRecord,
    OpsVideoCueGenerationRecord,
    OpsVideoDetailRecord,
    OpsVideoGenerationRecord,
    OpsVideoListQuery,
    OpsVideoListResult,
    OpsVideoMicroEventGenerationRecord,
    OpsVideoRecord,
    OpsVideoTaskListQuery,
    OpsVideoTaskListResult,
    OpsVideoTaskRecord,
    OpsVideoTimelineGenerationRecord,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)


class FakeOperationEventRepository(OperationEventRepositoryPort):
    def __init__(self) -> None:
        self.queries: list[OperationEventListQuery] = []

    async def create_event(self, event: OperationEventCreate) -> OperationEventRecord:
        raise NotImplementedError

    async def list_events(self, query: OperationEventListQuery) -> list[OperationEventRecord]:
        self.queries.append(query)
        return [
            OperationEventRecord(
                id=12,
                occurred_at=datetime.now(UTC),
                event_type="video_collect.failed",
                severity="error",
                message="Channel video collection failed.",
                actor_type="manual_api",
                source="videos.collect",
                metadata_json={"attemptId": 1},
                job_id=1,
                job_attempt_id=1,
                video_task_id=None,
                channel_id=2,
                video_id=None,
                external_api_call_id=None,
                subject_type="channel",
                subject_id=2,
                external_key="UC123",
                correlation_id=None,
                error_type="UpstreamError",
                error_message="failed",
            )
        ]


class FakeOpsRepository(OpsRepositoryPort):
    def __init__(self) -> None:
        self.video_queries: list[OpsVideoListQuery] = []
        self.video_task_queries: list[OpsVideoTaskListQuery] = []
        self.micro_candidate_queries: list[OpsCandidateListQuery] = []
        self.timeline_candidate_queries: list[OpsCandidateListQuery] = []
        self.stuck_queries: list[OpsStuckTaskQuery] = []

    async def get_summary_counts(self) -> OpsSummaryCountsRecord:
        return OpsSummaryCountsRecord(
            streamers=1,
            channels=2,
            videos=3,
            transcripts=4,
            video_tasks=(OpsStatusCountRecord(status="failed", count=1),),
            pipeline_jobs=(OpsStatusCountRecord(status="succeeded", count=2),),
        )

    async def list_recent_failures(self, *, limit: int) -> list[OpsRecentFailureRecord]:
        now = datetime.now(UTC)
        return [
            OpsRecentFailureRecord(
                kind="video_task",
                id=10,
                status="failed",
                label="transcript_collect abc123",
                error_type="UpstreamError",
                error_message="failed",
                created_at=now,
                updated_at=now,
            )
        ]

    async def list_channels(self) -> list[OpsChannelRecord]:
        return [
            OpsChannelRecord(
                channel_id=1,
                streamer_id=1,
                streamer_name="Streamer",
                handle="@channel",
                name="Channel",
                youtube_channel_id="UC123",
                uploads_playlist_id="UU123",
                video_count=3,
                transcript_succeeded_count=2,
                task_no_transcript_count=1,
                task_failed_count=1,
                task_running_count=0,
                latest_video_published_at=datetime.now(UTC),
                latest_task_updated_at=None,
            )
        ]

    async def list_videos(self, query: OpsVideoListQuery) -> OpsVideoListResult:
        self.video_queries.append(query)
        now = datetime.now(UTC)
        return OpsVideoListResult(
            total=1,
            items=(
                OpsVideoRecord(
                    video_id=1,
                    channel_id=1,
                    channel_name="Channel",
                    youtube_video_id="video1234567",
                    title="Video",
                    published_at=now,
                    duration="PT1M",
                    thumbnail_url=None,
                    latest_task_id=2,
                    latest_task_name="transcript_collect",
                    latest_task_status="succeeded",
                    latest_task_updated_at=now,
                    transcript_id=3,
                    generation=_video_generation_record(now),
                ),
            ),
        )

    async def get_video_detail(self, video_id: int) -> OpsVideoDetailRecord | None:
        if video_id != 1:
            return None
        now = datetime.now(UTC)
        task = OpsVideoTaskRecord(
            video_task_id=1,
            video_id=1,
            channel_id=1,
            channel_name="Channel",
            youtube_video_id="video1234567",
            task_name="transcript_collect",
            task_version="v1",
            status="succeeded",
            worker_id=None,
            timeout_seconds=600,
            job_id=1,
            job_attempt_id=1,
            output_transcript_id=3,
            output_json={"cueCount": 1},
            error_type=None,
            error_message=None,
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )
        transcript = YouTubeTranscriptMetadataRecord(
            id=3,
            video_id="video1234567",
            language="Korean",
            language_code="ko",
            is_generated=True,
            requested_languages=("ko", "en"),
            preserve_formatting=False,
            storage_bucket="raw",
            storage_object_name="youtube/transcripts/video1234567-hash.json",
            storage_uri="s3://raw/youtube/transcripts/video1234567-hash.json",
            response_sha256="a" * 64,
            segment_count=2,
            text_length=22,
            notes=None,
            created_at=now,
            updated_at=now,
        )
        return OpsVideoDetailRecord(
            video_id=1,
            channel_id=1,
            channel_name="Channel",
            youtube_video_id="video1234567",
            title="Video",
            description="Stored video description",
            published_at=now,
            duration="PT1M",
            thumbnail_url="https://i.ytimg.com/vi/video1234567/hqdefault.jpg",
            source_listing_api_call_id=10,
            source_details_api_call_id=11,
            source_job_id=12,
            created_at=now,
            updated_at=now,
            latest_task_id=1,
            latest_task_name="transcript_collect",
            latest_task_status="succeeded",
            latest_task_updated_at=now,
            transcript_id=3,
            tasks=(task,),
            transcripts=(transcript,),
        )

    async def list_video_tasks(
        self,
        query: OpsVideoTaskListQuery,
    ) -> OpsVideoTaskListResult:
        self.video_task_queries.append(query)
        now = datetime.now(UTC)
        return OpsVideoTaskListResult(
            total=1,
            items=(
                OpsVideoTaskRecord(
                    video_task_id=1,
                    video_id=1,
                    channel_id=1,
                    channel_name="Channel",
                    youtube_video_id="video1234567",
                    task_name="transcript_collect",
                    task_version="v1",
                    status="succeeded",
                    worker_id=None,
                    timeout_seconds=600,
                    job_id=1,
                    job_attempt_id=1,
                    output_transcript_id=1,
                    output_json={"cueCount": 1},
                    error_type=None,
                    error_message=None,
                    started_at=now,
                    completed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ),
        )

    async def list_micro_event_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsMicroEventReadyCandidateListResult:
        self.micro_candidate_queries.append(query)
        now = datetime.now(UTC)
        return OpsMicroEventReadyCandidateListResult(
            total=1,
            items=(
                OpsMicroEventReadyCandidateRecord(
                    video_id=2,
                    channel_id=1,
                    channel_name="Channel",
                    youtube_video_id="video-micro",
                    title="Micro candidate",
                    published_at=now,
                    transcript_id=3,
                    cue_count=22,
                    latest_cue_task=_task_summary(4, "succeeded", now),
                    latest_micro_task=None,
                    category="readyNoHistory",
                    recommended_retry_failed=False,
                ),
            ),
        )

    async def list_timeline_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsTimelineReadyCandidateListResult:
        self.timeline_candidate_queries.append(query)
        now = datetime.now(UTC)
        return OpsTimelineReadyCandidateListResult(
            total=1,
            items=(
                OpsTimelineReadyCandidateRecord(
                    video_id=3,
                    channel_id=1,
                    channel_name="Channel",
                    youtube_video_id="video-timeline",
                    title="Timeline candidate",
                    published_at=now,
                    source_micro_event_task_id=5,
                    micro_event_count=9,
                    window_count=2,
                    latest_timeline_task=_task_summary(6, "failed", now),
                    category="failed",
                    recommended_retry_failed=True,
                ),
            ),
        )

    async def detect_stuck_tasks(
        self,
        query: OpsStuckTaskQuery,
    ) -> OpsStuckTaskListResult:
        self.stuck_queries.append(query)
        now = datetime.now(UTC)
        return OpsStuckTaskListResult(
            total=1,
            items=(
                OpsStuckTaskRecord(
                    video_task_id=7,
                    video_id=3,
                    channel_id=1,
                    channel_name="Channel",
                    youtube_video_id="video-stuck",
                    title="Stuck video",
                    task_name=query.task_name,
                    status="running",
                    worker_id="micro-event-worker:host:1234",
                    worker_pid=1234,
                    job_id=8,
                    job_attempt_id=9,
                    job_attempt_status="running",
                    started_at=now,
                    updated_at=now,
                    stale_since=now,
                    latest_event=OpsLatestEventRecord(
                        operation_event_id=10,
                        occurred_at=now,
                        event_type="micro_event_extract.window_started",
                        severity="info",
                        message="Started.",
                        error_type=None,
                        error_message=None,
                    ),
                    error_type=None,
                    error_message=None,
                ),
            ),
        )

    async def get_schema_graph(self) -> OpsSchemaGraphRecord:
        return OpsSchemaGraphRecord(tables=(), relations=())


class FakeCodexUsageRepository(CodexUsageRepositoryPort):
    def __init__(self) -> None:
        self.queries: list[CodexUsageListQuery] = []

    async def create_usage(self, usage: CodexUsageCreate) -> CodexUsageRecord:
        raise NotImplementedError

    async def list_usages(self, query: CodexUsageListQuery) -> CodexUsageListResult:
        self.queries.append(query)
        now = datetime.now(UTC)
        return CodexUsageListResult(
            items=[
                CodexUsageRecord(
                    id=12,
                    source="micro_event_extract",
                    operation="extract_window",
                    model="gpt-test",
                    reasoning_effort="high",
                    status="succeeded",
                    thread_id="thread-1",
                    turn_id="turn-1",
                    usage_json={"totalTokens": 33},
                    input_tokens=20,
                    output_tokens=13,
                    total_tokens=33,
                    cached_input_tokens=2,
                    reasoning_output_tokens=1,
                    duration_ms=1234,
                    error_type=None,
                    error_message=None,
                    video_id=1,
                    video_task_id=2,
                    job_id=3,
                    job_attempt_id=4,
                    transcript_id=5,
                    window_index=6,
                    created_at=now,
                )
            ],
            next_cursor=9,
            summary=CodexUsageSummaryRecord(
                run_count=2,
                input_tokens=40,
                output_tokens=26,
                total_tokens=66,
                cached_input_tokens=4,
                reasoning_output_tokens=2,
            ),
        )

    async def list_usage_by_video(
        self,
        query: CodexUsageListQuery,
    ) -> list[CodexUsageVideoSummaryRecord]:
        self.queries.append(query)
        return [
            CodexUsageVideoSummaryRecord(
                video_id=1,
                youtube_video_id="youtube-1",
                title="Video 1",
                run_count=2,
                input_tokens=40,
                output_tokens=26,
                total_tokens=66,
                cached_input_tokens=4,
                reasoning_output_tokens=2,
                latest_model="gpt-test",
                latest_reasoning_effort="high",
                latest_created_at=datetime.now(UTC),
            )
        ]

    async def list_usage_by_job(
        self,
        query: CodexUsageListQuery,
    ) -> list[CodexUsageJobSummaryRecord]:
        self.queries.append(query)
        return [
            CodexUsageJobSummaryRecord(
                job_id=3,
                job_step="micro_event_extract",
                job_status="succeeded",
                subject_type="video",
                subject_id=1,
                external_key="youtube-1",
                run_count=2,
                input_tokens=40,
                output_tokens=26,
                total_tokens=66,
                cached_input_tokens=4,
                reasoning_output_tokens=2,
                latest_model="gpt-test",
                latest_reasoning_effort="high",
                latest_created_at=datetime.now(UTC),
            )
        ]


def test_ops_summary_and_lists_are_available() -> None:
    asyncio.run(_test_ops_summary_and_lists_are_available())


async def _test_ops_summary_and_lists_are_available() -> None:
    app = create_app()
    app.dependency_overrides[get_ops_repository] = lambda: FakeOpsRepository()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        summary = await client.get("/ops/summary")
        channels = await client.get("/ops/channels")
        videos = await client.get("/ops/videos")
        video_detail = await client.get("/ops/videos/1")
        missing_video_detail = await client.get("/ops/videos/999")
        tasks = await client.get("/ops/video-tasks")

    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["channels"] == 2
    assert channels.json()["items"][0]["uploadsPlaylistId"] == "UU123"
    assert channels.json()["items"][0]["taskNoTranscriptCount"] == 1
    video_payload = videos.json()["items"][0]
    assert video_payload["latestTaskStatus"] == "succeeded"
    assert video_payload["generation"]["cues"]["generated"] is True
    assert video_payload["generation"]["cues"]["transcriptId"] == 3
    assert video_payload["generation"]["cues"]["cueCount"] == 2
    assert video_payload["generation"]["cues"]["latestTaskStatus"] == "succeeded"
    assert video_payload["generation"]["microEvents"]["microEventCount"] == 5
    assert video_payload["generation"]["timeline"]["compositionId"] == 8
    assert video_detail.status_code == 200, video_detail.text
    assert video_detail.json()["description"] == "Stored video description"
    assert video_detail.json()["tasks"][0]["jobId"] == 1
    assert video_detail.json()["tasks"][0]["outputJson"] == {"cueCount": 1}
    assert video_detail.json()["transcripts"][0]["languageCode"] == "ko"
    assert missing_video_detail.status_code == 404
    assert missing_video_detail.json() == {"detail": "Video not found."}
    assert tasks.json()["items"][0]["taskName"] == "transcript_collect"


def test_ops_codex_usage_is_filterable() -> None:
    asyncio.run(_test_ops_codex_usage_is_filterable())


async def _test_ops_codex_usage_is_filterable() -> None:
    repository = FakeCodexUsageRepository()
    app = create_app()
    app.dependency_overrides[get_codex_usage_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/codex-usage",
            params={
                "source": "micro_event_extract",
                "status": "succeeded",
                "model": "gpt-test",
                "reasoningEffort": "high",
                "videoId": 1,
                "videoTaskId": 2,
                "jobId": 3,
                "limit": 25,
                "cursor": 99,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["totalTokens"] == 66
    assert payload["items"][0]["codexUsageId"] == 12
    assert payload["items"][0]["reasoningEffort"] == "high"
    assert payload["items"][0]["windowIndex"] == 6
    assert payload["items"][0]["usageJson"] == {"totalTokens": 33}
    assert payload["nextCursor"] == 9
    assert repository.queries[0] == CodexUsageListQuery(
        source="micro_event_extract",
        status="succeeded",
        model="gpt-test",
        reasoning_effort="high",
        video_id=1,
        video_task_id=2,
        job_id=3,
        limit=25,
        cursor=99,
    )


def test_ops_codex_usage_by_video_is_filterable() -> None:
    asyncio.run(_test_ops_codex_usage_by_video_is_filterable())


async def _test_ops_codex_usage_by_video_is_filterable() -> None:
    repository = FakeCodexUsageRepository()
    app = create_app()
    app.dependency_overrides[get_codex_usage_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/codex-usage/by-video",
            params={
                "source": "micro_event_extract",
                "status": "succeeded",
                "model": "gpt-test",
                "reasoningEffort": "high",
                "videoId": 1,
                "videoTaskId": 2,
                "jobId": 3,
                "limit": 25,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["totalTokens"] == 66
    assert payload["items"][0]["videoId"] == 1
    assert payload["items"][0]["youtubeVideoId"] == "youtube-1"
    assert payload["items"][0]["title"] == "Video 1"
    assert payload["items"][0]["latestModel"] == "gpt-test"
    assert payload["items"][0]["latestReasoningEffort"] == "high"
    assert repository.queries[0] == CodexUsageListQuery(
        source="micro_event_extract",
        status="succeeded",
        model="gpt-test",
        reasoning_effort="high",
        video_id=1,
        video_task_id=2,
        job_id=3,
        limit=25,
        cursor=None,
    )


def test_ops_codex_usage_by_job_is_filterable() -> None:
    asyncio.run(_test_ops_codex_usage_by_job_is_filterable())


async def _test_ops_codex_usage_by_job_is_filterable() -> None:
    repository = FakeCodexUsageRepository()
    app = create_app()
    app.dependency_overrides[get_codex_usage_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/codex-usage/by-job",
            params={
                "source": "micro_event_extract",
                "status": "succeeded",
                "model": "gpt-test",
                "reasoningEffort": "high",
                "videoId": 1,
                "videoTaskId": 2,
                "jobId": 3,
                "limit": 25,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["totalTokens"] == 66
    assert payload["items"][0]["jobId"] == 3
    assert payload["items"][0]["jobStep"] == "micro_event_extract"
    assert payload["items"][0]["jobStatus"] == "succeeded"
    assert payload["items"][0]["subjectType"] == "video"
    assert payload["items"][0]["externalKey"] == "youtube-1"
    assert payload["items"][0]["latestModel"] == "gpt-test"
    assert payload["items"][0]["latestReasoningEffort"] == "high"
    assert repository.queries[0] == CodexUsageListQuery(
        source="micro_event_extract",
        status="succeeded",
        model="gpt-test",
        reasoning_effort="high",
        video_id=1,
        video_task_id=2,
        job_id=3,
        limit=25,
        cursor=None,
    )


def test_ops_video_and_task_filters_are_forwarded() -> None:
    asyncio.run(_test_ops_video_and_task_filters_are_forwarded())


async def _test_ops_video_and_task_filters_are_forwarded() -> None:
    repository = FakeOpsRepository()
    app = create_app()
    app.dependency_overrides[get_ops_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        videos = await client.get(
            "/ops/videos",
            params={
                "channelId": 1,
                "taskStatus": "failed",
                "search": "needle",
                "limit": 25,
                "offset": 5,
            },
        )
        tasks = await client.get(
            "/ops/video-tasks",
            params={
                "channelId": 1,
                "taskName": "transcript_collect",
                "status": "running",
                "limit": 25,
                "offset": 5,
            },
        )

    assert videos.status_code == 200, videos.text
    assert tasks.status_code == 200, tasks.text
    assert repository.video_queries[0] == OpsVideoListQuery(
        channel_id=1,
        task_status="failed",
        search="needle",
        limit=25,
        offset=5,
    )
    assert repository.video_task_queries[0] == OpsVideoTaskListQuery(
        channel_id=1,
        task_name="transcript_collect",
        status="running",
        limit=25,
        offset=5,
    )


def test_ops_candidate_routes_are_filterable() -> None:
    asyncio.run(_test_ops_candidate_routes_are_filterable())


async def _test_ops_candidate_routes_are_filterable() -> None:
    repository = FakeOpsRepository()
    app = create_app()
    app.dependency_overrides[get_ops_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        micro = await client.get(
            "/ops/candidates/micro-event-ready",
            params={
                "channelId": 1,
                "search": "needle",
                "category": "readyNoHistory",
                "limit": 25,
                "offset": 5,
            },
        )
        timeline = await client.get(
            "/ops/candidates/timeline-ready",
            params={
                "channelId": 1,
                "search": "needle",
                "category": "failed",
                "limit": 25,
                "offset": 5,
            },
        )
        invalid_limit = await client.get(
            "/ops/candidates/timeline-ready",
            params={"limit": 201},
        )

    assert micro.status_code == 200, micro.text
    assert timeline.status_code == 200, timeline.text
    assert invalid_limit.status_code == 422
    micro_payload = micro.json()
    assert micro_payload["items"][0]["category"] == "readyNoHistory"
    assert micro_payload["items"][0]["recommendedEnqueue"] == {
        "target": "selected_videos",
        "videoIds": [2],
        "retryFailed": False,
    }
    timeline_payload = timeline.json()
    assert timeline_payload["items"][0]["sourceMicroEventTaskId"] == 5
    assert timeline_payload["items"][0]["recommendedEnqueue"]["retryFailed"] is True
    assert repository.micro_candidate_queries[0] == OpsCandidateListQuery(
        channel_id=1,
        search="needle",
        category="readyNoHistory",
        limit=25,
        offset=5,
    )
    assert repository.timeline_candidate_queries[0] == OpsCandidateListQuery(
        channel_id=1,
        search="needle",
        category="failed",
        limit=25,
        offset=5,
    )


def test_ops_events_are_filterable() -> None:
    asyncio.run(_test_ops_events_are_filterable())


async def _test_ops_events_are_filterable() -> None:
    event_repository = FakeOperationEventRepository()
    app = create_app()
    app.dependency_overrides[get_operation_event_repository] = lambda: event_repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/events",
            params={"severity": "error", "eventType": "video_collect.failed", "jobId": 1},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["eventType"] == "video_collect.failed"
    assert payload["items"][0]["metadata"] == {"attemptId": 1}
    assert event_repository.queries[0].severity == "error"
    assert event_repository.queries[0].event_type == "video_collect.failed"
    assert event_repository.queries[0].job_id == 1


def test_ops_schema_graph_uses_openapi_and_metadata() -> None:
    asyncio.run(_test_ops_schema_graph_uses_openapi_and_metadata())


async def _test_ops_schema_graph_uses_openapi_and_metadata() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/ops/schema-graph")

    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    table_names = {table["name"] for table in payload["tables"]}
    relation_ids = {relation["id"] for relation in payload["relations"]}
    channels = next(table for table in payload["tables"] if table["name"] == "channels")
    channel_streamer_relation = next(
        relation
        for relation in payload["relations"]
        if relation["id"] == "streamers.id->channels.streamer_id"
    )
    assert "channels" in table_names
    assert "videos" in table_names
    assert "channels.id->videos.channel_id" in relation_ids
    assert any(
        constraint["targetTable"] == "streamers"
        for constraint in channels["foreignKeyConstraints"]
    )
    assert any("streamer_id" in index["columnNames"] for index in channels["indexes"])
    assert channel_streamer_relation["constraintName"] == "fk_channels_streamer_id_streamers"
    assert channel_streamer_relation["relationKind"] == "one_to_many"
    assert channel_streamer_relation["sourceNullable"] is False
    assert channel_streamer_relation["targetPrimaryKey"] is False


def test_ops_routes_are_in_openapi() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/ops/summary"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/videos/{video_id}"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/events"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/candidates/micro-event-ready"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/candidates/timeline-ready"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/codex-usage"]["get"]["tags"] == ["ops"]
    assert schema["paths"]["/ops/schema-graph"]["get"]["tags"] == ["ops"]
    assert "CodexUsageListResponse" in schema["components"]["schemas"]
    assert "OperationEventListResponse" in schema["components"]["schemas"]
    assert "OpsMicroEventReadyCandidateListResponse" in schema["components"]["schemas"]
    assert "OpsTimelineReadyCandidateListResponse" in schema["components"]["schemas"]
    assert "OpsSchemaGraphResponse" in schema["components"]["schemas"]


def _video_generation_record(now: datetime) -> OpsVideoGenerationRecord:
    return OpsVideoGenerationRecord(
        cues=OpsVideoCueGenerationRecord(
            generated=True,
            transcript_id=3,
            cue_count=2,
            latest_task_id=4,
            latest_task_status="succeeded",
            latest_task_updated_at=now,
        ),
        micro_events=OpsVideoMicroEventGenerationRecord(
            generated=True,
            video_task_id=5,
            window_count=2,
            micro_event_count=5,
            latest_task_id=6,
            latest_task_status="succeeded",
            latest_task_updated_at=now,
        ),
        timeline=OpsVideoTimelineGenerationRecord(
            generated=True,
            composition_id=8,
            video_task_id=7,
            episode_count=3,
            latest_task_id=7,
            latest_task_status="succeeded",
            latest_task_updated_at=now,
        ),
    )


def _task_summary(
    task_id: int,
    status: str,
    now: datetime,
) -> OpsTaskSummaryRecord:
    return OpsTaskSummaryRecord(
        video_task_id=task_id,
        status=status,
        worker_id=None,
        job_id=task_id + 100,
        job_attempt_id=task_id + 200,
        error_type=None,
        error_message=None,
        updated_at=now,
    )
