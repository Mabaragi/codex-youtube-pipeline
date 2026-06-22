from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.ops.repository import SqlAlchemyOpsRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import PipelineJobAttemptModel, PipelineJobModel
from codex_sdk_cli.infra.streamers.repository import StreamerModel
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
            }
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
