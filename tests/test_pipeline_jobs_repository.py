from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository


def test_pipeline_job_repository_tracks_attempt_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'pipeline-jobs.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyPipelineJobRepository(session)
            job = await repository.create_job(
                PipelineJobCreate(
                    step="channel_resolve",
                    status="running",
                    subject_type="streamer",
                    subject_id=1,
                    external_key="@GoogleDevelopers",
                    input_json={"streamerId": 1, "handle": "@GoogleDevelopers"},
                    input_hash="0" * 64,
                )
            )

            first_attempt = await repository.create_attempt(job_id=job.id)
            second_attempt = await repository.create_attempt(job_id=job.id, worker_id="worker-1")
            failed_attempt = await repository.mark_attempt_failed(
                first_attempt.id,
                error_type="YouTubeDataUpstreamError",
                error_message="upstream failed",
            )
            succeeded_attempt = await repository.mark_attempt_succeeded(
                second_attempt.id,
                output_json={"channelId": 1, "jobId": job.id},
            )
            failed_job = await repository.mark_job_failed(job.id)
            succeeded_job = await repository.mark_job_succeeded(job.id)

            assert first_attempt.attempt_no == 1
            assert second_attempt.attempt_no == 2
            assert second_attempt.worker_id == "worker-1"
            assert failed_attempt.status == "failed"
            assert failed_attempt.error_type == "YouTubeDataUpstreamError"
            assert failed_attempt.finished_at is not None
            assert succeeded_attempt.status == "succeeded"
            assert succeeded_attempt.output_json == {"channelId": 1, "jobId": job.id}
            assert failed_job.status == "failed"
            assert failed_job.completed_at is not None
            assert succeeded_job.status == "succeeded"
            assert succeeded_job.completed_at is not None
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
