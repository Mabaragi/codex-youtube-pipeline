from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy import Column, Table, UniqueConstraint

from codex_sdk_cli.domains.ops.ports import (
    OpsRepositoryPort,
    OpsVideoListQuery,
    OpsVideoTaskListQuery,
    OpsVideoTaskRecord,
)
from codex_sdk_cli.domains.ops.schemas import (
    OpsChannelListResponse,
    OpsChannelResponse,
    OpsRecentFailureResponse,
    OpsSchemaColumnResponse,
    OpsSchemaForeignKeyConstraintResponse,
    OpsSchemaGraphResponse,
    OpsSchemaIndexResponse,
    OpsSchemaRelationResponse,
    OpsSchemaTableResponse,
    OpsSchemaUniqueConstraintResponse,
    OpsStatusCountResponse,
    OpsSummaryCountsResponse,
    OpsSummaryResponse,
    OpsVideoDetailResponse,
    OpsVideoListResponse,
    OpsVideoResponse,
    OpsVideoTaskListResponse,
    OpsVideoTaskResponse,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptMetadataResponse,
    TranscriptStorageResponse,
)

from .exceptions import OpsVideoNotFound

SchemaRelationKind = Literal[
    "one_to_many",
    "one_to_one",
    "optional_one_to_many",
    "optional_one_to_one",
]


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
                    taskNoTranscriptCount=record.task_no_transcript_count,
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


class GetOpsVideoDetailUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, video_id: int) -> OpsVideoDetailResponse:
        record = await self._repository.get_video_detail(video_id)
        if record is None:
            raise OpsVideoNotFound("Video not found.")
        return OpsVideoDetailResponse(
            videoId=record.video_id,
            channelId=record.channel_id,
            channelName=record.channel_name,
            youtubeVideoId=record.youtube_video_id,
            title=record.title,
            description=record.description,
            publishedAt=record.published_at,
            duration=record.duration,
            thumbnailUrl=record.thumbnail_url,
            sourceListingApiCallId=record.source_listing_api_call_id,
            sourceDetailsApiCallId=record.source_details_api_call_id,
            sourceJobId=record.source_job_id,
            createdAt=record.created_at,
            updatedAt=record.updated_at,
            latestTaskId=record.latest_task_id,
            latestTaskName=record.latest_task_name,
            latestTaskStatus=record.latest_task_status,
            latestTaskUpdatedAt=record.latest_task_updated_at,
            transcriptId=record.transcript_id,
            tasks=[_video_task_response(task) for task in record.tasks],
            transcripts=[
                _transcript_metadata_response(transcript)
                for transcript in record.transcripts
            ],
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
            items=[_video_task_response(record) for record in result.items],
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
                            default=_column_default(column),
                            foreignKeys=sorted(
                                f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                                for foreign_key in column.foreign_keys
                            ),
                            constraintNames=_column_constraint_names(table, column),
                        )
                        for column in table.columns
                    ],
                    indexes=_table_indexes(table),
                    uniqueConstraints=_table_unique_constraints(table),
                    foreignKeyConstraints=_table_foreign_key_constraints(table),
                )
                for table in tables
            ],
            relations=[
                OpsSchemaRelationResponse(
                    id=(
                        f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                        f"->{table.name}.{column.name}"
                    ),
                    constraintName=_constraint_name(foreign_key.constraint),
                    sourceTable=foreign_key.column.table.name,
                    sourceColumn=foreign_key.column.name,
                    targetTable=table.name,
                    targetColumn=column.name,
                    sourceNullable=bool(column.nullable),
                    targetPrimaryKey=column.primary_key,
                    relationKind=_relation_kind(table, column),
                )
                for table in tables
                for column in table.columns
                for foreign_key in column.foreign_keys
            ],
        )


def _column_type(column: Column[Any]) -> str:
    return str(column.type).replace("DATETIME", "DateTime")


def _column_default(column: Column[Any]) -> str | None:
    if column.server_default is not None:
        return str(getattr(column.server_default, "arg", column.server_default))
    if column.default is not None:
        return str(getattr(column.default, "arg", column.default))
    return None


def _index_column_names(table: Table) -> set[str]:
    return {column.name for index in table.indexes for column in index.columns}


def _unique_column_names(table: Table) -> set[str]:
    return {
        column.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }


def _table_indexes(table: Table) -> list[OpsSchemaIndexResponse]:
    return [
        OpsSchemaIndexResponse(
            name=_constraint_name(index),
            columnNames=[column.name for column in index.columns],
            unique=index.unique,
        )
        for index in sorted(table.indexes, key=_constraint_name)
    ]


def _table_unique_constraints(table: Table) -> list[OpsSchemaUniqueConstraintResponse]:
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    return [
        OpsSchemaUniqueConstraintResponse(
            name=_constraint_name(constraint),
            columnNames=[column.name for column in constraint.columns],
        )
        for constraint in sorted(constraints, key=_constraint_name)
    ]


def _table_foreign_key_constraints(table: Table) -> list[OpsSchemaForeignKeyConstraintResponse]:
    return [
        OpsSchemaForeignKeyConstraintResponse(
            name=_constraint_name(constraint),
            columnNames=[element.parent.name for element in constraint.elements],
            targetTable=constraint.elements[0].column.table.name,
            targetColumnNames=[element.column.name for element in constraint.elements],
        )
        for constraint in sorted(table.foreign_key_constraints, key=_constraint_name)
        if constraint.elements
    ]


def _column_constraint_names(table: Table, column: Column[Any]) -> list[str]:
    names: set[str] = set()
    if column.primary_key:
        names.add(_constraint_name(table.primary_key))
    names.update(
        _constraint_name(constraint)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and column.name in constraint.columns
    )
    names.update(
        _constraint_name(constraint)
        for constraint in table.foreign_key_constraints
        if column.name in constraint.columns
    )
    names.update(
        _constraint_name(index)
        for index in table.indexes
        if column.name in index.columns
    )
    return sorted(names)


def _relation_kind(table: Table, column: Column[Any]) -> SchemaRelationKind:
    is_optional = bool(column.nullable)
    is_single_unique = _is_single_column_unique(table, column)
    if is_optional and is_single_unique:
        return "optional_one_to_one"
    if is_optional:
        return "optional_one_to_many"
    if is_single_unique:
        return "one_to_one"
    return "one_to_many"


def _is_single_column_unique(table: Table, column: Column[Any]) -> bool:
    if column.primary_key or column.unique:
        return True
    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint):
            continue
        constraint_column_names = [item.name for item in constraint.columns]
        if constraint_column_names == [column.name]:
            return True
    return any(
        index.unique and [item.name for item in index.columns] == [column.name]
        for index in table.indexes
    )


def _constraint_name(item: Any) -> str:
    return str(item.name or "unnamed")


def _video_task_response(record: OpsVideoTaskRecord) -> OpsVideoTaskResponse:
    return OpsVideoTaskResponse(
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
        outputJson=record.output_json,
        errorType=record.error_type,
        errorMessage=record.error_message,
        startedAt=record.started_at,
        completedAt=record.completed_at,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _transcript_metadata_response(
    record: YouTubeTranscriptMetadataRecord,
) -> TranscriptMetadataResponse:
    return TranscriptMetadataResponse(
        id=record.id,
        videoId=record.video_id,
        language=record.language,
        languageCode=record.language_code,
        isGenerated=record.is_generated,
        requestedLanguages=list(record.requested_languages),
        preserveFormatting=record.preserve_formatting,
        storage=TranscriptStorageResponse(
            bucket=record.storage_bucket,
            objectName=record.storage_object_name,
            uri=record.storage_uri,
        ),
        responseSha256=record.response_sha256,
        segmentCount=record.segment_count,
        textLength=record.text_length,
        notes=record.notes,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
