from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.recovery import (
    INTERRUPTED_ERROR_TYPE,
    recover_interrupted_running_work,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.work.models import WorkAttemptModel, WorkItemModel


def test_recover_interrupted_running_work_marks_running_rows_failed(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    result = asyncio.run(_exercise_recovery(database_url))

    assert result == {
        "work_items": 1,
        "work_attempts": 1,
        "attempt_status": "failed",
        "work_item_status": "failed",
        "attempt_error_type": INTERRUPTED_ERROR_TYPE,
        "work_item_error_type": INTERRUPTED_ERROR_TYPE,
        "work_item_completed": True,
        "attempt_finished": True,
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
                source_job_id=None,
            )
            session.add(video)
            await session.flush()
            work_item = WorkItemModel(
                task_type="transcript_collect",
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                task_version="v1",
                input_hash="b" * 64,
                idempotency_key="recovery-test",
                execution_mode="inline",
                status="running",
                priority=0,
                timeout_seconds=600,
                input_json={"videoId": video.id},
                available_at=now,
                lease_owner="manual-api",
                started_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(work_item)
            await session.flush()
            attempt = WorkAttemptModel(
                work_item_id=work_item.id,
                attempt_no=1,
                status="running",
                started_at=now,
                worker_id="manual-api",
            )
            session.add(attempt)
            await session.commit()

            recovery = await recover_interrupted_running_work(session)
            recovered_item = await session.get(WorkItemModel, work_item.id)
            recovered_attempt = await session.get(WorkAttemptModel, attempt.id)

            assert recovered_item is not None
            assert recovered_attempt is not None
            await session.refresh(recovered_item)
            await session.refresh(recovered_attempt)
            return {
                "work_items": recovery.work_items,
                "work_attempts": recovery.work_attempts,
                "attempt_status": recovered_attempt.status,
                "work_item_status": recovered_item.status,
                "attempt_error_type": recovered_attempt.error_type,
                "work_item_error_type": recovered_item.error_type,
                "work_item_completed": recovered_item.completed_at is not None,
                "attempt_finished": recovered_attempt.finished_at is not None,
            }
    finally:
        await engine.dispose()
