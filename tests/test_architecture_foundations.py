from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind
from codex_sdk_cli.bootstrap.config import application_config
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.database.unit_of_work import SqlAlchemyUnitOfWork
from codex_sdk_cli.settings import CliSettings


def test_application_config_projects_environment_settings() -> None:
    settings = CliSettings(
        database_url="sqlite+aiosqlite:///./data/test.db",
        database_echo=True,
        micro_event_extract_concurrency_limit=6,
        timeline_compose_timeout_seconds=1800,
    )

    config = application_config(settings)

    assert config.database.url == settings.database_url
    assert config.database.echo is True
    assert config.micro_event.concurrency_limit == 6
    assert config.timeline.timeout_seconds == 1800
    assert config.codex.model == settings.model


def test_application_error_exposes_transport_neutral_descriptor() -> None:
    error = ApplicationError(
        code="video.not_found",
        message="Video was not found.",
        kind=ErrorKind.NOT_FOUND,
        details={"videoId": 7},
    )

    assert error.descriptor.code == "video.not_found"
    assert error.descriptor.kind is ErrorKind.NOT_FOUND
    assert error.descriptor.details == {"videoId": 7}


def test_sqlalchemy_unit_of_work_commits_and_rolls_back(tmp_path: Path) -> None:
    asyncio.run(_exercise_unit_of_work(tmp_path))


async def _exercise_unit_of_work(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'uow.db').as_posix()}"
    )
    session_factory = create_session_factory(engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE values_table (value INTEGER NOT NULL)"))

        async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            await unit_of_work.session.execute(
                text("INSERT INTO values_table(value) VALUES (1)")
            )
            await unit_of_work.commit()

        with pytest.raises(RuntimeError):
            async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
                await unit_of_work.session.execute(
                    text("INSERT INTO values_table(value) VALUES (2)")
                )
                raise RuntimeError("rollback")

        async with session_factory() as session:
            values = list((await session.execute(text("SELECT value FROM values_table"))).scalars())
        assert values == [1]
    finally:
        await engine.dispose()

