"""Best-effort operation event recording."""

from __future__ import annotations

import logging

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventRepositoryPort,
)

_LOGGER = logging.getLogger(__name__)


class BestEffortOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self, repository: OperationEventRepositoryPort) -> None:
        self._repository = repository

    async def record_event(self, event: OperationEventCreate) -> None:
        try:
            await self._repository.create_event(event)
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
