from __future__ import annotations

from pathlib import Path
from typing import Literal

from openai_codex import CodexConfig
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ApprovalChoice = Literal["auto-review", "deny-all"]
SandboxChoice = Literal["read-only", "workspace-write", "full-access"]
CodexModelChoice = Literal["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
ReasoningEffortChoice = Literal["low", "medium", "high", "xhigh"]
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
DEFAULT_CODEX_MODEL: CodexModelChoice = "gpt-5.5"
DEFAULT_CODEX_REASONING_EFFORT: ReasoningEffortChoice = "medium"
CODEX_MODEL_CHOICES: tuple[CodexModelChoice, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
)
CODEX_REASONING_EFFORT_CHOICES: tuple[ReasoningEffortChoice, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
)


class CliSettings(BaseSettings):
    """Environment-backed defaults for the CLI."""

    model: CodexModelChoice = DEFAULT_CODEX_MODEL
    reasoning_effort: ReasoningEffortChoice = DEFAULT_CODEX_REASONING_EFFORT
    sandbox: SandboxChoice = "workspace-write"
    approval: ApprovalChoice = "auto-review"
    codex_bin: Path | None = None
    api_key: SecretStr | None = None
    youtube_http_proxy: str | None = None
    youtube_https_proxy: str | None = None
    youtube_data_api_key: SecretStr | None = None
    youtube_data_timeout_seconds: float = 10.0
    transcript_collect_timeout_seconds: int = 600
    transcript_collect_concurrency_limit: int = 1
    transcript_collect_delay_seconds: int = 300
    transcript_cue_generate_timeout_seconds: int = 600
    transcript_cue_generate_concurrency_limit: int = 1
    micro_event_extract_timeout_seconds: int = 3600
    micro_event_extract_concurrency_limit: int = 3
    micro_event_worker_poll_interval_seconds: int = 5
    micro_event_worker_id: str | None = None
    timeline_compose_timeout_seconds: int = 3600
    timeline_compose_worker_poll_interval_seconds: int = 5
    timeline_compose_worker_id: str | None = None
    transcript_minio_endpoint: str | None = None
    transcript_minio_access_key: SecretStr | None = None
    transcript_minio_secret_key: SecretStr | None = None
    transcript_minio_bucket: str | None = None
    transcript_minio_prefix: str = "youtube/transcripts"
    transcript_minio_secure: bool = False
    external_api_call_minio_prefix: str = "external-api-calls"
    database_url: str = DEFAULT_DATABASE_URL
    database_echo: bool = False

    model_config = SettingsConfigDict(env_prefix="CODEX_CLI_", extra="ignore")

    @field_validator(
        "codex_bin",
        "api_key",
        "youtube_http_proxy",
        "youtube_https_proxy",
        "youtube_data_api_key",
        "micro_event_worker_id",
        "timeline_compose_worker_id",
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

    @field_validator("model", mode="before")
    @classmethod
    def _blank_model_to_default(cls, value: object) -> object:
        if value is None:
            return DEFAULT_CODEX_MODEL
        if isinstance(value, str) and not value.strip():
            return DEFAULT_CODEX_MODEL
        return value

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _blank_reasoning_effort_to_default(cls, value: object) -> object:
        if value is None:
            return DEFAULT_CODEX_REASONING_EFFORT
        if isinstance(value, str) and not value.strip():
            return DEFAULT_CODEX_REASONING_EFFORT
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_to_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_DATABASE_URL
        return value

    @field_validator(
        "transcript_collect_timeout_seconds",
        "transcript_collect_concurrency_limit",
        "transcript_cue_generate_timeout_seconds",
        "transcript_cue_generate_concurrency_limit",
        "micro_event_extract_timeout_seconds",
        "micro_event_extract_concurrency_limit",
        "micro_event_worker_poll_interval_seconds",
        "timeline_compose_timeout_seconds",
        "timeline_compose_worker_poll_interval_seconds",
    )
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("value must be greater than or equal to 1")
        return value

    @field_validator("transcript_collect_delay_seconds")
    @classmethod
    def _non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be greater than or equal to 0")
        return value

    def codex_config(self) -> CodexConfig:
        return CodexConfig(codex_bin=str(self.codex_bin) if self.codex_bin else None)

    def api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        return self.api_key.get_secret_value()

    def youtube_data_api_key_value(self) -> str | None:
        if self.youtube_data_api_key is None:
            return None
        return self.youtube_data_api_key.get_secret_value()
