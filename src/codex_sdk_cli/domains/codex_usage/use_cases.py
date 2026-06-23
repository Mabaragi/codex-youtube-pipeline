from __future__ import annotations

from .ports import CodexUsageListQuery, CodexUsageRepositoryPort
from .schemas import CodexUsageListResponse


class ListCodexUsageUseCase:
    def __init__(self, repository: CodexUsageRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        source: str | None,
        status: str | None,
        model: str | None,
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
