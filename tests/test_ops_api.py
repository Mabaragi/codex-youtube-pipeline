from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_ops_repository
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.ops.ports import (
    OpsChannelRecord,
    OpsRecentFailureRecord,
    OpsRepositoryPort,
    OpsStatusCountRecord,
    OpsSummaryCountsRecord,
    OpsVideoListQuery,
    OpsVideoListResult,
    OpsVideoRecord,
    OpsVideoTaskListQuery,
    OpsVideoTaskListResult,
    OpsVideoTaskRecord,
)


class FakeOpsRepository(OpsRepositoryPort):
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
                task_failed_count=1,
                task_running_count=0,
                latest_video_published_at=datetime.now(UTC),
                latest_task_updated_at=None,
            )
        ]

    async def list_videos(self, query: OpsVideoListQuery) -> OpsVideoListResult:
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

    async def list_video_tasks(
        self,
        query: OpsVideoTaskListQuery,
    ) -> OpsVideoTaskListResult:
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
        tasks = await client.get("/ops/video-tasks")

    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["channels"] == 2
    assert channels.json()["items"][0]["uploadsPlaylistId"] == "UU123"
    assert videos.json()["items"][0]["latestTaskStatus"] == "succeeded"
    assert tasks.json()["items"][0]["taskName"] == "transcript_collect"


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
    assert schema["paths"]["/ops/schema-graph"]["get"]["tags"] == ["ops"]
    assert "OpsSchemaGraphResponse" in schema["components"]["schemas"]
