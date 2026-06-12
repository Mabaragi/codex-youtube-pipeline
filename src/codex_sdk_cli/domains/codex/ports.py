from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from codex_sdk_cli.settings import ApprovalChoice, SandboxChoice


class CodexRunCommand(BaseModel):
    prompt: str
    thread_id: str | None
    cwd: Path | None
    model: str | None
    sandbox: SandboxChoice
    approval: ApprovalChoice
    persist: bool

    model_config = ConfigDict(frozen=True)


class CodexRunResult(BaseModel):
    thread_id: str
    turn_id: str
    status: str
    final_response: str
    usage: Any | None = None

    model_config = ConfigDict(frozen=True)


class CodexLoginResult(BaseModel):
    success: bool
    error: str | None = None

    model_config = ConfigDict(frozen=True)


class CodexRuntimePort(Protocol):
    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        """Run one Codex prompt."""

    async def login_with_device_code(self) -> CodexLoginResult:
        """Authenticate using the device code flow and persist login state in the Codex runtime."""

    async def login_api_key(self, api_key: str) -> None:
        """Persist API key login state in the Codex runtime."""

    async def account(self, *, refresh_token: bool = False) -> object:
        """Return the current Codex account state."""

    async def logout(self) -> None:
        """Clear the current Codex account session."""
