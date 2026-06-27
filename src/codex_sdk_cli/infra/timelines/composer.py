from __future__ import annotations

from typing_extensions import override

from codex_sdk_cli.domains.codex.ports import (
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.timelines.ports import (
    TimelineComposeRequest,
    TimelineComposeResult,
    TimelineComposerPort,
    TimelineEpisodeRepairRequest,
    TimelineEpisodeRepairResult,
)
from codex_sdk_cli.settings import CodexModelChoice, ReasoningEffortChoice


class CodexTimelineComposer(TimelineComposerPort):
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
    async def compose(self, request: TimelineComposeRequest) -> TimelineComposeResult:
        result = await self._run_prompt(
            prompt=request.prompt,
            operation="compose_video",
            video_id=request.video_id,
            video_task_id=request.video_task_id,
            job_id=request.job_id,
            job_attempt_id=request.job_attempt_id,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
        )
        return TimelineComposeResult(
            thread_id=result.thread_id,
            turn_id=result.turn_id,
            status=result.status,
            final_response=result.final_response,
        )

    @override
    async def repair_episode(
        self,
        request: TimelineEpisodeRepairRequest,
    ) -> TimelineEpisodeRepairResult:
        result = await self._run_prompt(
            prompt=request.prompt,
            operation="repair_episode",
            video_id=request.video_id,
            video_task_id=request.video_task_id,
            job_id=request.job_id,
            job_attempt_id=request.job_attempt_id,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
        )
        return TimelineEpisodeRepairResult(
            thread_id=result.thread_id,
            turn_id=result.turn_id,
            status=result.status,
            final_response=result.final_response,
        )

    async def _run_prompt(
        self,
        *,
        prompt: str,
        operation: str,
        video_id: int,
        video_task_id: int,
        job_id: int,
        job_attempt_id: int,
        model: CodexModelChoice | None,
        reasoning_effort: ReasoningEffortChoice | None,
    ) -> CodexRunResult:
        result = await self._runtime.run_prompt(
            CodexRunCommand(
                prompt=prompt,
                thread_id=None,
                cwd=None,
                model=model or self._model,
                reasoning_effort=reasoning_effort or self._reasoning_effort,
                sandbox="read-only",
                approval="deny-all",
                persist=False,
                base_instructions=" ",
                developer_instructions=" ",
                usage_context=CodexRunUsageContext(
                    source="timeline_compose",
                    operation=operation,
                    video_id=video_id,
                    video_task_id=video_task_id,
                    job_id=job_id,
                    job_attempt_id=job_attempt_id,
                    transcript_id=None,
                    window_index=None,
                ),
            )
        )
        return result
