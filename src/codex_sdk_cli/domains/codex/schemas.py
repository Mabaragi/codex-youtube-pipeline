from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr

from codex_sdk_cli.settings import ApprovalChoice, SandboxChoice


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    thread_id: str | None = Field(default=None, alias="threadId")
    cwd: Path | None = None
    model: str | None = None
    sandbox: SandboxChoice | None = None
    approval: ApprovalChoice | None = None
    persist: bool = False
    empty_base_instructions: bool = Field(default=False, alias="emptyBaseInstructions")
    empty_developer_instructions: bool = Field(default=False, alias="emptyDeveloperInstructions")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class RunResponse(BaseModel):
    thread_id: str = Field(alias="threadId")
    turn_id: str = Field(alias="turnId")
    status: str
    final_response: str = Field(alias="finalResponse")
    usage: Any | None = None

    model_config = ConfigDict(populate_by_name=True)


class ApiKeyLoginRequest(BaseModel):
    api_key: SecretStr = Field(alias="apiKey", min_length=1)

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class LoginResponse(BaseModel):
    success: bool
    error: str | None = None


class LogoutResponse(BaseModel):
    success: bool


class AccountResponse(RootModel[Any]):
    pass
