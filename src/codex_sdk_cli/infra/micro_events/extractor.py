from __future__ import annotations

from typing_extensions import override

from codex_sdk_cli.domains.codex.ports import (
    CodexRunCommand,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractorPort,
)


class CodexMicroEventExtractor(MicroEventExtractorPort):
    def __init__(
        self,
        runtime: CodexRuntimePort,
        *,
        model: str | None,
    ) -> None:
        self._runtime = runtime
        self._model = model

    @override
    async def extract_window(
        self,
        request: MicroEventExtractionRequest,
    ) -> MicroEventExtractionResult:
        result = await self._runtime.run_prompt(
            CodexRunCommand(
                prompt=request.prompt,
                thread_id=None,
                cwd=None,
                model=self._model,
                sandbox="read-only",
                approval="deny-all",
                persist=False,
                base_instructions=" ",
                developer_instructions=" ",
                usage_context=CodexRunUsageContext(
                    source="micro_event_extract",
                    operation="extract_window",
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
