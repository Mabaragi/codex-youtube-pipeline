from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    OperationEventRecorderDep,
    OperationEventRepositoryDep,
)
from codex_sdk_cli.application.operation_events.operator_audit import (
    RecordOperatorMutationUseCase,
)
from codex_sdk_cli.domains.operation_events.use_cases import ListOperationEventsUseCase


def get_list_operation_events_use_case(
    repository: OperationEventRepositoryDep,
) -> ListOperationEventsUseCase:
    return ListOperationEventsUseCase(repository)


def get_record_operator_mutation_use_case(
    recorder: OperationEventRecorderDep,
) -> RecordOperatorMutationUseCase:
    return RecordOperatorMutationUseCase(recorder)


RecordOperatorMutationUseCaseDep = Annotated[
    RecordOperatorMutationUseCase,
    Depends(get_record_operator_mutation_use_case),
]
ListOperationEventsUseCaseDep = Annotated[
    ListOperationEventsUseCase,
    Depends(get_list_operation_events_use_case),
]
