from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codex_sdk_cli.domains.channels.ports import ChannelCreate
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobCreate,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobStatus,
)
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueCreate
from codex_sdk_cli.domains.videos.ports import VideoCreate
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptRecord
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository, VideoModel
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)


def test_pipeline_job_repository_tracks_attempt_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_repository(database_url))


def test_pipeline_job_repository_filters_by_related_channel(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_channel_filter_repository(database_url))


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
                output_json={
                    "failure": {
                        "errorType": "YouTubeDataUpstreamError",
                        "errorMessage": "upstream failed",
                        "stage": "test",
                    },
                    "rawResponses": [],
                },
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
            transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
            cues = SqlAlchemyTranscriptCueRepository(session)
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
            transcript = await transcripts.save_transcript_record(
                YouTubeTranscriptRecord(
                    video_id="video-1",
                    language="Korean",
                    language_code="ko",
                    is_generated=True,
                    requested_languages=("ko", "en"),
                    preserve_formatting=False,
                    storage_bucket="raw",
                    storage_object_name="youtube/transcripts/video-1-hash.json",
                    storage_uri="s3://raw/youtube/transcripts/video-1-hash.json",
                    response_sha256="a" * 64,
                    segment_count=1,
                    text_length=5,
                )
            )
            await cues.replace_cues(
                transcript.id,
                [
                    TranscriptCueCreate(
                        transcript_id=transcript.id,
                        cue_id=f"tr{transcript.id}-c000001",
                        cue_index=1,
                        text="hello",
                        start_ms=0,
                        end_ms=1000,
                        duration_ms=1000,
                        source_segment_index=0,
                        source_job_id=job.id,
                        source_job_attempt_id=second_attempt.id,
                    )
                ],
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
            assert failed_attempt.output_json == {
                "failure": {
                    "errorType": "YouTubeDataUpstreamError",
                    "errorMessage": "upstream failed",
                    "stage": "test",
                },
                "rawResponses": [],
            }
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
            assert detail.attempts[0].output_json == failed_attempt.output_json
            assert detail.external_api_calls[0].id == 1
            assert detail.external_api_calls[0].pipeline_job_attempt_id == second_attempt.id
            assert detail.channels[0].source_job_id == job.id
            assert detail.videos[0].youtube_video_id == "video-1"
            assert detail.videos[0].source_job_id == job.id
            assert detail.transcript_cues[0].transcript_id == transcript.id
            assert detail.transcript_cues[0].cue_count == 1
            assert detail.transcript_cues[0].first_cue_id == f"tr{transcript.id}-c000001"
            assert await repository.get_job_detail(404) is None
    finally:
        await engine.dispose()


async def _exercise_channel_filter_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)
            streamer = await streamers.create_streamer(name="Filter Streamer")

            produced_channel_job = await _create_job(
                pipeline_jobs,
                step="channel_resolve",
                subject_type="streamer",
                subject_id=streamer.id,
                input_json={"streamerId": streamer.id},
            )
            channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@filter",
                    name="Filter Channel",
                    youtube_channel_id="UC_FILTER",
                    uploads_playlist_id="UU_FILTER",
                    source_job_id=produced_channel_job.id,
                )
            )
            other_channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@other",
                    name="Other Channel",
                    youtube_channel_id="UC_OTHER",
                    uploads_playlist_id="UU_OTHER",
                )
            )
            subject_job = await _create_job(
                pipeline_jobs,
                step="video_collect",
                status="failed",
                subject_type="channel",
                subject_id=channel.id,
                input_json={},
            )
            input_job = await _create_job(
                pipeline_jobs,
                step="video_collect",
                subject_type=None,
                subject_id=None,
                input_json={"channelId": channel.id},
            )
            output_job = await _create_job(
                pipeline_jobs,
                step="channel_resolve",
                subject_type="streamer",
                subject_id=streamer.id,
                input_json={"streamerId": streamer.id},
            )
            output_attempt = await pipeline_jobs.create_attempt(job_id=output_job.id)
            await pipeline_jobs.mark_attempt_succeeded(
                output_attempt.id,
                output_json={"channelId": channel.id},
            )
            produced_video_job = await _create_job(
                pipeline_jobs,
                step="video_collect",
                subject_type="channel",
                subject_id=other_channel.id,
                input_json={"channelId": other_channel.id},
            )
            video = VideoModel(
                channel_id=channel.id,
                youtube_video_id="filterVideo1",
                title="Filter Video",
                description="Filter video",
                published_at=produced_video_job.created_at,
                duration="PT1M",
                source_job_id=produced_video_job.id,
            )
            session.add(video)
            await session.flush()
            linked_task_job = await _create_job(
                pipeline_jobs,
                step="transcript_collect",
                subject_type="video",
                subject_id=video.id,
                input_json={"videoId": video.id},
            )
            session.add(
                VideoTaskModel(
                    video_id=video.id,
                    task_name="transcript_collect",
                    task_version="v1",
                    input_hash="1" * 64,
                    status="running",
                    timeout_seconds=600,
                    job_id=linked_task_job.id,
                )
            )
            unrelated_job = await _create_job(
                pipeline_jobs,
                step="video_collect",
                subject_type="channel",
                subject_id=other_channel.id,
                input_json={"channelId": other_channel.id},
            )
            await session.commit()

            records = await pipeline_jobs.list_job_summaries(
                PipelineJobListQuery(channel_id=channel.id, limit=20)
            )
            failed_records = await pipeline_jobs.list_job_summaries(
                PipelineJobListQuery(channel_id=channel.id, status="failed", limit=20)
            )

            job_ids = {record.job.id for record in records}
            assert {
                produced_channel_job.id,
                subject_job.id,
                input_job.id,
                output_job.id,
                produced_video_job.id,
                linked_task_job.id,
            }.issubset(job_ids)
            assert unrelated_job.id not in job_ids
            assert [record.job.id for record in failed_records] == [subject_job.id]
    finally:
        await engine.dispose()


async def _create_job(
    repository: SqlAlchemyPipelineJobRepository,
    *,
    step: str,
    status: PipelineJobStatus = "succeeded",
    subject_type: str | None,
    subject_id: int | None,
    input_json: JsonObject,
) -> PipelineJobRecord:
    return await repository.create_job(
        PipelineJobCreate(
            step=step,
            status=status,
            subject_type=subject_type,
            subject_id=subject_id,
            external_key=None,
            input_json=input_json,
            input_hash=f"{step}:{subject_type}:{subject_id}:{len(input_json)}"[:64].ljust(
                64,
                "0",
            ),
        )
    )
