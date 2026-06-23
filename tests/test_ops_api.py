from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_operation_event_repository, get_ops_repository
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventListQuery,
    OperationEventRecord,
    OperationEventRepositoryPort,
)
from codex_sdk_cli.domains.ops.ports import (
    OpsChannelRecord,
    OpsRecentFailureRecord,
    OpsRepositoryPort,
    OpsStatusCountRecord,
    OpsSummaryCountsRecord,
    OpsVideoDetailRecord,
    OpsVideoListQuery,
    OpsVideoListResult,
    OpsVideoRecord,
    OpsVideoTaskListQuery,
    OpsVideoTaskListResult,
    OpsVideoTaskRecord,
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
    assert videos.json()["items"][0]["latestTaskStatus"] == "succeeded"
    assert video_detail.status_code == 200, video_detail.text
    assert video_detail.json()["description"] == "Stored video description"
    assert video_detail.json()["tasks"][0]["jobId"] == 1
    assert video_detail.json()["tasks"][0]["outputJson"] == {"cueCount": 1}
    assert video_detail.json()["transcripts"][0]["languageCode"] == "ko"
    assert missing_video_detail.status_code == 404
    assert missing_video_detail.json() == {"detail": "Video not found."}
    assert tasks.json()["items"][0]["taskName"] == "transcript_collect"


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
    assert schema["paths"]["/ops/schema-graph"]["get"]["tags"] == ["ops"]
    assert "OperationEventListResponse" in schema["components"]["schemas"]
    assert "OpsSchemaGraphResponse" in schema["components"]["schemas"]
