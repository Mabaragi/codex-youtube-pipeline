"""Best-effort operation event recording."""

from __future__ import annotations

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventRepositoryPort,
)


class BestEffortOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self, repository: OperationEventRepositoryPort) -> None:
        self._repository = repository

    async def record_event(self, event: OperationEventCreate) -> None:
        try:
            await self._repository.create_event(event)
        except Exception:
            return

