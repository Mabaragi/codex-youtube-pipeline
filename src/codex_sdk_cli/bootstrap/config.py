from __future__ import annotations

from dataclasses import dataclass

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.settings import CliSettings


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str
    echo: bool


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    task_type: str
    timeout_seconds: int
    concurrency_limit: int
    poll_interval_seconds: int
    worker_id: str | None


@dataclass(frozen=True, slots=True)
class CodexTaskConfig:
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    prompt_cache_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    enabled: bool
    poll_interval_seconds: int
    channel_interval_seconds: int
    transcript_limit: int
    no_transcript_recheck_interval_seconds: int
    no_transcript_limit: int
    scheduler_id: str | None


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    database: DatabaseConfig
    codex: CodexTaskConfig
    scheduler: SchedulerConfig
    transcript: WorkerConfig
    transcript_cue: WorkerConfig
    micro_event: WorkerConfig
    timeline: WorkerConfig


def application_config(settings: CliSettings) -> ApplicationConfig:
    return ApplicationConfig(
        database=DatabaseConfig(
            url=settings.database_url,
            echo=settings.database_echo,
        ),
        codex=CodexTaskConfig(
            model=settings.model,
            reasoning_effort=settings.reasoning_effort,
            prompt_cache_ttl_seconds=settings.prompt_cache_ttl_seconds,
        ),
        scheduler=SchedulerConfig(
            enabled=settings.pipeline_scheduler_enabled,
            poll_interval_seconds=settings.pipeline_scheduler_poll_interval_seconds,
            channel_interval_seconds=settings.pipeline_scheduler_channel_interval_seconds,
            transcript_limit=settings.pipeline_scheduler_transcript_limit,
            no_transcript_recheck_interval_seconds=(
                settings.pipeline_scheduler_no_transcript_recheck_interval_seconds
            ),
            no_transcript_limit=settings.pipeline_scheduler_no_transcript_limit,
            scheduler_id=settings.pipeline_scheduler_id,
        ),
        transcript=WorkerConfig(
            task_type="transcript_collect",
            timeout_seconds=settings.transcript_collect_timeout_seconds,
            concurrency_limit=settings.transcript_collect_concurrency_limit,
            poll_interval_seconds=settings.pipeline_scheduler_poll_interval_seconds,
            worker_id=settings.pipeline_scheduler_id,
        ),
        transcript_cue=WorkerConfig(
            task_type="transcript_cue_generate",
            timeout_seconds=settings.transcript_cue_generate_timeout_seconds,
            concurrency_limit=settings.transcript_cue_generate_concurrency_limit,
            poll_interval_seconds=settings.pipeline_scheduler_poll_interval_seconds,
            worker_id=settings.pipeline_scheduler_id,
        ),
        micro_event=WorkerConfig(
            task_type="micro_event_extract",
            timeout_seconds=settings.micro_event_extract_timeout_seconds,
            concurrency_limit=settings.micro_event_extract_concurrency_limit,
            poll_interval_seconds=settings.micro_event_worker_poll_interval_seconds,
            worker_id=settings.micro_event_worker_id,
        ),
        timeline=WorkerConfig(
            task_type="timeline_compose",
            timeout_seconds=settings.timeline_compose_timeout_seconds,
            concurrency_limit=settings.timeline_compose_concurrency_limit,
            poll_interval_seconds=settings.timeline_compose_worker_poll_interval_seconds,
            worker_id=settings.timeline_compose_worker_id,
        ),
    )

