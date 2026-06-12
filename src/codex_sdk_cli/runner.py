from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
from openai_codex import AsyncThread as SdkAsyncThread

from .settings import ApprovalChoice, SandboxChoice


class CodexCliError(Exception):
    """Raised when CLI input cannot be translated to a Codex SDK request."""


BLANK_BASE_INSTRUCTIONS = " "


@dataclass(frozen=True, slots=True)
class RunRequest:
    prompt: str
    thread_id: str | None
    cwd: Path | None
    model: str | None
    sandbox: Sandbox
    approval_mode: ApprovalMode
    persist: bool
    empty_base_instructions: bool


@dataclass(frozen=True, slots=True)
class RunOutput:
    thread_id: str
    turn_id: str
    status: str
    final_response: str
    usage: object | None


@dataclass(frozen=True, slots=True)
class LoginOutput:
    success: bool
    error: str | None = None


class TurnResultLike(Protocol):
    @property
    def id(self) -> str:
        """Turn id."""

    @property
    def status(self) -> object:
        """Turn status."""

    @property
    def final_response(self) -> str | None:
        """Final assistant response."""

    @property
    def usage(self) -> object | None:
        """Token usage, when available."""


class ThreadLike(Protocol):
    @property
    def id(self) -> str:
        """Thread id."""

    def run(self, input: str) -> Awaitable[TurnResultLike]:
        """Run a Codex turn."""


class ChatgptLoginHandleLike(Protocol):
    auth_url: str

    def wait(self) -> Awaitable[object]:
        """Wait for login completion."""


class DeviceCodeLoginHandleLike(Protocol):
    verification_url: str
    user_code: str

    def wait(self) -> Awaitable[object]:
        """Wait for login completion."""


class CodexLike(Protocol):
    def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        base_instructions: str | None = None,
        cwd: str | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> Awaitable[ThreadLike]:
        """Start a new Codex thread."""

    def thread_resume(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> Awaitable[ThreadLike]:
        """Resume an existing Codex thread."""

    def login_chatgpt(self) -> Awaitable[ChatgptLoginHandleLike]:
        """Start browser-based ChatGPT login."""

    def login_chatgpt_device_code(self) -> Awaitable[DeviceCodeLoginHandleLike]:
        """Start device-code ChatGPT login."""

    def login_api_key(self, api_key: str) -> Awaitable[None]:
        """Log in with an API key."""

    def account(self, *, refresh_token: bool = False) -> Awaitable[object]:
        """Read current account state."""

    def logout(self) -> Awaitable[None]:
        """Clear current account state."""


@runtime_checkable
class JsonDumpable(Protocol):
    def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> object:
        """Return a JSON-compatible object."""


@dataclass(frozen=True, slots=True)
class SdkThreadAdapter(ThreadLike):
    _thread: SdkAsyncThread

    @property
    def id(self) -> str:
        return self._thread.id

    async def run(self, input: str) -> TurnResultLike:
        return await self._thread.run(input)


@dataclass(frozen=True, slots=True)
class CodexSdkAdapter(CodexLike):
    _codex: AsyncCodex

    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        base_instructions: str | None = None,
        cwd: str | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> ThreadLike:
        return SdkThreadAdapter(
            await self._codex.thread_start(
                approval_mode=approval_mode,
                base_instructions=base_instructions,
                cwd=cwd,
                ephemeral=ephemeral,
                model=model,
                sandbox=sandbox,
            )
        )

    async def thread_resume(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> ThreadLike:
        return SdkThreadAdapter(
            await self._codex.thread_resume(
                thread_id,
                approval_mode=approval_mode,
                base_instructions=base_instructions,
                cwd=cwd,
                model=model,
                sandbox=sandbox,
            )
        )

    async def login_chatgpt(self) -> ChatgptLoginHandleLike:
        return await self._codex.login_chatgpt()

    async def login_chatgpt_device_code(self) -> DeviceCodeLoginHandleLike:
        return await self._codex.login_chatgpt_device_code()

    async def login_api_key(self, api_key: str) -> None:
        await self._codex.login_api_key(api_key)

    async def account(self, *, refresh_token: bool = False) -> object:
        return await self._codex.account(refresh_token=refresh_token)

    async def logout(self) -> None:
        await self._codex.logout()


@asynccontextmanager
async def open_codex(config: CodexConfig) -> AsyncGenerator[CodexLike, None]:
    async with AsyncCodex(config=config) as codex:
        yield CodexSdkAdapter(codex)


def parse_sandbox(value: SandboxChoice) -> Sandbox:
    match value:
        case "read-only":
            return Sandbox.read_only
        case "workspace-write":
            return Sandbox.workspace_write
        case "full-access":
            return Sandbox.full_access


def parse_approval(value: ApprovalChoice) -> ApprovalMode:
    match value:
        case "auto-review":
            return ApprovalMode.auto_review
        case "deny-all":
            return ApprovalMode.deny_all


async def run_prompt(codex: CodexLike, request: RunRequest) -> RunOutput:
    cwd = str(request.cwd) if request.cwd is not None else None
    base_instructions = BLANK_BASE_INSTRUCTIONS if request.empty_base_instructions else None

    if request.thread_id is None:
        thread = await codex.thread_start(
            approval_mode=request.approval_mode,
            base_instructions=base_instructions,
            cwd=cwd,
            ephemeral=not request.persist,
            model=request.model,
            sandbox=request.sandbox,
        )
    else:
        thread = await codex.thread_resume(
            request.thread_id,
            approval_mode=request.approval_mode,
            base_instructions=base_instructions,
            cwd=cwd,
            model=request.model,
            sandbox=request.sandbox,
        )

    result = await thread.run(request.prompt)

    return RunOutput(
        thread_id=thread.id,
        turn_id=result.id,
        status=_status_value(result.status),
        final_response=result.final_response or "",
        usage=result.usage,
    )


async def login_with_browser(
    codex: CodexLike,
    *,
    announce_url: Callable[[str], None],
) -> LoginOutput:
    handle = await codex.login_chatgpt()
    announce_url(handle.auth_url)
    return _login_output(await handle.wait())


async def login_with_device_code(
    codex: CodexLike,
    *,
    announce_code: Callable[[str, str], None],
) -> LoginOutput:
    handle = await codex.login_chatgpt_device_code()
    announce_code(handle.verification_url, handle.user_code)
    return _login_output(await handle.wait())


async def login_with_api_key(codex: CodexLike, api_key: str) -> LoginOutput:
    if not api_key.strip():
        raise CodexCliError("API key cannot be empty.")

    await codex.login_api_key(api_key)
    return LoginOutput(success=True)


async def account_json(codex: CodexLike, *, refresh_token: bool = False) -> object:
    return to_jsonable(await codex.account(refresh_token=refresh_token))


async def logout_codex(codex: CodexLike) -> None:
    await codex.logout()


def to_jsonable(value: object) -> object:
    if isinstance(value, JsonDumpable):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Enum):
        return value.value
    return value


def _status_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _login_output(completion: object) -> LoginOutput:
    success = getattr(completion, "success", False)
    error = getattr(completion, "error", None)
    return LoginOutput(success=bool(success), error=str(error) if error is not None else None)
