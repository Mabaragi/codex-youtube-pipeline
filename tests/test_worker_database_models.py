from __future__ import annotations

import json
import subprocess
import sys


def test_micro_event_worker_runtime_registers_fk_target_models() -> None:
    assert _worker_runtime_registered_tables("codex_sdk_cli.workers.micro_events") == {
        "external_api_calls": True,
        "operation_events": True,
    }


def test_timeline_worker_runtime_registers_fk_target_models() -> None:
    assert _worker_runtime_registered_tables("codex_sdk_cli.workers.timelines") == {
        "external_api_calls": True,
        "operation_events": True,
    }


def _worker_runtime_registered_tables(module: str) -> dict[str, bool]:
    script = f"""
import asyncio
import importlib
import json

from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.settings import CliSettings

worker = importlib.import_module({module!r})
runtime = worker.WorkRuntime(
    CliSettings(database_url="sqlite+aiosqlite:///:memory:")
)
print(json.dumps({{
    "external_api_calls": "external_api_calls" in Base.metadata.tables,
    "operation_events": "operation_events" in Base.metadata.tables,
}}))
asyncio.run(runtime.close())
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)
