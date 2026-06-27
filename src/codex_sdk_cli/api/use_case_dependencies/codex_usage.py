from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import CodexUsageRepositoryDep
from codex_sdk_cli.domains.codex_usage.use_cases import ListCodexUsageUseCase


async def get_list_codex_usage_use_case(
    repository: CodexUsageRepositoryDep,
) -> ListCodexUsageUseCase:
    return ListCodexUsageUseCase(repository)


ListCodexUsageUseCaseDep = Annotated[
    ListCodexUsageUseCase,
    Depends(get_list_codex_usage_use_case),
]
