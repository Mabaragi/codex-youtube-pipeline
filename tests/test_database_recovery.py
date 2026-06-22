from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.recovery import (
    INTERRUPTED_ERROR_TYPE,
    recover_interrupted_running_work,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.pipeline_jobs.repository import (
    PipelineJobAttemptModel,
    PipelineJobModel,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel


def test_recover_interrupted_running_work_marks_running_rows_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'recovery.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    result = asyncio.run(_exercise_recovery(database_url))

    assert result == {
        "pipeline_jobs": 1,
        "pipeline_job_attempts": 1,
        "video_tasks": 1,
        "job_status": "failed",
        "attempt_status": "failed",
        "task_status": "failed",
        "attempt_error_type": INTERRUPTED_ERROR_TYPE,
        "task_error_type": INTERRUPTED_ERROR_TYPE,
        "job_completed": True,
        "attempt_finished": True,
        "task_completed": True,
    }


async def _exercise_recovery(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            now = datetime(2026, 6, 22, tzinfo=UTC)
            streamer = StreamerModel(name="Creator")
            session.add(streamer)
            await session.flush()
            channel = ChannelModel(
                streamer_id=streamer.id,
                handle="@creator",
                name="Creator",
                youtube_channel_id="UC-test",
                uploads_playlist_id="UU-test",
            )
            session.add(channel)
            await session.flush()
            job = PipelineJobModel(
                step="transcript_collect",
                status="running",
                subject_type="video",
                subject_id=1,
                external_key="abc123DEF45",
                input_json={"videoId": 1},
                input_hash="a" * 64,
            )
            session.add(job)
            await session.flush()
            attempt = PipelineJobAttemptModel(
                job_id=job.id,
                attempt_no=1,
                status="running",
                started_at=now,
                worker_id="manual-api",
            )
            session.add(attempt)
            video = VideoModel(
                channel_id=channel.id,
                youtube_video_id="abc123DEF45",
                title="Video",
                description="Description",
                published_at=now,
                duration="PT1M",
                thumbnail_url=None,
                source_listing_api_call_id=None,
                source_details_api_call_id=None,
                source_job_id=job.id,
            )
            session.add(video)
            await session.flush()
            task = VideoTaskModel(
                video_id=video.id,
                task_name="transcript_collect",
                task_version="v1",
                input_hash="b" * 64,
                status="running",
                worker_id="manual-api",
                timeout_seconds=600,
                job_id=job.id,
                job_attempt_id=attempt.id,
                started_at=now,
            )
            session.add(task)
            await session.commit()

            recovery = await recover_interrupted_running_work(session)
            recovered_job = await session.get(PipelineJobModel, job.id)
            recovered_attempt = await session.get(PipelineJobAttemptModel, attempt.id)
            recovered_task = await session.get(VideoTaskModel, task.id)

            assert recovered_job is not None
            assert recovered_attempt is not None
            assert recovered_task is not None
            await session.refresh(recovered_job)
            await session.refresh(recovered_attempt)
            await session.refresh(recovered_task)
            return {
                "pipeline_jobs": recovery.pipeline_jobs,
                "pipeline_job_attempts": recovery.pipeline_job_attempts,
                "video_tasks": recovery.video_tasks,
                "job_status": recovered_job.status,
                "attempt_status": recovered_attempt.status,
                "task_status": recovered_task.status,
                "attempt_error_type": recovered_attempt.error_type,
                "task_error_type": recovered_task.error_type,
                "job_completed": recovered_job.completed_at is not None,
                "attempt_finished": recovered_attempt.finished_at is not None,
                "task_completed": recovered_task.completed_at is not None,
            }
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
