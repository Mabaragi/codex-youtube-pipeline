"""Helpers for best-effort operation event recording."""

from __future__ import annotations

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)


async def record_operation_event(
    recorder: OperationEventRecorderPort,
    event: OperationEventCreate,
) -> None:
    try:
        await recorder.record_event(event)
    except Exception:
        return

