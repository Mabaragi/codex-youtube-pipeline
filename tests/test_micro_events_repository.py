from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.channels.ports import ChannelCreate
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.domains.micro_events.ports import (
    AsrCorrectionCandidateCreate,
    MicroEventCandidateCreate,
    MicroEventExcludedRangeCreate,
    MicroEventExtractionWindowCreate,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskCreate
from codex_sdk_cli.domains.videos.ports import VideoCreate
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptRecord
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.micro_events.repository import (
    SqlAlchemyMicroEventExtractionRepository,
)
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)


def test_micro_event_repository_replaces_and_reads_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'micro-events.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    result = asyncio.run(_exercise_repository(database_url))

    assert result["window_count"] == 1
    assert result["micro_event_count"] == 1
    assert result["excluded_range_count"] == 1
    assert result["asr_count"] == 1
    assert result["latest_task_id"] == result["task_id"]
    assert result["pipeline_micro_event_count"] == 1
    assert result["updated_event"] == "스트리머가 울면서 방송 주제를 설명한다."
    assert result["parsed_response_json"] == {"micro_events": []}
    assert result["missing_update_is_none"] is True
    assert result["replaced_window_count"] == 1
    assert result["replaced_micro_event_count"] == 0


async def _exercise_repository(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)
            videos = SqlAlchemyVideoRepository(session)
            external_api_calls = SqlAlchemyExternalApiCallRepository(session)
            transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            video_tasks = SqlAlchemyVideoTaskRepository(session)
            micro_events = SqlAlchemyMicroEventExtractionRepository(session)

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
            video_collect_job = await pipeline_jobs.create_job(
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
                            published_at=datetime(2026, 6, 23, tzinfo=UTC),
                            duration="PT1H",
                            thumbnail_url=None,
                            source_listing_api_call_id=listing_call.id,
                            source_details_api_call_id=details_call.id,
                            source_job_id=video_collect_job.id,
                        )
                    ]
                )
            )[0]
            transcript = await transcripts.save_transcript_record(
                YouTubeTranscriptRecord(
                    video_id=video.youtube_video_id,
                    language="Korean",
                    language_code="ko",
                    is_generated=True,
                    requested_languages=("ko", "en"),
                    preserve_formatting=False,
                    storage_bucket="raw",
                    storage_object_name="youtube/transcripts/abc123DEF45.json",
                    storage_uri="s3://raw/youtube/transcripts/abc123DEF45.json",
                    response_sha256="a" * 64,
                    segment_count=2,
                    text_length=10,
                )
            )
            task = await video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=video.id,
                    task_name="micro_event_extract",
                    task_version="v1",
                    input_hash="b" * 64,
                    timeout_seconds=3600,
                )
            )
            job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="micro_event_extract",
                    status="running",
                    subject_type="video",
                    subject_id=video.id,
                    external_key=video.youtube_video_id,
                    input_json={"videoTaskId": task.id},
                    input_hash=task.input_hash,
                )
            )
            attempt = await pipeline_jobs.create_attempt(job_id=job.id)
            running = await video_tasks.mark_task_running(
                task.id,
                worker_id="manual-api",
                timeout_seconds=3600,
                job_id=job.id,
                job_attempt_id=attempt.id,
            )
            await micro_events.replace_extraction(
                running.id,
                [
                    _window(
                        video_task_id=running.id,
                        video_id=video.id,
                        transcript_id=transcript.id,
                        job_id=job.id,
                        attempt_id=attempt.id,
                    )
                ],
            )
            await pipeline_jobs.mark_attempt_succeeded(
                attempt.id,
                output_json={"windowCount": 1},
            )
            await pipeline_jobs.mark_job_succeeded(job.id)
            succeeded = await video_tasks.mark_task_succeeded(
                running.id,
                output_transcript_id=transcript.id,
                output_json={"windowCount": 1},
            )
            detail = await micro_events.get_extraction(
                video_id=video.id,
                video_task_id=succeeded.id,
            )
            latest = await micro_events.get_latest_succeeded_extraction(video_id=video.id)
            job_detail = await pipeline_jobs.get_job_detail(job.id)
            candidate_id = detail.windows[0].micro_events[0].id
            updated_candidate = await micro_events.update_candidate_event(
                video_task_id=succeeded.id,
                candidate_id=candidate_id,
                event="스트리머가 울면서 방송 주제를 설명한다.",
            )
            reread = await micro_events.get_extraction(
                video_id=video.id,
                video_task_id=succeeded.id,
            )
            missing_update = await micro_events.update_candidate_event(
                video_task_id=succeeded.id,
                candidate_id=999_999,
                event="없는 후보를 바꾼다.",
            )
            await micro_events.replace_extraction(
                succeeded.id,
                [
                    _window(
                        video_task_id=succeeded.id,
                        video_id=video.id,
                        transcript_id=transcript.id,
                        job_id=job.id,
                        attempt_id=attempt.id,
                        with_candidates=False,
                    )
                ],
            )
            replaced = await micro_events.get_extraction(
                video_id=video.id,
                video_task_id=succeeded.id,
            )

            assert detail is not None
            assert latest is not None
            assert job_detail is not None
            assert updated_candidate is not None
            assert reread is not None
            assert replaced is not None
            return {
                "task_id": succeeded.id,
                "window_count": len(detail.windows),
                "micro_event_count": len(detail.windows[0].micro_events),
                "excluded_range_count": len(detail.windows[0].excluded_ranges),
                "asr_count": len(detail.windows[0].asr_correction_candidates),
                "latest_task_id": latest.video_task_id,
                "pipeline_micro_event_count": (
                    job_detail.micro_event_extractions[0].micro_event_count
                ),
                "updated_event": updated_candidate.event,
                "parsed_response_json": reread.windows[0].parsed_response_json,
                "missing_update_is_none": missing_update is None,
                "replaced_window_count": len(replaced.windows),
                "replaced_micro_event_count": len(replaced.windows[0].micro_events),
            }
    finally:
        await engine.dispose()


def _window(
    *,
    video_task_id: int,
    video_id: int,
    transcript_id: int,
    job_id: int,
    attempt_id: int,
    with_candidates: bool = True,
) -> MicroEventExtractionWindowCreate:
    return MicroEventExtractionWindowCreate(
        video_task_id=video_task_id,
        video_id=video_id,
        transcript_id=transcript_id,
        window_index=1,
        start_cue_id=f"tr{transcript_id}-c000001",
        end_cue_id=f"tr{transcript_id}-c000002",
        cue_count=2,
        status="succeeded",
        carry_out_unfinished=False,
        codex_thread_id="thread-1",
        codex_turn_id="turn-1",
        raw_response_text='{"micro_events":[]}',
        parsed_response_json={"micro_events": []},
        validation_error=None,
        source_job_id=job_id,
        source_job_attempt_id=attempt_id,
        micro_events=[
            MicroEventCandidateCreate(
                candidate_index=1,
                activity="JUST_CHATTING",
                event="스트리머가 방송 주제를 설명한다.",
                start_cue_id=f"tr{transcript_id}-c000001",
                end_cue_id=f"tr{transcript_id}-c000002",
                evidence_cue_ids=[f"tr{transcript_id}-c000001"],
                boundary_before=True,
                boundary_after=False,
                confidence=0.9,
                program_mode="JUST_CHATTING",
                content_kind="META_CHAT",
                topics=["방송 주제"],
                relation_to_previous="NEW_TOPIC",
                continues_to_next=False,
                support_level="DIRECT",
            )
        ]
        if with_candidates
        else [],
        excluded_ranges=[
            MicroEventExcludedRangeCreate(
                range_index=1,
                start_cue_id=f"tr{transcript_id}-c000002",
                end_cue_id=f"tr{transcript_id}-c000002",
                reason="LOW_INFORMATION",
            )
        ]
        if with_candidates
        else [],
        asr_correction_candidates=[
            AsrCorrectionCandidateCreate(
                candidate_index=1,
                original="코덱스",
                suggested="Codex",
                correction_type="PROPER_NOUN",
                apply_scope="SEARCH_ONLY",
                confidence=0.8,
            )
        ]
        if with_candidates
        else [],
    )


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


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
