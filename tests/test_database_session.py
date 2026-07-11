from __future__ import annotations

import subprocess
import sys


def test_engine_factory_registers_complete_model_metadata_in_fresh_process() -> None:
    command = """
import asyncio
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.database.session import create_database_engine

engine = create_database_engine('sqlite+aiosqlite:///:memory:')
required = {'work_items', 'youtube_transcripts', 'videos', 'workflow_runs'}
missing = required.difference(Base.metadata.tables)
if missing:
    raise SystemExit(f'missing model tables: {sorted(missing)}')
asyncio.run(engine.dispose())
"""

    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
