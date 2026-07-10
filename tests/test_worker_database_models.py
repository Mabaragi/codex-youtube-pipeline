from __future__ import annotations

import json
import subprocess
import sys


def test_micro_event_worker_import_registers_fk_target_models() -> None:
    assert _worker_registered_tables("codex_sdk_cli.workers.micro_events") == {
        "external_api_calls": True,
        "operation_events": True,
    }


def test_timeline_worker_import_registers_fk_target_models() -> None:
    assert _worker_registered_tables("codex_sdk_cli.workers.timelines") == {
        "external_api_calls": True,
        "operation_events": True,
    }


def _worker_registered_tables(module: str) -> dict[str, bool]:
    script = f"""
import importlib
import json

from codex_sdk_cli.infra.database.base import Base

importlib.import_module({module!r})
print(json.dumps({{
    "external_api_calls": "external_api_calls" in Base.metadata.tables,
    "operation_events": "operation_events" in Base.metadata.tables,
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)
