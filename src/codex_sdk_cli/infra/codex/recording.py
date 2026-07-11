from __future__ import annotations

from time import perf_counter

from typing_extensions import override

from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.codex_usage.normalization import (
    extract_usage_tokens,
    usage_to_json,
)
from codex_sdk_cli.domains.codex_usage.ports import (
    CodexUsageCreate,
    CodexUsageRecorderPort,
)


class RecordingCodexRuntime(CodexRuntimePort):
    def __init__(
        self,
        wrapped: CodexRuntimePort,
        recorder: CodexUsageRecorderPort,
    ) -> None:
        self._wrapped = wrapped
        self._recorder = recorder

    @override
    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        started = perf_counter()
        try:
            result = await self._wrapped.run_prompt(command)
        except Exception as exc:
            await self._recorder.record_usage(
                _usage_create(
                    command=command,
                    duration_ms=_duration_ms(started),
                    status="failed",
                    thread_id=None,
                    turn_id=None,
                    usage=None,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            raise
        await self._recorder.record_usage(
            _usage_create(
                command=command,
                duration_ms=_duration_ms(started),
                status="succeeded",
                thread_id=result.thread_id,
                turn_id=result.turn_id,
                usage=result.usage,
                error_type=None,
                error_message=None,
            )
        )
        return result

    @override
    async def login_with_device_code(self) -> CodexLoginResult:
        return await self._wrapped.login_with_device_code()

    @override
    async def login_api_key(self, api_key: str) -> None:
        await self._wrapped.login_api_key(api_key)

    @override
    async def account(self, *, refresh_token: bool = False) -> object:
        return await self._wrapped.account(refresh_token=refresh_token)

    @override
    async def logout(self) -> None:
        await self._wrapped.logout()


def _usage_create(
    *,
    command: CodexRunCommand,
    duration_ms: int,
    status: str,
    thread_id: str | None,
    turn_id: str | None,
    usage: object | None,
    error_type: str | None,
    error_message: str | None,
) -> CodexUsageCreate:
    usage_json = usage_to_json(usage)
    (
        input_tokens,
        output_tokens,
        total_tokens,
        cached_input_tokens,
        reasoning_output_tokens,
    ) = extract_usage_tokens(usage_json)
    context = command.usage_context or CodexRunUsageContext(
        source="codex_runtime",
        operation="run_prompt",
    )
    return CodexUsageCreate(
        source=context.source,
        operation=context.operation,
        model=command.model,
        reasoning_effort=command.reasoning_effort,
        status="failed" if status == "failed" else "succeeded",
        thread_id=thread_id,
        turn_id=turn_id,
        usage_json=usage_json,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        duration_ms=duration_ms,
        error_type=error_type,
        error_message=error_message,
        video_id=context.video_id,
        video_task_id=context.video_task_id,
        job_id=context.job_id,
        job_attempt_id=context.job_attempt_id,
        work_item_id=context.work_item_id,
        work_attempt_id=context.work_attempt_id,
        transcript_id=context.transcript_id,
        window_index=context.window_index,
    )


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
