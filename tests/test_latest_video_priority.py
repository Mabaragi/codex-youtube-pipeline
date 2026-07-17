from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from codex_sdk_cli.application.scheduler.ports import AutomationScheduleState
from codex_sdk_cli.application.work.ports import CreateWorkflowRun, CreateWorkItem
from codex_sdk_cli.domains.work.models import WorkExecutionMode
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.scheduler import SqlAlchemyWorkflowCandidateReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


def test_automation_prioritizes_latest_videos_without_overriding_explicit_priority(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_latest_video_priority(migrated_database_path))


async def _exercise_latest_video_priority(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    now = datetime(2026, 8, 1, tzinfo=UTC)
    try:
        await _seed_videos(session_factory)

        candidates = await SqlAlchemyWorkflowCandidateReader(session_factory).list_candidates(
            state=AutomationScheduleState(mode="backfill", backfill_started_at=now),
            limit=2,
        )
        assert [candidate.id for candidate in candidates] == [3, 2]

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            old_workflow, _ = await unit_of_work.workflows.create_or_get(
                CreateWorkflowRun(
                    workflow_type="process_to_publish",
                    workflow_version="v2",
                    video_id=1,
                    input_hash="old-workflow",
                    options_json={},
                    available_at=now,
                )
            )
            latest_workflow, _ = await unit_of_work.workflows.create_or_get(
                CreateWorkflowRun(
                    workflow_type="process_to_publish",
                    workflow_version="v2",
                    video_id=3,
                    input_hash="latest-workflow",
                    options_json={},
                    available_at=now,
                )
            )
            claimed_workflow = await unit_of_work.workflows.claim_next(
                worker_id="coordinator:test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            await unit_of_work.commit()

        assert old_workflow.id != latest_workflow.id
        assert claimed_workflow is not None
        assert claimed_workflow.video_id == 3

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            old_high, _ = await unit_of_work.work_items.get_or_create(
                _create_item(video_id=1, key="old-high", priority=10, now=now)
            )
            old_normal, _ = await unit_of_work.work_items.get_or_create(
                _create_item(video_id=1, key="old-normal", priority=0, now=now)
            )
            latest_normal, _ = await unit_of_work.work_items.get_or_create(
                _create_item(video_id=3, key="latest-normal", priority=0, now=now)
            )
            first_claim = await unit_of_work.work_items.claim_next(
                task_types=("timeline_compose",),
                worker_id="worker:first",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            second_claim = await unit_of_work.work_items.claim_next(
                task_types=("timeline_compose",),
                worker_id="worker:second",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            await unit_of_work.commit()

        assert first_claim is not None and first_claim.id == old_high.id
        assert second_claim is not None and second_claim.id == latest_normal.id
        assert second_claim.id != old_normal.id
    finally:
        await engine.dispose()


async def _seed_videos(session_factory) -> None:
    async with session_factory() as session:
        await session.execute(text("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')"))
        await session.execute(
            text(
                "INSERT INTO channels(id, streamer_id, handle, name) VALUES "
                "(1, 1, '@nagi', 'Nagi'), (2, 1, '@nagi2', 'Nagi 2')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                "published_at, created_at, is_embeddable) VALUES "
                "(1, 1, 'oldvideo001', 'Old', '', "
                "'2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00', 1), "
                "(2, 1, 'newvideo002', 'New', '', "
                "'2026-07-20T00:00:00+00:00', '2026-07-20T00:00:00+00:00', 1), "
                "(3, 2, 'latestvid03', 'Latest', '', "
                "'2026-07-25T00:00:00+00:00', '2026-07-25T00:00:00+00:00', 1)"
            )
        )
        await session.commit()


def _create_item(
    *,
    video_id: int,
    key: str,
    priority: int,
    now: datetime,
) -> CreateWorkItem:
    return CreateWorkItem(
        task_type="timeline_compose",
        subject_type="video",
        subject_id=video_id,
        external_key=f"video-{video_id}",
        task_version="v1",
        input_hash=key,
        idempotency_key=f"timeline_compose:video:{video_id}:v1:{key}",
        execution_mode=WorkExecutionMode.WORKER,
        timeout_seconds=600,
        input_json={"videoId": video_id},
        priority=priority,
        available_at=now,
    )
