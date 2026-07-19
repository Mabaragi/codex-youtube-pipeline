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


class WorkItemRetrySuperseded(ApplicationError):
    def __init__(self, work_item_id: int, *, replacement_work_item_id: int) -> None:
        super().__init__(
            code="work_item.retry_superseded",
            message="A newer succeeded work item already replaces this work item.",
            kind=ErrorKind.CONFLICT,
            details={
                "workItemId": work_item_id,
                "replacementWorkItemId": replacement_work_item_id,
            },
        )


class WorkItemRetryInputUnavailable(ApplicationError):
    def __init__(self, work_item_id: int, *, invalid_fields: tuple[str, ...]) -> None:
        super().__init__(
            code="work_item.retry_input_unavailable",
            message="The stored work input is incomplete and cannot be retried safely.",
            kind=ErrorKind.CONFLICT,
            details={
                "workItemId": work_item_id,
                "invalidFields": list(invalid_fields),
            },
        )


class WorkBatchNotFound(ApplicationError):
    def __init__(self, batch_id: int) -> None:
        super().__init__(
            code="work_batch.not_found",
            message="Work batch was not found.",
            kind=ErrorKind.NOT_FOUND,
            details={"batchId": batch_id},
        )


class WorkflowRunNotFound(ApplicationError):
    def __init__(self, workflow_run_id: int) -> None:
        super().__init__(
            code="workflow_run.not_found",
            message="Workflow run was not found.",
            kind=ErrorKind.NOT_FOUND,
            details={"workflowRunId": workflow_run_id},
        )


class WorkPersistenceError(ApplicationError):
    def __init__(self, message: str = "Work persistence failed.") -> None:
        super().__init__(
            code="work.persistence_failed",
            message=message,
            kind=ErrorKind.UNAVAILABLE,
        )
