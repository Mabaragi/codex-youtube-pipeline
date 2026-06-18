from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Column, Table, UniqueConstraint

from codex_sdk_cli.domains.ops.ports import (
    OpsRepositoryPort,
    OpsVideoListQuery,
    OpsVideoTaskListQuery,
)
from codex_sdk_cli.domains.ops.schemas import (
    OpsChannelListResponse,
    OpsChannelResponse,
    OpsRecentFailureResponse,
    OpsSchemaColumnResponse,
    OpsSchemaGraphResponse,
    OpsSchemaRelationResponse,
    OpsSchemaTableResponse,
    OpsStatusCountResponse,
    OpsSummaryCountsResponse,
    OpsSummaryResponse,
    OpsVideoListResponse,
    OpsVideoResponse,
    OpsVideoTaskListResponse,
    OpsVideoTaskResponse,
)


class GetOpsSummaryUseCase:
    def __init__(
        self,
        repository: OpsRepositoryPort,
        s3_status_provider: Callable[[], dict[str, object]],
    ) -> None:
        self._repository = repository
        self._s3_status_provider = s3_status_provider

    async def execute(self) -> OpsSummaryResponse:
        counts = await self._repository.get_summary_counts()
        failures = await self._repository.list_recent_failures(limit=10)
        return OpsSummaryResponse(
            apiStatus="ok",
            s3=self._s3_status_provider(),
            counts=OpsSummaryCountsResponse(
                streamers=counts.streamers,
                channels=counts.channels,
                videos=counts.videos,
                transcripts=counts.transcripts,
                videoTasks=[
                    OpsStatusCountResponse(status=item.status, count=item.count)
                    for item in counts.video_tasks
                ],
                pipelineJobs=[
                    OpsStatusCountResponse(status=item.status, count=item.count)
                    for item in counts.pipeline_jobs
                ],
            ),
            recentFailures=[
                OpsRecentFailureResponse(
                    kind=item.kind,
                    id=item.id,
                    status=item.status,
                    label=item.label,
                    errorType=item.error_type,
                    errorMessage=item.error_message,
                    createdAt=item.created_at,
                    updatedAt=item.updated_at,
                )
                for item in failures
            ],
        )


class ListOpsChannelsUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> OpsChannelListResponse:
        records = await self._repository.list_channels()
        return OpsChannelListResponse(
            items=[
                OpsChannelResponse(
                    channelId=record.channel_id,
                    streamerId=record.streamer_id,
                    streamerName=record.streamer_name,
                    handle=record.handle,
                    name=record.name,
                    youtubeChannelId=record.youtube_channel_id,
                    uploadsPlaylistId=record.uploads_playlist_id,
                    videoCount=record.video_count,
                    transcriptSucceededCount=record.transcript_succeeded_count,
                    taskFailedCount=record.task_failed_count,
                    taskRunningCount=record.task_running_count,
                    latestVideoPublishedAt=record.latest_video_published_at,
                    latestTaskUpdatedAt=record.latest_task_updated_at,
                )
                for record in records
            ]
        )


class ListOpsVideosUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        channel_id: int | None,
        task_status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> OpsVideoListResponse:
        result = await self._repository.list_videos(
            OpsVideoListQuery(
                channel_id=channel_id,
                task_status=task_status,
                search=search,
                limit=limit,
                offset=offset,
            )
        )
        return OpsVideoListResponse(
            items=[
                OpsVideoResponse(
                    videoId=record.video_id,
                    channelId=record.channel_id,
                    channelName=record.channel_name,
                    youtubeVideoId=record.youtube_video_id,
                    title=record.title,
                    publishedAt=record.published_at,
                    duration=record.duration,
                    thumbnailUrl=record.thumbnail_url,
                    latestTaskId=record.latest_task_id,
                    latestTaskName=record.latest_task_name,
                    latestTaskStatus=record.latest_task_status,
                    latestTaskUpdatedAt=record.latest_task_updated_at,
                    transcriptId=record.transcript_id,
                )
                for record in result.items
            ],
            total=result.total,
            limit=limit,
            offset=offset,
        )


class ListOpsVideoTasksUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        channel_id: int | None,
        task_name: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> OpsVideoTaskListResponse:
        result = await self._repository.list_video_tasks(
            OpsVideoTaskListQuery(
                channel_id=channel_id,
                task_name=task_name,
                status=status,
                limit=limit,
                offset=offset,
            )
        )
        return OpsVideoTaskListResponse(
            items=[
                OpsVideoTaskResponse(
                    videoTaskId=record.video_task_id,
                    videoId=record.video_id,
                    channelId=record.channel_id,
                    channelName=record.channel_name,
                    youtubeVideoId=record.youtube_video_id,
                    taskName=record.task_name,
                    taskVersion=record.task_version,
                    status=record.status,
                    workerId=record.worker_id,
                    timeoutSeconds=record.timeout_seconds,
                    jobId=record.job_id,
                    jobAttemptId=record.job_attempt_id,
                    outputTranscriptId=record.output_transcript_id,
                    errorType=record.error_type,
                    errorMessage=record.error_message,
                    startedAt=record.started_at,
                    completedAt=record.completed_at,
                    createdAt=record.created_at,
                    updatedAt=record.updated_at,
                )
                for record in result.items
            ],
            total=result.total,
            limit=limit,
            offset=offset,
        )


class GetOpsSchemaGraphUseCase:
    def execute(self) -> OpsSchemaGraphResponse:
        import codex_sdk_cli.infra.database.models  # noqa: F401
        from codex_sdk_cli.infra.database.base import Base

        tables = list(Base.metadata.sorted_tables)
        return OpsSchemaGraphResponse(
            tables=[
                OpsSchemaTableResponse(
                    id=table.name,
                    name=table.name,
                    columns=[
                        OpsSchemaColumnResponse(
                            id=f"{table.name}.{column.name}",
                            name=column.name,
                            type=_column_type(column),
                            nullable=bool(column.nullable),
                            primaryKey=column.primary_key,
                            unique=column.unique or column.name in _unique_column_names(table),
                            index=column.index or column.name in _index_column_names(table),
                            foreignKeys=sorted(
                                f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                                for foreign_key in column.foreign_keys
                            ),
                        )
                        for column in table.columns
                    ],
                )
                for table in tables
            ],
            relations=[
                OpsSchemaRelationResponse(
                    id=(
                        f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                        f"->{table.name}.{column.name}"
                    ),
                    sourceTable=foreign_key.column.table.name,
                    sourceColumn=foreign_key.column.name,
                    targetTable=table.name,
                    targetColumn=column.name,
                )
                for table in tables
                for column in table.columns
                for foreign_key in column.foreign_keys
            ],
        )


def _column_type(column: Column[Any]) -> str:
    return str(column.type).replace("DATETIME", "DateTime")


def _index_column_names(table: Table) -> set[str]:
    return {column.name for index in table.indexes for column in index.columns}


def _unique_column_names(table: Table) -> set[str]:
    return {
        column.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }
