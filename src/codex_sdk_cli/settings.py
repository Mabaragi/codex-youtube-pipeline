from __future__ import annotations

from pathlib import Path
from typing import Literal

from openai_codex import CodexConfig
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ApprovalChoice = Literal["auto-review", "deny-all"]
SandboxChoice = Literal["read-only", "workspace-write", "full-access"]


class CliSettings(BaseSettings):
    """Environment-backed defaults for the CLI."""

    model: str | None = None
    sandbox: SandboxChoice = "workspace-write"
    approval: ApprovalChoice = "auto-review"
    codex_bin: Path | None = None
    api_key: SecretStr | None = None
    youtube_http_proxy: str | None = None
    youtube_https_proxy: str | None = None

    model_config = SettingsConfigDict(env_prefix="CODEX_CLI_", extra="ignore")

    @field_validator(
        "model",
        "codex_bin",
        "api_key",
        "youtube_http_proxy",
        "youtube_https_proxy",
        mode="before",
    )
    @classmethod
    def _blank_string_to_none(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def codex_config(self) -> CodexConfig:
        return CodexConfig(codex_bin=str(self.codex_bin) if self.codex_bin else None)

    def api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        return self.api_key.get_secret_value()
