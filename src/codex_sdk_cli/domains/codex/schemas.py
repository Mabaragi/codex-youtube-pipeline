from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr


class RunRequest(BaseModel):
    prompt: str = Field(
        min_length=1,
        description="User prompt to send to a Codex thread.",
        examples=["Explain how this project is structured."],
    )
    base_instructions: str | None = Field(
        default=None,
        alias="baseInstructions",
        description="Optional base instructions applied before the prompt.",
        examples=["Answer concisely and include file paths when relevant."],
    )
    developer_instructions: str | None = Field(
        default=None,
        alias="developerInstructions",
        description="Optional developer instructions for this run.",
        examples=["Do not modify files; only inspect the repository."],
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "prompt": "Explain how this project is structured.",
                    "baseInstructions": "Answer concisely and include file paths when relevant.",
                    "developerInstructions": "Do not modify files; only inspect the repository.",
                }
            ]
        },
    )


class RunResponse(BaseModel):
    thread_id: str = Field(alias="threadId")
    turn_id: str = Field(alias="turnId")
    status: str
    final_response: str = Field(alias="finalResponse")
    usage: Any | None = None

    model_config = ConfigDict(populate_by_name=True)


class ApiKeyLoginRequest(BaseModel):
    api_key: SecretStr = Field(
        alias="apiKey",
        min_length=1,
        description="OpenAI API key used for Codex authentication.",
        examples=["sk-proj-example"],
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"apiKey": "sk-proj-example"}]},
    )


class LoginResponse(BaseModel):
    success: bool
    error: str | None = None


class LogoutResponse(BaseModel):
    success: bool


class AccountResponse(RootModel[Any]):
    pass
