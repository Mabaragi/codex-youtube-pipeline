from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.codex_usage.ports import CodexUsageCreate, CodexUsageListQuery
from codex_sdk_cli.infra.codex_usage.repository import SqlAlchemyCodexUsageRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory


def test_codex_usage_repository_creates_lists_and_summarizes_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'codex-usage.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    result = asyncio.run(_exercise_repository(database_url))

    assert result == {
        "first_source": "micro_event_extract",
        "first_total_tokens": 33,
        "summary_run_count": 2,
        "summary_total_tokens": 43,
        "source_summary_run_count": 1,
        "next_cursor": 1,
    }


async def _exercise_repository(database_url: str) -> dict[str, int | str | None]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyCodexUsageRepository(session)
            await repository.create_usage(
                CodexUsageCreate(
                    source="codex_runs",
                    operation="run_prompt",
                    model="gpt-test",
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
                    video_id=None,
                    video_task_id=None,
                    job_id=None,
                    job_attempt_id=None,
                    transcript_id=None,
                    window_index=1,
                )
            )

            all_rows = await repository.list_usages(CodexUsageListQuery(limit=1))
            source_rows = await repository.list_usages(
                CodexUsageListQuery(source="micro_event_extract", limit=50)
            )
            return {
                "first_source": all_rows.items[0].source,
                "first_total_tokens": all_rows.items[0].total_tokens,
                "summary_run_count": all_rows.summary.run_count,
                "summary_total_tokens": all_rows.summary.total_tokens,
                "source_summary_run_count": source_rows.summary.run_count,
                "next_cursor": all_rows.next_cursor,
            }
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
