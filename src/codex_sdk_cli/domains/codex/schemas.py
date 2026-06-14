from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    base_instructions: str | None = Field(default=None, alias="baseInstructions")
    developer_instructions: str | None = Field(default=None, alias="developerInstructions")

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
