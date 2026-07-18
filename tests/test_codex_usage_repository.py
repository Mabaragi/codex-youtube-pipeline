from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.codex_usage.ports import CodexUsageCreate, CodexUsageListQuery
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.codex_usage.repository import SqlAlchemyCodexUsageRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.work.models import WorkItemModel


def test_codex_usage_repository_creates_lists_and_summarizes_usage(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    result = asyncio.run(_exercise_repository(database_url))

    assert result == {
        "first_source": "micro_event_extract",
        "first_reasoning_effort": "low",
        "first_total_tokens": 11,
        "summary_run_count": 4,
        "summary_total_tokens": 87,
        "effort_summary_total_tokens": 33,
        "source_summary_run_count": 3,
        "source_summary_total_tokens": 77,
        "video_summary_count": 1,
        "video_summary_latest_model": "gpt-test",
        "video_summary_latest_reasoning_effort": "low",
        "video_summary_title": "Video 1",
        "video_summary_total_tokens": 77,
        "job_summary_count": 3,
        "job_summary_total_tokens": 77,
        "job_summary_has_unlinked": True,
        "job_summary_has_step": True,
        "next_cursor": 3,
    }


async def _exercise_repository(database_url: str) -> dict[str, int | str | None]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyCodexUsageRepository(session)
            video = await _create_video(session)
            first_job = await _create_job(
                session,
                step="micro_event_extract",
                status="succeeded",
                video_id=video.id,
                external_key=video.youtube_video_id,
            )
            second_job = await _create_job(
                session,
                step="micro_event_extract",
                status="failed",
                video_id=video.id,
                external_key=video.youtube_video_id,
            )
            await repository.create_usage(
                CodexUsageCreate(
                    source="codex_runs",
                    operation="run_prompt",
                    model="gpt-test",
                    reasoning_effort="low",
                    status="succeeded",
                    thread_id="thread-0",
                    turn_id="turn-0",
                    usage_json={"totalTokens": 10},
                    input_tokens=7,
                    output_tokens=3,
                    total_tokens=10,
                    cached_input_tokens=None,
                    reasoning_output_tokens=None,
                    duration_ms=100,
                )
            )
            await repository.create_usage(
                CodexUsageCreate(
                    source="micro_event_extract",
                    operation="extract_window",
                    model="gpt-test",
                    reasoning_effort="high",
                    status="succeeded",
                    thread_id="thread-1",
                    turn_id="turn-1",
                    usage_json={"totalTokens": 33},
                    input_tokens=20,
                    output_tokens=13,
                    total_tokens=33,
                    cached_input_tokens=2,
                    reasoning_output_tokens=1,
                    duration_ms=1234,
                    video_id=video.id,
                    video_task_id=None,
                    job_id=first_job.id,
                    job_attempt_id=None,
                    transcript_id=None,
                    window_index=1,
                )
            )
            await repository.create_usage(
                CodexUsageCreate(
                    source="micro_event_extract",
                    operation="extract_window",
                    model="gpt-test",
                    reasoning_effort="medium",
                    status="succeeded",
                    thread_id="thread-2",
                    turn_id="turn-2",
                    usage_json={
                        "last": {"totalTokens": 3},
                        "total": {
                            "inputTokens": 20,
                            "outputTokens": 13,
                            "totalTokens": 33,
                            "cachedInputTokens": 2,
                            "reasoningOutputTokens": 1,
                        },
                    },
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    cached_input_tokens=None,
                    reasoning_output_tokens=None,
                    duration_ms=1234,
                    video_id=video.id,
                    video_task_id=None,
                    job_id=second_job.id,
                    job_attempt_id=None,
                    transcript_id=None,
                    window_index=2,
                )
            )
            await repository.create_usage(
                CodexUsageCreate(
                    source="micro_event_extract",
                    operation="extract_window",
                    model="gpt-test",
                    reasoning_effort="low",
                    status="succeeded",
                    thread_id="thread-3",
                    turn_id="turn-3",
                    usage_json={"totalTokens": 11},
                    input_tokens=8,
                    output_tokens=3,
                    total_tokens=11,
                    cached_input_tokens=0,
                    reasoning_output_tokens=0,
                    duration_ms=100,
                    video_id=video.id,
                    video_task_id=None,
                    job_id=None,
                    job_attempt_id=None,
                    transcript_id=None,
                    window_index=3,
                )
            )

            all_rows = await repository.list_usages(CodexUsageListQuery(limit=1))
            source_rows = await repository.list_usages(
                CodexUsageListQuery(source="micro_event_extract", limit=50)
            )
            effort_rows = await repository.list_usages(
                CodexUsageListQuery(reasoning_effort="high", limit=50)
            )
            video_rows = await repository.list_usage_by_video(
                CodexUsageListQuery(source="micro_event_extract", limit=50)
            )
            job_rows = await repository.list_usage_by_job(
                CodexUsageListQuery(source="micro_event_extract", video_id=video.id, limit=50)
            )
            return {
                "first_source": all_rows.items[0].source,
                "first_reasoning_effort": all_rows.items[0].reasoning_effort,
                "first_total_tokens": all_rows.items[0].total_tokens,
                "summary_run_count": all_rows.summary.run_count,
                "summary_total_tokens": all_rows.summary.total_tokens,
                "effort_summary_total_tokens": effort_rows.summary.total_tokens,
                "source_summary_run_count": source_rows.summary.run_count,
                "source_summary_total_tokens": source_rows.summary.total_tokens,
                "video_summary_count": len(video_rows),
                "video_summary_latest_model": video_rows[0].latest_model,
                "video_summary_latest_reasoning_effort": (video_rows[0].latest_reasoning_effort),
                "video_summary_title": video_rows[0].title,
                "video_summary_total_tokens": video_rows[0].total_tokens,
                "job_summary_count": len(job_rows),
                "job_summary_total_tokens": sum(row.total_tokens for row in job_rows),
                "job_summary_has_unlinked": any(row.job_id is None for row in job_rows),
                "job_summary_has_step": any(
                    row.job_step == "micro_event_extract" and row.job_status == "failed"
                    for row in job_rows
                ),
                "next_cursor": all_rows.next_cursor,
            }
    finally:
        await engine.dispose()


async def _create_video(session: AsyncSession) -> VideoModel:
    now = datetime.now(UTC)
    streamer = StreamerModel(name="Streamer", publish_profile_id=1)
    session.add(streamer)
    await session.flush()
    channel = ChannelModel(
        streamer_id=streamer.id,
        handle="@streamer",
        name="Channel",
        youtube_channel_id="channel-1",
        uploads_playlist_id="uploads-1",
    )
    session.add(channel)
    await session.flush()
    video = VideoModel(
        channel_id=channel.id,
        youtube_video_id="youtube-1",
        title="Video 1",
        description="Description",
        published_at=now,
        duration="PT1H",
        thumbnail_url=None,
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)
    return video


async def _create_job(
    session: AsyncSession,
    *,
    step: str,
    status: str,
    video_id: int,
    external_key: str,
) -> WorkItemModel:
    job = WorkItemModel(
        task_type=step,
        status=status,
        subject_type="video",
        subject_id=video_id,
        external_key=external_key,
        task_version="v1",
        input_json={"videoId": video_id},
        input_hash=f"{step}-{status}-{video_id}",
        idempotency_key=f"usage:{step}:{status}:{video_id}",
        execution_mode="worker",
        priority=0,
        timeout_seconds=600,
        available_at=datetime.now(UTC),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
