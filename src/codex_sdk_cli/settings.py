from __future__ import annotations

from pathlib import Path
from typing import Literal

from openai_codex import CodexConfig
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ApprovalChoice = Literal["auto-review", "deny-all"]
SandboxChoice = Literal["read-only", "workspace-write", "full-access"]
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"


class CliSettings(BaseSettings):
    """Environment-backed defaults for the CLI."""

    model: str | None = None
    sandbox: SandboxChoice = "workspace-write"
    approval: ApprovalChoice = "auto-review"
    codex_bin: Path | None = None
    api_key: SecretStr | None = None
    youtube_http_proxy: str | None = None
    youtube_https_proxy: str | None = None
    transcript_minio_endpoint: str | None = None
    transcript_minio_access_key: SecretStr | None = None
    transcript_minio_secret_key: SecretStr | None = None
    transcript_minio_bucket: str | None = None
    transcript_minio_prefix: str = "youtube/transcripts"
    transcript_minio_secure: bool = False
    database_url: str = DEFAULT_DATABASE_URL
    database_echo: bool = False

    model_config = SettingsConfigDict(env_prefix="CODEX_CLI_", extra="ignore")

    @field_validator(
        "model",
        "codex_bin",
        "api_key",
        "youtube_http_proxy",
        "youtube_https_proxy",
        "transcript_minio_endpoint",
        "transcript_minio_access_key",
        "transcript_minio_secret_key",
        "transcript_minio_bucket",
        mode="before",
    )
    @classmethod
    def _blank_string_to_none(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_to_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_DATABASE_URL
        return value

    def codex_config(self) -> CodexConfig:
        return CodexConfig(codex_bin=str(self.codex_bin) if self.codex_bin else None)

    def api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        return self.api_key.get_secret_value()
