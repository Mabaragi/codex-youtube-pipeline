from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.channels.ports import ChannelCreate
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskCreate, VideoTaskListQuery
from codex_sdk_cli.domains.videos.ports import VideoCreate
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptRecord
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)


def test_video_task_repository_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'video-tasks.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    result = asyncio.run(_exercise_repository(database_url))

    assert result["same_task_id"] is True
    assert result["running_count"] == 1
    assert result["listed_youtube_ids"] == ["abc123DEF45"]
    assert result["succeeded_transcript_id"] == 1
    assert result["failed_status"] == "failed"
    assert result["timed_out_status"] == "timed_out"
    assert result["no_transcript_status"] == "no_transcript"


async def _exercise_repository(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)
            videos = SqlAlchemyVideoRepository(session)
            external_api_calls = SqlAlchemyExternalApiCallRepository(session)
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
            video_tasks = SqlAlchemyVideoTaskRepository(session)

            streamer = await streamers.create_streamer(name="Creator")
            channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@creator",
                    name="Creator",
                    youtube_channel_id="UC-test",
                    uploads_playlist_id="UU-test",
                )
            )
            collect_job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="video_collect",
                    status="succeeded",
                    subject_type="channel",
                    subject_id=channel.id,
                    external_key="UC-test",
                    input_json={"channelId": channel.id},
                    input_hash="0" * 64,
                )
            )
            listing_call = await external_api_calls.create_external_api_call(
                _external_call("playlistItems.list")
            )
            details_call = await external_api_calls.create_external_api_call(
                _external_call("videos.list")
            )
            video = (
                await videos.create_videos(
                    [
                        VideoCreate(
                            channel_id=channel.id,
                            youtube_video_id="abc123DEF45",
                            title="Video",
                            description="Description",
                            published_at=datetime(2026, 6, 16, tzinfo=UTC),
                            duration="PT1M",
                            thumbnail_url=None,
                            source_listing_api_call_id=listing_call.id,
                            source_details_api_call_id=details_call.id,
                            source_job_id=collect_job.id,
                        )
                    ]
                )
            )[0]
            task = await video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=video.id,
                    task_name="transcript_collect",
                    task_version="v1",
                    input_hash="a" * 64,
                    timeout_seconds=600,
                )
            )
            same_task = await video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=video.id,
                    task_name="transcript_collect",
                    task_version="v1",
                    input_hash="a" * 64,
                    timeout_seconds=600,
                )
            )
            job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="transcript_collect",
                    status="running",
                    subject_type="video",
                    subject_id=video.id,
                    external_key=video.youtube_video_id,
                    input_json={"videoTaskId": task.id},
                    input_hash="a" * 64,
                )
            )
            attempt = await pipeline_jobs.create_attempt(job_id=job.id)
            running = await video_tasks.mark_task_running(
                task.id,
                worker_id="worker-1",
                timeout_seconds=600,
                job_id=job.id,
                job_attempt_id=attempt.id,
            )
            running_count = await video_tasks.count_running(task_name="transcript_collect")
            listed = await video_tasks.list_tasks(VideoTaskListQuery(channel_id=channel.id))
            transcript = await transcripts.save_transcript_record(
                YouTubeTranscriptRecord(
                    video_id=video.youtube_video_id,
                    language="Korean",
                    language_code="ko",
                    is_generated=True,
                    requested_languages=("ko", "en"),
                    preserve_formatting=False,
                    storage_bucket="raw",
                    storage_object_name="youtube/transcripts/object.json",
                    storage_uri="s3://raw/youtube/transcripts/object.json",
                    response_sha256="b" * 64,
                    segment_count=2,
                    text_length=10,
                )
            )
            succeeded = await video_tasks.mark_task_succeeded(
                running.id,
                output_transcript_id=transcript.id,
                output_json={"transcriptId": transcript.id},
            )
            failed = await video_tasks.mark_task_failed(
                task.id,
                error_type="Boom",
                error_message="failed",
            )
            timed_out = await video_tasks.mark_task_timed_out(
                task.id,
                error_message="timeout",
            )
            no_transcript = await video_tasks.mark_task_no_transcript(
                task.id,
                error_message="No transcript.",
            )

            return {
                "same_task_id": task.id == same_task.id,
                "running_count": running_count,
                "listed_youtube_ids": [record.youtube_video_id for record in listed],
                "succeeded_transcript_id": succeeded.output_transcript_id,
                "failed_status": failed.status,
                "timed_out_status": timed_out.status,
                "no_transcript_status": no_transcript.status,
            }
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config


def _external_call(operation: str) -> ExternalApiCallCreate:
    return ExternalApiCallCreate(
        provider="youtube_data",
        operation=operation,
        request_method="GET",
        request_url=f"https://www.googleapis.com/youtube/v3/{operation}",
        request_params={"part": "snippet"},
        request_body=None,
        response_status_code=200,
        response_headers={"content-type": "application/json"},
        response_storage_bucket="raw",
        response_storage_object_name=f"external-api-calls/{operation}.json",
        response_storage_uri=f"s3://raw/external-api-calls/{operation}.json",
        response_sha256="0" * 64,
        schema_name="schema",
        schema_version="v1",
        validation_status="valid",
        validation_error=None,
        duration_ms=12,
        quota_cost=1,
    )
