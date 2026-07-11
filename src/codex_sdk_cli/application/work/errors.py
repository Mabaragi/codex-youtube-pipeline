from __future__ import annotations

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind


class WorkItemNotFound(ApplicationError):
    def __init__(self, work_item_id: int) -> None:
        super().__init__(
            code="work_item.not_found",
            message="Work item was not found.",
            kind=ErrorKind.NOT_FOUND,
            details={"workItemId": work_item_id},
        )


class WorkItemTransitionNotAllowed(ApplicationError):
    def __init__(self, work_item_id: int, *, status: str, transition: str) -> None:
        super().__init__(
            code="work_item.transition_not_allowed",
            message=f"Cannot {transition} a work item with status {status}.",
            kind=ErrorKind.CONFLICT,
            details={
                "workItemId": work_item_id,
                "status": status,
                "transition": transition,
            },
        )


class WorkPersistenceError(ApplicationError):
    def __init__(self, message: str = "Work persistence failed.") -> None:
        super().__init__(
            code="work.persistence_failed",
            message=message,
            kind=ErrorKind.UNAVAILABLE,
        )
