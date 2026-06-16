from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository


def test_external_api_call_repository_creates_metadata_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'external-api-calls.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    record = asyncio.run(_save_record(database_url))

    assert record.id == 1
    assert record.provider == "youtube_data"
    assert record.operation == "channels.list"
    assert record.request_params == {"part": "id,snippet", "forHandle": "@GoogleDevelopers"}
    assert record.response_storage_object_name == "external-api-calls/object.json"
    assert record.response_sha256 == "0" * 64
    assert record.validation_status == "valid"


async def _save_record(database_url: str):
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyExternalApiCallRepository(session)
            return await repository.create_external_api_call(
                ExternalApiCallCreate(
                    provider="youtube_data",
                    operation="channels.list",
                    request_method="GET",
                    request_url="https://www.googleapis.com/youtube/v3/channels",
                    request_params={
                        "part": "id,snippet",
                        "forHandle": "@GoogleDevelopers",
                    },
                    request_body=None,
                    response_status_code=200,
                    response_headers={"content-type": "application/json"},
                    response_storage_bucket="raw",
                    response_storage_object_name="external-api-calls/object.json",
                    response_storage_uri="s3://raw/external-api-calls/object.json",
                    response_sha256="0" * 64,
                    schema_name="YouTubeChannelsListResponse",
                    schema_version="v1",
                    validation_status="valid",
                    validation_error=None,
                    duration_ms=12,
                    quota_cost=1,
                )
            )
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
