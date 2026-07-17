from __future__ import annotations

from typing import Literal

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event

OperatorMutation = Literal["deleted", "archived", "relationship_removed"]


class RecordOperatorMutationUseCase:
    def __init__(self, recorder: OperationEventRecorderPort) -> None:
        self._recorder = recorder

    async def execute(
        self,
        *,
        mutation: OperatorMutation,
        target_type: str,
        target_id: int,
        action: str,
        reason: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        event_type = {
            "deleted": "operator.resource_deleted",
            "archived": "operator.resource_archived",
            "relationship_removed": "operator.relationship_removed",
        }[mutation]
        await record_operation_event(
            self._recorder,
            OperationEventCreate(
                event_type=event_type,
                severity="warning",
                message=f"Operator {action} {target_type} {target_id}.",
                actor_type="manual_api",
                source="ops_api",
                subject_type=target_type,
                subject_id=target_id,
                metadata_json={
                    "targetType": target_type,
                    "targetId": target_id,
                    "action": action,
                    "reason": reason,
                    **(metadata or {}),
                },
            ),
        )
