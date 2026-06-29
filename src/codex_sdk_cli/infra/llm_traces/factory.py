from __future__ import annotations

from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.infra.llm_traces.writer import FileLlmTraceRecorder
from codex_sdk_cli.settings import CliSettings


def create_llm_trace_recorder(settings: CliSettings) -> LlmTraceRecorderPort:
    if not settings.llm_trace_enabled:
        return NoopLlmTraceRecorder()
    return FileLlmTraceRecorder(
        base_dir=settings.llm_trace_dir,
        raw_response_enabled=settings.llm_trace_raw_response_enabled,
        retention_days=settings.llm_trace_retention_days,
    )
