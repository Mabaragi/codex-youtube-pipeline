from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.application.work.ports import CreateWorkItem, WorkItemQuery
from codex_sdk_cli.domains.work.models import WorkExecutionMode, WorkItemStatus
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


def test_work_repository_enforces_dependencies_and_retry_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_work_repository(database_url))


async def _exercise_work_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            await session.execute(text("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')"))
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@nagi', 'Nagi')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                    "published_at) VALUES "
                    "(1, 1, 'abcdefghijk', 'Test', '', '2026-07-01T00:00:00+00:00')"
                )
            )
            await session.commit()

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            upstream, created = await unit_of_work.work_items.get_or_create(
                _create_item("transcript_collect", "upstream", now)
            )
            downstream, _ = await unit_of_work.work_items.get_or_create(
                _create_item("transcript_cue_generate", "downstream", now)
            )
            await unit_of_work.work_items.add_dependency(
                work_item_id=downstream.id,
                dependency_work_item_id=upstream.id,
            )
            await unit_of_work.commit()
        assert created is True

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            blocked_claim = await unit_of_work.work_items.claim_next(
                task_types=("transcript_cue_generate",),
                worker_id="worker:test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            claimed_upstream = await unit_of_work.work_items.claim_next(
                task_types=("transcript_collect",),
                worker_id="worker:test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            assert blocked_claim is None
            assert claimed_upstream is not None
            attempt = await unit_of_work.work_attempts.create(
                work_item_id=claimed_upstream.id,
                worker_id="worker:test",
            )
            await unit_of_work.commit()

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            await unit_of_work.work_attempts.mark_succeeded(
                attempt_id=attempt.id,
                now=now,
                output_json={"reason": "no transcript"},
            )
            await unit_of_work.work_items.mark_succeeded(
                work_item_id=upstream.id,
                now=now,
                output_json={"reason": "no transcript"},
                outcome_code="no_transcript",
            )
            blocked_count = await unit_of_work.work_items.mark_dependency_blocked(now=now)
            await unit_of_work.commit()
        assert blocked_count == 1

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            blocked = await unit_of_work.work_items.get(downstream.id)
            retried = await unit_of_work.work_items.reset_for_retry(
                work_item_id=upstream.id,
                now=now + timedelta(minutes=1),
                allow_succeeded=True,
            )
            duplicate, duplicate_created = await unit_of_work.work_items.get_or_create(
                _create_item("transcript_collect", "upstream", now)
            )
            listed = await unit_of_work.work_items.list_items(
                WorkItemQuery(subject_type="video", subject_id=1, limit=10)
            )
            await unit_of_work.commit()

        assert blocked is not None
        assert blocked.status is WorkItemStatus.BLOCKED
        assert blocked.outcome_code == "dependency_failed"
        assert retried.status is WorkItemStatus.PENDING
        assert duplicate.id == upstream.id
        assert duplicate_created is False
        assert {item.id for item in listed} == {upstream.id, downstream.id}

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            canceled_count = await unit_of_work.work_items.cancel_pending_for_subject(
                subject_type="video",
                subject_id=1,
                task_types=("transcript_collect",),
                now=now + timedelta(minutes=2),
                outcome_code="not_embeddable",
                reason="Video cannot be embedded.",
            )
            canceled = await unit_of_work.work_items.get(upstream.id)
            await unit_of_work.commit()

        assert canceled_count == 1
        assert canceled is not None
        assert canceled.status is WorkItemStatus.CANCELED
        assert canceled.outcome_code == "not_embeddable"
    finally:
        await engine.dispose()


def _create_item(task_type: str, key: str, now: datetime) -> CreateWorkItem:
    return CreateWorkItem(
        task_type=task_type,
        subject_type="video",
        subject_id=1,
        external_key="abcdefghijk",
        task_version="v1",
        input_hash=key,
        idempotency_key=f"{task_type}:video:1:v1:{key}",
        execution_mode=WorkExecutionMode.WORKER,
        timeout_seconds=600,
        input_json={"videoId": 1},
        available_at=now,
    )
