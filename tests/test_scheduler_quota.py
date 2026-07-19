from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from codex_sdk_cli.application.scheduler.ports import (
    AutomationScheduleState,
    WorkflowCandidateChannel,
    WorkflowCandidateSnapshot,
)
from codex_sdk_cli.application.scheduler.quota import (
    allocate_workflow_candidates,
    daily_quota_window,
)
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.work.models import WorkflowRunModel
from codex_sdk_cli.infra.work.scheduler import SqlAlchemyWorkflowCandidateReader

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_daily_allocation_applies_channel_floor_then_backlog_ratio() -> None:
    snapshot = _snapshot({1: 20, 2: 8, 3: 2})

    plan = allocate_workflow_candidates(
        snapshot,
        daily_limit=40,
        channel_minimum=2,
        tick_limit=12,
        quota_date=date(2026, 7, 19),
    )

    assert dict(plan.channel_allocations) == {1: 6, 2: 4, 3: 2}
    assert len(plan.candidates) == 12
    assert plan.admitted_after_count == 12
    assert plan.remaining_after_count == 28
    assert plan.floor_feasible is True
    for channel_id in (1, 2, 3):
        selected = [item for item in plan.candidates if item.channel_id == channel_id]
        assert selected == sorted(
            selected,
            key=lambda item: (item.published_at, item.id),
            reverse=True,
        )


def test_daily_allocation_respects_existing_admissions_and_hard_cap() -> None:
    snapshot = _snapshot({1: 3, 2: 3}, admitted={1: 20, 2: 19})

    plan = allocate_workflow_candidates(
        snapshot,
        daily_limit=40,
        channel_minimum=2,
        tick_limit=12,
        quota_date=date(2026, 7, 19),
    )

    assert len(plan.candidates) == 1
    assert plan.admitted_before_count == 39
    assert plan.admitted_after_count == 40
    assert plan.remaining_after_count == 0


def test_infeasible_floor_gives_every_channel_one_before_second_slots() -> None:
    snapshot = _snapshot(dict.fromkeys(range(1, 22), 2))

    plan = allocate_workflow_candidates(
        snapshot,
        daily_limit=40,
        channel_minimum=2,
        tick_limit=40,
        quota_date=date(2026, 7, 19),
    )

    allocations = dict(plan.channel_allocations)
    assert plan.floor_feasible is False
    assert len(plan.candidates) == 40
    assert set(allocations.values()) == {1, 2}
    assert sum(count == 1 for count in allocations.values()) == 2
    assert all(count >= 1 for count in allocations.values())


def test_quota_window_rolls_over_at_seoul_midnight() -> None:
    before = daily_quota_window(
        datetime(2026, 7, 19, 14, 59, tzinfo=UTC),
        "Asia/Seoul",
    )
    after = daily_quota_window(
        datetime(2026, 7, 19, 15, 0, tzinfo=UTC),
        "Asia/Seoul",
    )

    assert before.quota_date == date(2026, 7, 19)
    assert before.started_at == datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    assert after.quota_date == date(2026, 7, 20)
    assert after.started_at == datetime(2026, 7, 19, 15, 0, tzinfo=UTC)


def test_snapshot_counts_automatic_workflows_in_all_statuses_but_not_manual(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_automatic_workflow_count(migrated_database_path))


def _snapshot(
    backlog: dict[int, int],
    *,
    admitted: dict[int, int] | None = None,
) -> WorkflowCandidateSnapshot:
    admitted = admitted or {}
    channels = tuple(
        WorkflowCandidateChannel(
            channel_id=channel_id,
            admitted_today_count=admitted.get(channel_id, 0),
            candidates=tuple(
                _video(channel_id, index)
                for index in range(candidate_count)
            ),
        )
        for channel_id, candidate_count in backlog.items()
    )
    return WorkflowCandidateSnapshot(
        admitted_today_count=sum(admitted.values()),
        channels=channels,
    )


def _video(channel_id: int, index: int) -> VideoRecord:
    video_id = channel_id * 1000 + index
    published_at = NOW - timedelta(minutes=index)
    return VideoRecord(
        id=video_id,
        channel_id=channel_id,
        youtube_video_id=f"video-{video_id}",
        title=f"Video {video_id}",
        description="",
        published_at=published_at,
        duration=None,
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=published_at,
        updated_at=published_at,
        is_embeddable=True,
    )


async def _exercise_automatic_workflow_count(database_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (100, 'Quota Test', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (100, 100, '@quota-test', 'Quota Test')"
                )
            )
            for video_id in (101, 102, 103):
                await session.execute(
                    text(
                        "INSERT INTO videos(id, channel_id, youtube_video_id, title, "
                        "description, published_at, created_at, updated_at, is_embeddable) "
                        "VALUES (:id, 100, :youtube_id, :title, '', :created_at, "
                        ":created_at, :created_at, 1)"
                    ),
                    {
                        "id": video_id,
                        "youtube_id": f"quota-{video_id}",
                        "title": f"Quota {video_id}",
                        "created_at": NOW,
                    },
                )
            for video_id, automation_mode, status in (
                (101, "backfill", "failed"),
                (102, "steady", "pending"),
                (103, "manual", "succeeded"),
            ):
                session.add(
                    WorkflowRunModel(
                        workflow_type="process_to_publish",
                        workflow_version="v2",
                        video_id=video_id,
                        input_hash=f"{video_id:064x}",
                        status=status,
                        options_json={"automation_mode": automation_mode},
                        available_at=NOW,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            await session.commit()

        snapshot = await SqlAlchemyWorkflowCandidateReader(
            session_factory
        ).read_snapshot(
            state=AutomationScheduleState(
                mode="backfill",
                backfill_started_at=NOW + timedelta(days=1),
                runtime_state="active",
            ),
            quota_started_at=NOW - timedelta(hours=1),
            quota_ends_at=NOW + timedelta(hours=1),
        )

        assert snapshot.admitted_today_count == 2
        channel = next(item for item in snapshot.channels if item.channel_id == 100)
        assert channel.admitted_today_count == 2
        assert [item.id for item in channel.candidates] == [103]
    finally:
        await engine.dispose()
