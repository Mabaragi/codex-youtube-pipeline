from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import CodexRuntimeDep, SettingsDep
from codex_sdk_cli.domains.codex.use_cases import (
    CodexRunDefaults,
    GetCodexAccountUseCase,
    LoginCodexWithApiKeyUseCase,
    LoginCodexWithDeviceCodeUseCase,
    LogoutCodexUseCase,
    RunCodexPromptUseCase,
)


def get_run_codex_prompt_use_case(
    runtime: CodexRuntimeDep,
    settings: SettingsDep,
) -> RunCodexPromptUseCase:
    return RunCodexPromptUseCase(
        runtime,
        CodexRunDefaults(
            model=settings.model,
            reasoning_effort=settings.reasoning_effort,
            sandbox=settings.sandbox,
            approval=settings.approval,
        ),
    )


def get_codex_account_use_case(runtime: CodexRuntimeDep) -> GetCodexAccountUseCase:
    return GetCodexAccountUseCase(runtime)


def get_login_codex_with_device_code_use_case(
    runtime: CodexRuntimeDep,
) -> LoginCodexWithDeviceCodeUseCase:
    return LoginCodexWithDeviceCodeUseCase(runtime)


def get_login_codex_with_api_key_use_case(
    runtime: CodexRuntimeDep,
) -> LoginCodexWithApiKeyUseCase:
    return LoginCodexWithApiKeyUseCase(runtime)


def get_logout_codex_use_case(runtime: CodexRuntimeDep) -> LogoutCodexUseCase:
    return LogoutCodexUseCase(runtime)


RunCodexPromptUseCaseDep = Annotated[
    RunCodexPromptUseCase,
    Depends(get_run_codex_prompt_use_case),
]
GetCodexAccountUseCaseDep = Annotated[
    GetCodexAccountUseCase,
    Depends(get_codex_account_use_case),
]
LoginCodexWithDeviceCodeUseCaseDep = Annotated[
    LoginCodexWithDeviceCodeUseCase,
    Depends(get_login_codex_with_device_code_use_case),
]
LoginCodexWithApiKeyUseCaseDep = Annotated[
    LoginCodexWithApiKeyUseCase,
    Depends(get_login_codex_with_api_key_use_case),
]
LogoutCodexUseCaseDep = Annotated[
    LogoutCodexUseCase,
    Depends(get_logout_codex_use_case),
]
