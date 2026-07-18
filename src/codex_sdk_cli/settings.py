from __future__ import annotations

from pathlib import Path

from openai_codex import CodexConfig
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from codex_sdk_cli.domains.codex.choices import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    ApprovalChoice,
    CodexModelChoice,
    ReasoningEffortChoice,
    SandboxChoice,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"


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
    ytdlp_bin: Path | None = None
    ffmpeg_bin: Path | None = None
    ffprobe_bin: Path | None = None
    youtube_data_api_key: SecretStr | None = None
    youtube_data_timeout_seconds: float = 10.0
    transcript_collect_timeout_seconds: int = 600
    transcript_collect_concurrency_limit: int = 1
    transcript_collect_delay_seconds: int = 300
    transcript_worker_poll_interval_seconds: int = 5
    transcript_worker_id: str | None = None
    pipeline_scheduler_enabled: bool = True
    pipeline_scheduler_poll_interval_seconds: int = 300
    pipeline_scheduler_channel_interval_seconds: int = 7200
    pipeline_scheduler_transcript_limit: int = 5
    pipeline_scheduler_no_transcript_recheck_interval_seconds: int = 604800
    pipeline_scheduler_no_transcript_limit: int = 2
    pipeline_scheduler_workflow_limit: int = 12
    pipeline_scheduler_transcript_fallback_grace_seconds: int = 21600
    pipeline_scheduler_transcript_recheck_interval_seconds: int = 1800
    pipeline_scheduler_id: str | None = None
    transcript_cue_generate_timeout_seconds: int = 600
    transcript_cue_generate_concurrency_limit: int = 1
    transcript_cue_worker_poll_interval_seconds: int = 5
    transcript_cue_worker_id: str | None = None
    asr_transcribe_timeout_seconds: int = 64800
    asr_transcribe_concurrency_limit: int = 1
    asr_worker_poll_interval_seconds: int = 5
    asr_worker_id: str | None = None
    micro_event_extract_timeout_seconds: int = 14400
    micro_event_extract_concurrency_limit: int = 1
    micro_event_window_concurrency_limit: int = 6
    micro_event_worker_poll_interval_seconds: int = 5
    micro_event_worker_id: str | None = None
    timeline_compose_timeout_seconds: int = 7200
    timeline_compose_concurrency_limit: int = 3
    timeline_compose_worker_poll_interval_seconds: int = 5
    timeline_compose_worker_id: str | None = None
    workflow_coordinator_poll_interval_seconds: int = 5
    workflow_coordinator_id: str | None = None
    pipeline_supervisor_enabled: bool = True
    pipeline_supervisor_poll_interval_seconds: int = 60
    pipeline_supervisor_id: str | None = None
    llm_trace_enabled: bool = True
    llm_trace_dir: Path = Path(".home-deploy/logs/llm-traces")
    local_runtime_pid_dir: Path = Path(".home-deploy/pids")
    llm_trace_raw_response_enabled: bool = True
    llm_trace_retention_days: int = 14
    archive_publish_timeout_seconds: int = 600
    archive_publish_r2_endpoint: str | None = None
    archive_publish_r2_access_key: SecretStr | None = None
    archive_publish_r2_secret_key: SecretStr | None = None
    archive_publish_r2_bucket: str | None = None
    archive_publish_r2_secure: bool = True
    archive_publish_public_base_url: str | None = None
    archive_publish_prefix: str = "archive"
    archive_publish_environment: str = "prod"
    archive_publish_dev_r2_endpoint: str | None = None
    archive_publish_dev_r2_access_key: SecretStr | None = None
    archive_publish_dev_r2_secret_key: SecretStr | None = None
    archive_publish_dev_r2_bucket: str | None = None
    archive_publish_dev_r2_secure: bool | None = None
    archive_publish_dev_public_base_url: str | None = None
    archive_publish_dev_prefix: str = "archive-dev"
    archive_publish_dev_environment: str = "dev"
    archive_public_catalog_sync_url: str | None = None
    archive_public_catalog_sync_token: SecretStr | None = None
    archive_public_catalog_sync_enabled: bool = True
    archive_public_catalog_sync_timeout_seconds: float = 15.0
    publish_connections_file: Path | None = Path(
        ".home-deploy/publish-connections.json"
    )
    publication_artifact_store_ref: str = "local-artifact-store"
    publication_staging_store_ref: str = "local-publication-staging"
    prompt_cache_ttl_seconds: int = 60
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
        "ytdlp_bin",
        "ffmpeg_bin",
        "ffprobe_bin",
        "youtube_data_api_key",
        "pipeline_scheduler_id",
        "transcript_worker_id",
        "transcript_cue_worker_id",
        "asr_worker_id",
        "micro_event_worker_id",
        "timeline_compose_worker_id",
        "workflow_coordinator_id",
        "pipeline_supervisor_id",
        "archive_publish_r2_endpoint",
        "archive_publish_r2_access_key",
        "archive_publish_r2_secret_key",
        "archive_publish_r2_bucket",
        "archive_publish_public_base_url",
        "archive_publish_dev_r2_endpoint",
        "archive_publish_dev_r2_access_key",
        "archive_publish_dev_r2_secret_key",
        "archive_publish_dev_r2_bucket",
        "archive_publish_dev_public_base_url",
        "archive_public_catalog_sync_url",
        "archive_public_catalog_sync_token",
        "publish_connections_file",
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
        "transcript_worker_poll_interval_seconds",
        "pipeline_scheduler_poll_interval_seconds",
        "pipeline_scheduler_channel_interval_seconds",
        "pipeline_scheduler_transcript_limit",
        "pipeline_scheduler_no_transcript_recheck_interval_seconds",
        "pipeline_scheduler_no_transcript_limit",
        "pipeline_scheduler_transcript_fallback_grace_seconds",
        "pipeline_scheduler_transcript_recheck_interval_seconds",
        "pipeline_scheduler_workflow_limit",
        "transcript_cue_generate_timeout_seconds",
        "transcript_cue_generate_concurrency_limit",
        "transcript_cue_worker_poll_interval_seconds",
        "asr_transcribe_timeout_seconds",
        "asr_transcribe_concurrency_limit",
        "asr_worker_poll_interval_seconds",
        "micro_event_extract_timeout_seconds",
        "micro_event_extract_concurrency_limit",
        "micro_event_window_concurrency_limit",
        "micro_event_worker_poll_interval_seconds",
        "timeline_compose_timeout_seconds",
        "timeline_compose_concurrency_limit",
        "timeline_compose_worker_poll_interval_seconds",
        "workflow_coordinator_poll_interval_seconds",
        "pipeline_supervisor_poll_interval_seconds",
        "llm_trace_retention_days",
        "archive_publish_timeout_seconds",
        "prompt_cache_ttl_seconds",
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

    @field_validator("archive_public_catalog_sync_timeout_seconds")
    @classmethod
    def _positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("value must be greater than 0")
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
