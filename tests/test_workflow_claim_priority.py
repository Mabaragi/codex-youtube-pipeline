from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.models import WorkflowRunModel, WorkflowStepModel, WorkItemModel
from codex_sdk_cli.infra.work.workflow_repository import SqlAlchemyWorkflowRepository


@pytest.mark.parametrize(
    ("status", "execution_mode", "workflow_status", "normal_first"),
    [
        ("succeeded", "worker", "waiting", True),
        ("failed", "worker", "waiting", True),
        ("pending", "inline", "waiting", True),
        ("pending", "worker", "waiting", False),
        ("running", "worker", "waiting", False),
        ("pending", "worker", "pending", True),
    ],
)
def test_ready_normal_workflows_precede_backfill_without_blocking_on_busy_workers(
    migrated_database_path: Path,
    status: str,
    execution_mode: str,
    workflow_status: str,
    normal_first: bool,
) -> None:
    asyncio.run(
        _exercise(migrated_database_path, status, execution_mode, workflow_status, normal_first)
    )


async def _exercise(
    path: Path, status: str, execution_mode: str, workflow_status: str, normal_first: bool
) -> None:
    now = datetime.now(UTC)
    engine = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            await session.execute(
                text("INSERT INTO streamers(id,name,publish_profile_id) VALUES (1,'Test',1)")
            )
            await session.execute(
                text("INSERT INTO channels(id,streamer_id,handle,name) VALUES (1,1,'@test','Test')")
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id,channel_id,youtube_video_id,title,description,"
                    "published_at) "
                    "VALUES (1,1,'priority','Test','',:now)"
                ),
                {"now": now},
            )
            backfill = WorkflowRunModel(
                workflow_type="classify_to_publish",
                workflow_version="v3",
                video_id=1,
                input_hash="a" * 64,
                options_json={},
                status="waiting",
                current_stage="segment_classify",
                available_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
            normal = WorkflowRunModel(
                workflow_type="process_to_publish",
                workflow_version="v3",
                video_id=1,
                input_hash="b" * 64,
                options_json={},
                status=workflow_status,
                current_stage="timeline_compose",
                available_at=now,
                updated_at=now,
            )
            work = WorkItemModel(
                task_type="timeline_compose",
                subject_type="video",
                subject_id=1,
                task_version="v1",
                input_hash="c" * 64,
                idempotency_key="priority-test",
                execution_mode=execution_mode,
                status=status,
                timeout_seconds=600,
                input_json={},
                available_at=now,
            )
            session.add_all([backfill, normal, work])
            await session.flush()
            session.add(
                WorkflowStepModel(
                    workflow_run_id=normal.id,
                    stage_name="timeline_compose",
                    position=1,
                    work_item_id=work.id,
                    status=status,
                )
            )
            await session.commit()
            claimed = await SqlAlchemyWorkflowRepository(session).claim_next(
                worker_id="priority:test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            assert claimed is not None
            assert claimed.id == (normal.id if normal_first else backfill.id)
    finally:
        await engine.dispose()
