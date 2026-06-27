from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.micro_events.repository import (
    MicroEventCandidateModel,
    MicroEventExtractionWindowModel,
)
from codex_sdk_cli.infra.ops.repository import SqlAlchemyOpsRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import PipelineJobAttemptModel, PipelineJobModel
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.timelines.repository import (
    TimelineCompositionModel,
    TimelineEpisodeModel,
)
from codex_sdk_cli.infra.transcript_cues.repository import TranscriptCueModel
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.youtube_transcripts.repository import YouTubeTranscriptRecordModel


def test_ops_repository_lists_operational_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_file = tmp_path / "ops.db"
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_file.as_posix()}",
    )
    command.upgrade(_alembic_config(), "head")

    result = asyncio.run(_exercise_repository(database_file))

    assert result["counts"].channels == 1
    assert result["counts"].videos == 1
    assert result["channels"][0].video_count == 1
    assert result["channels"][0].transcript_succeeded_count == 1
    assert result["channels"][0].task_no_transcript_count == 1
    assert result["videos"].total == 1
    assert result["videos"].items[0].latest_task_status == "succeeded"
    assert result["videos"].items[0].transcript_id == result["transcript_id"]
    assert result["videos"].items[0].generation.cues.generated is True
    assert result["videos"].items[0].generation.cues.cue_count == 2
    assert result["videos"].items[0].generation.micro_events.generated is True
    assert result["videos"].items[0].generation.micro_events.window_count == 1
    assert result["videos"].items[0].generation.micro_events.micro_event_count == 2
    assert result["videos"].items[0].generation.timeline.generated is True
    assert result["videos"].items[0].generation.timeline.composition_id == result[
        "composition_id"
    ]
    assert result["videos"].items[0].generation.timeline.episode_count == 2
    assert result["tasks"].items[0].youtube_video_id == "video1234567"
    assert result["failures"][0].kind == "pipeline_job"


async def _exercise_repository(database_file: Path):
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            now = datetime.now(UTC)
            streamer = StreamerModel(name="Streamer")
            session.add(streamer)
            await session.flush()
            channel = ChannelModel(
                streamer_id=streamer.id,
                handle="@channel",
                name="Channel",
                youtube_channel_id="UC123",
                uploads_playlist_id="UU123",
            )
            session.add(channel)
            await session.flush()
            video = VideoModel(
                channel_id=channel.id,
                youtube_video_id="video1234567",
                title="Video",
                description="Description",
                published_at=now,
                duration="PT1M",
            )
            session.add(video)
            transcript = YouTubeTranscriptRecordModel(
                video_id="video1234567",
                language="Korean",
                language_code="ko",
                is_generated=False,
                requested_languages=["ko", "en"],
                preserve_formatting=False,
                storage_bucket="raw",
                storage_object_name="object.json",
                storage_uri="s3://raw/object.json",
                response_sha256="a" * 64,
                segment_count=1,
                text_length=10,
            )
            session.add(transcript)
            failed_job = PipelineJobModel(
                step="video_collect",
                status="failed",
                subject_type="channel",
                subject_id=channel.id,
                external_key="UC123",
                input_json={"channelId": channel.id},
                input_hash="0" * 64,
            )
            session.add(failed_job)
            await session.flush()
            session.add(
                PipelineJobAttemptModel(
                    job_id=failed_job.id,
                    attempt_no=1,
                    status="failed",
                    error_type="UpstreamError",
                    error_message="failed",
                )
            )
            await session.flush()
            no_transcript_task = VideoTaskModel(
                video_id=video.id,
                task_name="transcript_collect",
                task_version="v1",
                input_hash="2" * 64,
                status="no_transcript",
                timeout_seconds=600,
                error_type="YouTubeTranscriptNotFound",
                error_message="No transcript.",
            )
            session.add(no_transcript_task)
            await session.flush()
            task = VideoTaskModel(
                video_id=video.id,
                task_name="transcript_collect",
                task_version="v1",
                input_hash="1" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
            )
            session.add(task)
            cue_task = VideoTaskModel(
                video_id=video.id,
                task_name="transcript_cue_generate",
                task_version="v1",
                input_hash="3" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
                output_json={"cueCount": 1},
            )
            session.add(cue_task)
            await session.flush()
            session.add_all(
                [
                    TranscriptCueModel(
                        transcript_id=transcript.id,
                        cue_id="tr1-c000001",
                        cue_index=1,
                        text="first cue",
                        start_ms=0,
                        end_ms=1000,
                        duration_ms=1000,
                        source_segment_index=0,
                    ),
                    TranscriptCueModel(
                        transcript_id=transcript.id,
                        cue_id="tr1-c000002",
                        cue_index=2,
                        text="second cue",
                        start_ms=1000,
                        end_ms=2000,
                        duration_ms=1000,
                        source_segment_index=1,
                    ),
                ]
            )
            micro_task = VideoTaskModel(
                video_id=video.id,
                task_name="micro_event_extract",
                task_version="v2",
                input_hash="4" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
            )
            session.add(micro_task)
            await session.flush()
            micro_window = MicroEventExtractionWindowModel(
                video_task_id=micro_task.id,
                video_id=video.id,
                transcript_id=transcript.id,
                window_index=1,
                start_cue_id="tr1-c000001",
                end_cue_id="tr1-c000002",
                cue_count=2,
                status="succeeded",
                carry_out_unfinished=False,
            )
            session.add(micro_window)
            await session.flush()
            session.add_all(
                [
                    MicroEventCandidateModel(
                        window_id=micro_window.id,
                        video_task_id=micro_task.id,
                        transcript_id=transcript.id,
                        candidate_index=1,
                        activity="JUST_CHATTING",
                        event="first event",
                        start_cue_id="tr1-c000001",
                        end_cue_id="tr1-c000001",
                        evidence_cue_ids=["tr1-c000001"],
                        boundary_before=True,
                        boundary_after=False,
                        confidence=0.8,
                    ),
                    MicroEventCandidateModel(
                        window_id=micro_window.id,
                        video_task_id=micro_task.id,
                        transcript_id=transcript.id,
                        candidate_index=2,
                        activity="GAMEPLAY",
                        event="second event",
                        start_cue_id="tr1-c000002",
                        end_cue_id="tr1-c000002",
                        evidence_cue_ids=["tr1-c000002"],
                        boundary_before=False,
                        boundary_after=True,
                        confidence=0.9,
                    ),
                ]
            )
            timeline_task = VideoTaskModel(
                video_id=video.id,
                task_name="timeline_compose",
                task_version="v1",
                input_hash="5" * 64,
                status="succeeded",
                timeout_seconds=600,
            )
            session.add(timeline_task)
            await session.flush()
            composition = TimelineCompositionModel(
                video_task_id=timeline_task.id,
                video_id=video.id,
                source_micro_event_task_id=micro_task.id,
                source_micro_event_fingerprint="f" * 64,
                copy_style="LIGHT_FANDOM_V1",
                title="Timeline",
                summary="Summary",
                display_title="Timeline",
                display_summary="Summary",
                main_topics=["topic"],
                output_json={"ok": True},
                validation_warnings=[],
            )
            session.add(composition)
            await session.flush()
            session.add_all(
                [
                    TimelineEpisodeModel(
                        composition_id=composition.id,
                        episode_id="ep-1",
                        episode_index=1,
                        parent_block_id="block-1",
                        program_mode="JUST_CHATTING",
                        primary_content_kind="META_CHAT",
                        title="Episode 1",
                        summary="First episode",
                        display_title="Episode 1",
                        display_summary="First episode",
                        topics=["topic"],
                        viewer_tags=["FUNNY"],
                        highlight_micro_event_candidate_ids=[],
                        visibility="PUBLIC",
                    ),
                    TimelineEpisodeModel(
                        composition_id=composition.id,
                        episode_id="ep-2",
                        episode_index=2,
                        parent_block_id="block-1",
                        program_mode="GAMEPLAY",
                        primary_content_kind="GAME_PROGRESS",
                        title="Episode 2",
                        summary="Second episode",
                        display_title="Episode 2",
                        display_summary="Second episode",
                        topics=["topic"],
                        viewer_tags=["SKILL"],
                        highlight_micro_event_candidate_ids=[],
                        visibility="PUBLIC",
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            repository = SqlAlchemyOpsRepository(session)
            from codex_sdk_cli.domains.ops.ports import (
                OpsVideoListQuery,
                OpsVideoTaskListQuery,
            )

            return {
                "counts": await repository.get_summary_counts(),
                "channels": await repository.list_channels(),
                "videos": await repository.list_videos(
                    OpsVideoListQuery(
                        channel_id=None,
                        task_status=None,
                        search=None,
                        limit=10,
                        offset=0,
                    )
                ),
                "tasks": await repository.list_video_tasks(
                    OpsVideoTaskListQuery(
                        channel_id=None,
                        task_name=None,
                        status=None,
                        limit=10,
                        offset=0,
                    )
                ),
                "failures": await repository.list_recent_failures(limit=5),
                "transcript_id": transcript.id,
                "composition_id": composition.id,
            }
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
