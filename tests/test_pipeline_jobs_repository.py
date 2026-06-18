from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.channels.ports import ChannelCreate
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate, PipelineJobListQuery
from codex_sdk_cli.domains.videos.ports import VideoCreate
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository


def test_pipeline_job_repository_tracks_attempt_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'pipeline-jobs.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyPipelineJobRepository(session)
            job = await repository.create_job(
                PipelineJobCreate(
                    step="channel_resolve",
                    status="running",
                    subject_type="streamer",
                    subject_id=1,
                    external_key="@GoogleDevelopers",
                    input_json={"streamerId": 1, "handle": "@GoogleDevelopers"},
                    input_hash="0" * 64,
                )
            )

            first_attempt = await repository.create_attempt(job_id=job.id)
            second_attempt = await repository.create_attempt(job_id=job.id, worker_id="worker-1")
            failed_attempt = await repository.mark_attempt_failed(
                first_attempt.id,
                error_type="YouTubeDataUpstreamError",
                error_message="upstream failed",
            )
            succeeded_attempt = await repository.mark_attempt_succeeded(
                second_attempt.id,
                output_json={"channelId": 1, "jobId": job.id},
            )
            failed_job = await repository.mark_job_failed(job.id)
            running_job = await repository.mark_job_running(job.id)
            succeeded_job = await repository.mark_job_succeeded(job.id)
            fetched_job = await repository.get_job(job.id)
            external_api_calls = SqlAlchemyExternalApiCallRepository(session)
            await external_api_calls.create_external_api_call(
                ExternalApiCallCreate(
                    provider="youtube_data",
                    operation="channels.list",
                    request_method="GET",
                    request_url="https://www.googleapis.com/youtube/v3/channels",
                    request_params={"part": "id,snippet", "forHandle": "@GoogleDevelopers"},
                    request_body=None,
                    response_status_code=200,
                    response_headers={"content-type": "application/json"},
                    response_storage_bucket="raw",
                    response_storage_object_name="external-api-calls/object.json",
                    response_storage_uri="s3://raw/external-api-calls/object.json",
                    response_sha256="0" * 64,
                    schema_name="YouTubeChannelsListResponse",
                    schema_version="v1",
                    validation_status="valid",
                    validation_error=None,
                    duration_ms=12,
                    quota_cost=1,
                    pipeline_job_attempt_id=second_attempt.id,
                )
            )
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)
            videos = SqlAlchemyVideoRepository(session)
            streamer = await streamers.create_streamer(name="Google")
            await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@GoogleDevelopers",
                    name="Google for Developers",
                    youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
                    uploads_playlist_id="UU_x5XG1OV2P6uZZ5FSM9Ttw",
                    source_api_call_id=1,
                    source_job_id=job.id,
                )
            )
            await videos.create_videos(
                [
                    VideoCreate(
                        channel_id=1,
                        youtube_video_id="video-1",
                        title="Video 1",
                        description="Collected video",
                        published_at=succeeded_job.created_at,
                        duration="PT1M",
                        thumbnail_url=None,
                        source_listing_api_call_id=1,
                        source_details_api_call_id=1,
                        source_job_id=job.id,
                    )
                ]
            )
            summaries = await repository.list_job_summaries(
                PipelineJobListQuery(step="channel_resolve", status="succeeded")
            )
            detail = await repository.get_job_detail(job.id)

            assert first_attempt.attempt_no == 1
            assert second_attempt.attempt_no == 2
            assert second_attempt.worker_id == "worker-1"
            assert failed_attempt.status == "failed"
            assert failed_attempt.error_type == "YouTubeDataUpstreamError"
            assert failed_attempt.finished_at is not None
            assert succeeded_attempt.status == "succeeded"
            assert succeeded_attempt.output_json == {"channelId": 1, "jobId": job.id}
            assert failed_job.status == "failed"
            assert failed_job.completed_at is not None
            assert running_job.status == "running"
            assert running_job.completed_at is None
            assert succeeded_job.status == "succeeded"
            assert succeeded_job.completed_at is not None
            assert fetched_job == succeeded_job
            assert await repository.get_job(404) is None
            assert len(summaries) == 1
            assert summaries[0].latest_attempt_id == second_attempt.id
            assert summaries[0].latest_attempt_status == "succeeded"
            assert summaries[0].attempt_count == 2
            assert detail is not None
            assert [attempt.id for attempt in detail.attempts] == [
                first_attempt.id,
                second_attempt.id,
            ]
            assert detail.external_api_calls[0].id == 1
            assert detail.external_api_calls[0].pipeline_job_attempt_id == second_attempt.id
            assert detail.channels[0].source_job_id == job.id
            assert detail.videos[0].youtube_video_id == "video-1"
            assert detail.videos[0].source_job_id == job.id
            assert await repository.get_job_detail(404) is None
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
