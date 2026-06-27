"""FastAPI dependencies for operation event use cases."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import OperationEventRepositoryDep
from codex_sdk_cli.domains.operation_events.use_cases import ListOperationEventsUseCase


def get_list_operation_events_use_case(
    repository: OperationEventRepositoryDep,
) -> ListOperationEventsUseCase:
    return ListOperationEventsUseCase(repository)


ListOperationEventsUseCaseDep = Annotated[
    ListOperationEventsUseCase,
    Depends(get_list_operation_events_use_case),
]

