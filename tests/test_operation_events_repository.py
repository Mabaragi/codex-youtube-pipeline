from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventListQuery,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.operation_events.repository import SQLAlchemyOperationEventRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository


def test_operation_event_repository_creates_and_filters_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'operation-events.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            events = SQLAlchemyOperationEventRepository(session)
            job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="video_collect",
                    status="running",
                    subject_type="channel",
                    subject_id=7,
                    external_key="UC123",
                    input_json={"channelId": 7},
                    input_hash="0" * 64,
                )
            )
            attempt = await pipeline_jobs.create_attempt(job_id=job.id)

            requested = await events.create_event(
                OperationEventCreate(
                    event_type="video_collect.requested",
                    severity="info",
                    message="requested",
                    actor_type="manual_api",
                    source="videos.collect",
                    job_id=job.id,
                    job_attempt_id=attempt.id,
                    subject_type="channel",
                    subject_id=7,
                    external_key="UC123",
                    metadata_json={"channelId": 7},
                )
            )
            failed = await events.create_event(
                OperationEventCreate(
                    event_type="video_collect.failed",
                    severity="error",
                    message="failed",
                    actor_type="retry_executor",
                    source="videos.collect",
                    job_id=job.id,
                    job_attempt_id=attempt.id,
                    subject_type="channel",
                    subject_id=7,
                    external_key="UC123",
                    error_type="UpstreamError",
                    error_message="upstream failed",
                    metadata_json={"attemptId": attempt.id},
                )
            )

            newest = await events.list_events(OperationEventListQuery(limit=10))
            errors = await events.list_events(
                OperationEventListQuery(limit=10, severity="error")
            )
            by_job = await events.list_events(OperationEventListQuery(limit=10, job_id=job.id))
            by_subject = await events.list_events(
                OperationEventListQuery(limit=10, subject_type="channel", subject_id=7)
            )
            after_cursor = await events.list_events(
                OperationEventListQuery(limit=10, cursor=failed.id)
            )

            assert requested.id < failed.id
            assert [event.event_type for event in newest] == [
                "video_collect.failed",
                "video_collect.requested",
            ]
            assert [event.id for event in errors] == [failed.id]
            assert [event.id for event in by_job] == [failed.id, requested.id]
            assert [event.id for event in by_subject] == [failed.id, requested.id]
            assert [event.id for event in after_cursor] == [requested.id]
            assert errors[0].error_message == "upstream failed"
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
