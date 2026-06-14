from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from typing_extensions import override

from codex_sdk_cli.domains.codex.exceptions import CodexRuntimeError, InvalidCodexRequest
from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
)
from codex_sdk_cli.runner import (
    CodexCliError,
    RunRequest,
    account_json,
    login_with_api_key,
    login_with_device_code,
    logout_codex,
    open_codex,
    parse_approval,
    parse_sandbox,
    run_prompt,
)
from codex_sdk_cli.settings import CliSettings

T = TypeVar("T")


class CodexRuntimeClient(CodexRuntimePort):
    def __init__(self, settings: CliSettings) -> None:
        self._settings = settings

    @override
    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        async def operation() -> CodexRunResult:
            async with open_codex(self._settings.codex_config()) as codex:
                output = await run_prompt(
                    codex,
                    RunRequest(
                        prompt=command.prompt,
                        thread_id=command.thread_id,
                        cwd=command.cwd,
                        model=command.model,
                        sandbox=parse_sandbox(command.sandbox),
                        approval_mode=parse_approval(command.approval),
                        persist=command.persist,
                        base_instructions=command.base_instructions,
                        developer_instructions=command.developer_instructions,
                    ),
                )
            return CodexRunResult(
                thread_id=output.thread_id,
                turn_id=output.turn_id,
                status=output.status,
                final_response=output.final_response,
                usage=output.usage,
            )

        return await self._translate_errors(operation)

    @override
    async def login_with_device_code(self) -> CodexLoginResult:
        async def operation() -> CodexLoginResult:
            async with open_codex(self._settings.codex_config()) as codex:
                output = await login_with_device_code(
                    codex,
                    announce_code=lambda url, code: print(
                        f"To log in, visit {url} and enter the code: {code}"
                    ),
                )
            return CodexLoginResult(success=output.success, error=output.error)

        return await self._translate_errors(operation)

    async def login_api_key(self, api_key: str) -> None:
        async def operation() -> None:
            async with open_codex(self._settings.codex_config()) as codex:
                await login_with_api_key(codex, api_key)

        await self._translate_errors(operation)

    async def account(self, *, refresh_token: bool = False) -> object:
        async def operation() -> object:
            async with open_codex(self._settings.codex_config()) as codex:
                return await account_json(codex, refresh_token=refresh_token)

        return await self._translate_errors(operation)

    async def logout(self) -> None:
        async def operation() -> None:
            async with open_codex(self._settings.codex_config()) as codex:
                await logout_codex(codex)

        await self._translate_errors(operation)

    async def _translate_errors(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            return await operation()
        except CodexCliError as exc:
            raise InvalidCodexRequest(str(exc)) from exc
        except Exception as exc:
            raise CodexRuntimeError("Codex runtime operation failed.") from exc
