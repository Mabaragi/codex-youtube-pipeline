from __future__ import annotations

import asyncio

from typing_extensions import override

from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
)
from codex_sdk_cli.domains.micro_events.ports import MicroEventRepairRequest
from codex_sdk_cli.infra.micro_events.extractor import CodexMicroEventExtractor


class FakeCodexRuntime(CodexRuntimePort):
    def __init__(self) -> None:
        self.commands: list[CodexRunCommand] = []

    @override
    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        self.commands.append(command)
        return CodexRunResult(
            thread_id="thread-repair",
            turn_id="turn-repair",
            status="completed",
            final_response='{"events":[],"excluded_ranges":[],"asr_correction_candidates":[]}',
            usage=None,
        )

    @override
    async def login_with_device_code(self) -> CodexLoginResult:
        return CodexLoginResult(success=True, error=None)

    @override
    async def login_api_key(self, api_key: str) -> None:
        _ = api_key

    @override
    async def account(self, *, refresh_token: bool = False) -> object:
        return {"refreshToken": refresh_token}

    @override
    async def logout(self) -> None:
        return None


def test_micro_event_repair_window_records_repair_operation_context() -> None:
    runtime = FakeCodexRuntime()
    extractor = CodexMicroEventExtractor(
        runtime,
        model="gpt-5.4",
        reasoning_effort="high",
    )

    result = asyncio.run(
        extractor.repair_window(
            MicroEventRepairRequest(
                prompt="repair prompt",
                original_prompt="original prompt",
                original_response="original response",
                validation_error="Extractor left a gap in OWNED_RANGE coverage.",
                owned_start_cue_id="tr1-c000001",
                owned_end_cue_id="tr1-c000002",
                owned_cue_ids=["tr1-c000001", "tr1-c000002"],
                video_id=1,
                video_task_id=2,
                job_id=3,
                job_attempt_id=4,
                transcript_id=5,
                window_index=6,
                model="gpt-5.4-mini",
                reasoning_effort="medium",
            )
        )
    )

    assert result.thread_id == "thread-repair"
    command = runtime.commands[0]
    assert command.prompt == "repair prompt"
    assert command.model == "gpt-5.4-mini"
    assert command.reasoning_effort == "medium"
    assert command.usage_context is not None
    assert command.usage_context.source == "micro_event_extract"
    assert command.usage_context.operation == "repair_window"
    assert command.usage_context.video_id == 1
    assert command.usage_context.video_task_id == 2
    assert command.usage_context.job_id == 3
    assert command.usage_context.job_attempt_id == 4
    assert command.usage_context.transcript_id == 5
    assert command.usage_context.window_index == 6
