from __future__ import annotations

from .ports import CodexUsageListQuery, CodexUsageRepositoryPort
from .schemas import (
    CodexUsageByJobResponse,
    CodexUsageByVideoResponse,
    CodexUsageListResponse,
)


class ListCodexUsageUseCase:
    def __init__(self, repository: CodexUsageRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        source: str | None,
        status: str | None,
        model: str | None,
        reasoning_effort: str | None,
        video_id: int | None,
        video_task_id: int | None,
        job_id: int | None,
        limit: int,
        cursor: int | None,
    ) -> CodexUsageListResponse:
        result = await self._repository.list_usages(
            CodexUsageListQuery(
                source=source,
                status=status,
                model=model,
                reasoning_effort=reasoning_effort,
                video_id=video_id,
                video_task_id=video_task_id,
                job_id=job_id,
                limit=limit,
                cursor=cursor,
            )
        )
        return CodexUsageListResponse(
            items=[
                {
                    "codexUsageId": item.id,
                    "source": item.source,
                    "operation": item.operation,
                    "model": item.model,
                    "reasoningEffort": item.reasoning_effort,
                    "status": item.status,
                    "threadId": item.thread_id,
                    "turnId": item.turn_id,
                    "usageJson": item.usage_json,
                    "inputTokens": item.input_tokens,
                    "outputTokens": item.output_tokens,
                    "totalTokens": item.total_tokens,
                    "cachedInputTokens": item.cached_input_tokens,
                    "reasoningOutputTokens": item.reasoning_output_tokens,
                    "durationMs": item.duration_ms,
                    "errorType": item.error_type,
                    "errorMessage": item.error_message,
                    "videoId": item.video_id,
                    "videoTaskId": item.video_task_id,
                    "jobId": item.job_id,
                    "jobAttemptId": item.job_attempt_id,
                    "transcriptId": item.transcript_id,
                    "windowIndex": item.window_index,
                    "createdAt": item.created_at,
                }
                for item in result.items
            ],
            nextCursor=result.next_cursor,
            summary={
                "runCount": result.summary.run_count,
                "inputTokens": result.summary.input_tokens,
                "outputTokens": result.summary.output_tokens,
                "totalTokens": result.summary.total_tokens,
                "cachedInputTokens": result.summary.cached_input_tokens,
                "reasoningOutputTokens": result.summary.reasoning_output_tokens,
            },
        )

    async def execute_by_video(
        self,
        *,
        source: str | None,
        status: str | None,
        model: str | None,
        reasoning_effort: str | None,
        video_id: int | None,
        video_task_id: int | None,
        job_id: int | None,
        limit: int,
    ) -> CodexUsageByVideoResponse:
        items = await self._repository.list_usage_by_video(
            CodexUsageListQuery(
                source=source,
                status=status,
                model=model,
                reasoning_effort=reasoning_effort,
                video_id=video_id,
                video_task_id=video_task_id,
                job_id=job_id,
                limit=limit,
            )
        )
        return CodexUsageByVideoResponse(
            items=[
                {
                    "videoId": item.video_id,
                    "youtubeVideoId": item.youtube_video_id,
                    "title": item.title,
                    "latestModel": item.latest_model,
                    "latestReasoningEffort": item.latest_reasoning_effort,
                    "runCount": item.run_count,
                    "inputTokens": item.input_tokens,
                    "outputTokens": item.output_tokens,
                    "totalTokens": item.total_tokens,
                    "cachedInputTokens": item.cached_input_tokens,
                    "reasoningOutputTokens": item.reasoning_output_tokens,
                    "latestCreatedAt": item.latest_created_at,
                }
                for item in items
            ],
            summary={
                "runCount": sum(item.run_count for item in items),
                "inputTokens": sum(item.input_tokens for item in items),
                "outputTokens": sum(item.output_tokens for item in items),
                "totalTokens": sum(item.total_tokens for item in items),
                "cachedInputTokens": sum(item.cached_input_tokens for item in items),
                "reasoningOutputTokens": sum(
                    item.reasoning_output_tokens for item in items
                ),
            },
        )

    async def execute_by_job(
        self,
        *,
        source: str | None,
        status: str | None,
        model: str | None,
        reasoning_effort: str | None,
        video_id: int | None,
        video_task_id: int | None,
        job_id: int | None,
        limit: int,
    ) -> CodexUsageByJobResponse:
        items = await self._repository.list_usage_by_job(
            CodexUsageListQuery(
                source=source,
                status=status,
                model=model,
                reasoning_effort=reasoning_effort,
                video_id=video_id,
                video_task_id=video_task_id,
                job_id=job_id,
                limit=limit,
            )
        )
        return CodexUsageByJobResponse(
            items=[
                {
                    "jobId": item.job_id,
                    "jobStep": item.job_step,
                    "jobStatus": item.job_status,
                    "subjectType": item.subject_type,
                    "subjectId": item.subject_id,
                    "externalKey": item.external_key,
                    "latestModel": item.latest_model,
                    "latestReasoningEffort": item.latest_reasoning_effort,
                    "runCount": item.run_count,
                    "inputTokens": item.input_tokens,
                    "outputTokens": item.output_tokens,
                    "totalTokens": item.total_tokens,
                    "cachedInputTokens": item.cached_input_tokens,
                    "reasoningOutputTokens": item.reasoning_output_tokens,
                    "latestCreatedAt": item.latest_created_at,
                }
                for item in items
            ],
            summary={
                "runCount": sum(item.run_count for item in items),
                "inputTokens": sum(item.input_tokens for item in items),
                "outputTokens": sum(item.output_tokens for item in items),
                "totalTokens": sum(item.total_tokens for item in items),
                "cachedInputTokens": sum(item.cached_input_tokens for item in items),
                "reasoningOutputTokens": sum(
                    item.reasoning_output_tokens for item in items
                ),
            },
        )
