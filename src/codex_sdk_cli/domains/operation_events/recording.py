"""Helpers for best-effort operation event recording."""

from __future__ import annotations

import logging

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)

_LOGGER = logging.getLogger(__name__)


async def record_operation_event(
    recorder: OperationEventRecorderPort,
    event: OperationEventCreate,
) -> None:
    try:
        await recorder.record_event(event)
    except Exception:
        _LOGGER.exception(
            "operation_event_recording_failed",
            extra={
                "event_type": event.event_type,
                "subject_type": event.subject_type,
                "subject_id": event.subject_id,
            },
        )
        return
