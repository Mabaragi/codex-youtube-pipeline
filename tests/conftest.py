from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


@pytest.fixture(scope="session")
def migrated_database_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    database_path = tmp_path_factory.mktemp("migrated-database") / "template.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    previous_database_url = os.environ.get("CODEX_CLI_DATABASE_URL")
    os.environ["CODEX_CLI_DATABASE_URL"] = database_url
    try:
        config = Config()
        config.set_main_option("script_location", "alembic")
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("CODEX_CLI_DATABASE_URL", None)
        else:
            os.environ["CODEX_CLI_DATABASE_URL"] = previous_database_url
    return database_path


@pytest.fixture
def migrated_database_path(
    tmp_path: Path,
    migrated_database_template: Path,
) -> Path:
    database_path = tmp_path / "app.db"
    shutil.copy2(migrated_database_template, database_path)
    return database_path
