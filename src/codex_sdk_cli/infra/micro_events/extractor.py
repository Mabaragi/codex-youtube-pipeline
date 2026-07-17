from __future__ import annotations

from typing_extensions import override

from codex_sdk_cli.domains.codex.ports import (
    CodexRunCommand,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.micro_events.output_validation import micro_event_output_schema
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractorPort,
    MicroEventRepairRequest,
)
from codex_sdk_cli.settings import CodexModelChoice, ReasoningEffortChoice


class CodexMicroEventExtractor(MicroEventExtractorPort):
    def __init__(
        self,
        runtime: CodexRuntimePort,
        *,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
    ) -> None:
        self._runtime = runtime
        self._model = model
        self._reasoning_effort = reasoning_effort

    @override
    async def extract_window(
        self,
        request: MicroEventExtractionRequest,
    ) -> MicroEventExtractionResult:
        return await self._run_prompt(request, operation="extract_window")

    @override
    async def repair_window(
        self,
        request: MicroEventRepairRequest,
    ) -> MicroEventExtractionResult:
        return await self._run_prompt(request, operation="repair_window")

    async def _run_prompt(
        self,
        request: MicroEventExtractionRequest | MicroEventRepairRequest,
        *,
        operation: str,
    ) -> MicroEventExtractionResult:
        result = await self._runtime.run_prompt(
            CodexRunCommand(
                prompt=request.prompt,
                thread_id=None,
                cwd=None,
                model=request.model or self._model,
                reasoning_effort=request.reasoning_effort or self._reasoning_effort,
                sandbox="read-only",
                approval="deny-all",
                persist=False,
                base_instructions=" ",
                developer_instructions=" ",
                output_schema=micro_event_output_schema(),
                usage_context=CodexRunUsageContext(
                    source="micro_event_extract",
                    operation=operation,
                    video_id=request.video_id,
                    video_task_id=request.video_task_id,
                    job_id=request.job_id,
                    job_attempt_id=request.job_attempt_id,
                    transcript_id=request.transcript_id,
                    window_index=request.window_index,
                ),
            )
        )
        return MicroEventExtractionResult(
            thread_id=result.thread_id,
            turn_id=result.turn_id,
            status=result.status,
            final_response=result.final_response,
        )
