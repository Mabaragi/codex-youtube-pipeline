from __future__ import annotations

import asyncio

import pytest

from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.codex_usage.ports import CodexUsageCreate, CodexUsageRecorderPort
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime


class FakeRuntime(CodexRuntimePort):
    def __init__(self) -> None:
        self.fail = False
        self.usage: object = {
            "input_tokens": 20,
            "output_tokens": 13,
            "total_tokens": 33,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 1},
        }

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        if self.fail:
            raise RuntimeError("runtime failed")
        return CodexRunResult(
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            final_response="done",
            usage=self.usage,
        )

    async def login_with_device_code(self) -> CodexLoginResult:
        return CodexLoginResult(success=True)

    async def login_api_key(self, api_key: str) -> None:
        pass

    async def account(self, *, refresh_token: bool = False) -> object:
        return {}

    async def logout(self) -> None:
        pass


class FakeRecorder(CodexUsageRecorderPort):
    def __init__(self) -> None:
        self.usages: list[CodexUsageCreate] = []

    async def record_usage(self, usage: CodexUsageCreate) -> None:
        self.usages.append(usage)


def test_recording_codex_runtime_records_success_usage() -> None:
    recorder = FakeRecorder()
    runtime = RecordingCodexRuntime(FakeRuntime(), recorder)

    result = asyncio.run(runtime.run_prompt(_command()))

    assert result.final_response == "done"
    usage = recorder.usages[0]
    assert usage.source == "micro_event_extract"
    assert usage.operation == "extract_window"
    assert usage.video_task_id == 2
    assert usage.job_id == 3
    assert usage.window_index == 6
    assert usage.status == "succeeded"
    assert usage.model == "gpt-5.4"
    assert usage.reasoning_effort == "high"
    assert usage.thread_id == "thread-1"
    assert usage.turn_id == "turn-1"
    assert usage.input_tokens == 20
    assert usage.output_tokens == 13
    assert usage.total_tokens == 33
    assert usage.cached_input_tokens == 2
    assert usage.reasoning_output_tokens == 1
    assert usage.duration_ms >= 0


def test_recording_codex_runtime_extracts_nested_total_usage() -> None:
    recorder = FakeRecorder()
    wrapped = FakeRuntime()
    wrapped.usage = {
        "last": {
            "inputTokens": 1,
            "outputTokens": 2,
            "totalTokens": 3,
        },
        "total": {
            "inputTokens": 20,
            "outputTokens": 13,
            "totalTokens": 33,
            "cachedInputTokens": 2,
            "reasoningOutputTokens": 1,
        },
    }
    runtime = RecordingCodexRuntime(wrapped, recorder)

    asyncio.run(runtime.run_prompt(_command()))

    usage = recorder.usages[0]
    assert usage.input_tokens == 20
    assert usage.output_tokens == 13
    assert usage.total_tokens == 33
    assert usage.cached_input_tokens == 2
    assert usage.reasoning_output_tokens == 1


def test_recording_codex_runtime_records_failure_and_reraises() -> None:
    wrapped = FakeRuntime()
    wrapped.fail = True
    recorder = FakeRecorder()
    runtime = RecordingCodexRuntime(wrapped, recorder)

    with pytest.raises(RuntimeError, match="runtime failed"):
        asyncio.run(runtime.run_prompt(_command()))

    usage = recorder.usages[0]
    assert usage.status == "failed"
    assert usage.error_type == "RuntimeError"
    assert usage.error_message == "runtime failed"
    assert usage.total_tokens is None


def _command() -> CodexRunCommand:
    return CodexRunCommand(
        prompt="hello",
        thread_id=None,
        cwd=None,
        model="gpt-5.4",
        reasoning_effort="high",
        sandbox="read-only",
        approval="deny-all",
        persist=False,
        base_instructions=" ",
        developer_instructions=" ",
        usage_context=CodexRunUsageContext(
            source="micro_event_extract",
            operation="extract_window",
            video_id=1,
            video_task_id=2,
            job_id=3,
            job_attempt_id=4,
            transcript_id=5,
            window_index=6,
        ),
    )
