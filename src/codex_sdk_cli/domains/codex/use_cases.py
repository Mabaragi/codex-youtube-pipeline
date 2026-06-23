from __future__ import annotations

from codex_sdk_cli.settings import CliSettings

from .exceptions import InvalidCodexRequest
from .ports import CodexRunCommand, CodexRuntimePort, CodexRunUsageContext
from .schemas import (
    AccountResponse,
    ApiKeyLoginRequest,
    LoginResponse,
    LogoutResponse,
    RunRequest,
    RunResponse,
)


class RunCodexPromptUseCase:
    def __init__(self, runtime: CodexRuntimePort, settings: CliSettings) -> None:
        self._runtime = runtime
        self._settings = settings

    async def execute(self, request: RunRequest) -> RunResponse:
        prompt = request.prompt.strip()
        if not prompt:
            raise InvalidCodexRequest("Prompt cannot be empty.")

        result = await self._runtime.run_prompt(
            CodexRunCommand(
                prompt=prompt,
                thread_id=None,
                cwd=None,
                model=self._settings.model,
                sandbox=self._settings.sandbox,
                approval=self._settings.approval,
                persist=False,
                base_instructions=_instruction_or_blank(request.base_instructions),
                developer_instructions=_instruction_or_blank(request.developer_instructions),
                usage_context=CodexRunUsageContext(
                    source="codex_runs",
                    operation="run_prompt",
                ),
            )
        )
        return RunResponse.model_validate(result.model_dump())


class GetCodexAccountUseCase:
    def __init__(self, runtime: CodexRuntimePort) -> None:
        self._runtime = runtime

    async def execute(self, *, refresh_token: bool = False) -> AccountResponse:
        return AccountResponse(root=await self._runtime.account(refresh_token=refresh_token))


class LoginCodexWithDeviceCodeUseCase:
    def __init__(self, runtime: CodexRuntimePort) -> None:
        self._runtime = runtime

    async def execute(self) -> LoginResponse:
        output = await self._runtime.login_with_device_code()
        return LoginResponse(success=output.success, error=output.error)


class LoginCodexWithApiKeyUseCase:
    def __init__(self, runtime: CodexRuntimePort) -> None:
        self._runtime = runtime

    async def execute(self, request: ApiKeyLoginRequest) -> LoginResponse:
        api_key = request.api_key.get_secret_value().strip()
        if not api_key:
            raise InvalidCodexRequest("API key cannot be empty.")

        await self._runtime.login_api_key(api_key)
        return LoginResponse(success=True)


class LogoutCodexUseCase:
    def __init__(self, runtime: CodexRuntimePort) -> None:
        self._runtime = runtime

    async def execute(self) -> LogoutResponse:
        await self._runtime.logout()
        return LogoutResponse(success=True)


def _instruction_or_blank(value: str | None) -> str:
    if value is None:
        return " "

    normalized = value.strip()
    return normalized if normalized else " "
