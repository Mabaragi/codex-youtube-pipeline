from __future__ import annotations

from collections.abc import Callable

from codex_sdk_cli.domains.ops.ports import (
    OpsRepositoryPort,
    OpsSchemaColumnRecord,
    OpsSchemaForeignKeyConstraintRecord,
    OpsSchemaGraphRecord,
    OpsSchemaIndexRecord,
    OpsSchemaRelationRecord,
    OpsSchemaTableRecord,
    OpsSchemaUniqueConstraintRecord,
    OpsVideoGenerationRecord,
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
    OpsVideoCueGenerationResponse,
    OpsVideoDetailResponse,
    OpsVideoGenerationResponse,
    OpsVideoListResponse,
    OpsVideoMicroEventGenerationResponse,
    OpsVideoResponse,
    OpsVideoTaskListResponse,
    OpsVideoTaskResponse,
    OpsVideoTimelineGenerationResponse,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptMetadataResponse,
    TranscriptStorageResponse,
)

from .exceptions import OpsVideoNotFound


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
                    generation=_video_generation_response(record.generation),
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
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> OpsSchemaGraphResponse:
        return _schema_graph_response(await self._repository.get_schema_graph())


def _schema_graph_response(record: OpsSchemaGraphRecord) -> OpsSchemaGraphResponse:
    return OpsSchemaGraphResponse(
        tables=[_schema_table_response(table) for table in record.tables],
        relations=[_schema_relation_response(relation) for relation in record.relations],
    )


def _schema_table_response(record: OpsSchemaTableRecord) -> OpsSchemaTableResponse:
    return OpsSchemaTableResponse(
        id=record.id,
        name=record.name,
        columns=[_schema_column_response(column) for column in record.columns],
        indexes=[_schema_index_response(index) for index in record.indexes],
        uniqueConstraints=[
            _schema_unique_constraint_response(constraint)
            for constraint in record.unique_constraints
        ],
        foreignKeyConstraints=[
            _schema_foreign_key_constraint_response(constraint)
            for constraint in record.foreign_key_constraints
        ],
    )


def _schema_column_response(record: OpsSchemaColumnRecord) -> OpsSchemaColumnResponse:
    return OpsSchemaColumnResponse(
        id=record.id,
        name=record.name,
        type=record.type,
        nullable=record.nullable,
        primaryKey=record.primary_key,
        unique=record.unique,
        index=record.index,
        default=record.default,
        foreignKeys=list(record.foreign_keys),
        constraintNames=list(record.constraint_names),
    )


def _schema_index_response(record: OpsSchemaIndexRecord) -> OpsSchemaIndexResponse:
    return OpsSchemaIndexResponse(
        name=record.name,
        columnNames=list(record.column_names),
        unique=record.unique,
    )


def _schema_unique_constraint_response(
    record: OpsSchemaUniqueConstraintRecord,
) -> OpsSchemaUniqueConstraintResponse:
    return OpsSchemaUniqueConstraintResponse(
        name=record.name,
        columnNames=list(record.column_names),
    )


def _schema_foreign_key_constraint_response(
    record: OpsSchemaForeignKeyConstraintRecord,
) -> OpsSchemaForeignKeyConstraintResponse:
    return OpsSchemaForeignKeyConstraintResponse(
        name=record.name,
        columnNames=list(record.column_names),
        targetTable=record.target_table,
        targetColumnNames=list(record.target_column_names),
    )


def _schema_relation_response(record: OpsSchemaRelationRecord) -> OpsSchemaRelationResponse:
    return OpsSchemaRelationResponse(
        id=record.id,
        constraintName=record.constraint_name,
        sourceTable=record.source_table,
        sourceColumn=record.source_column,
        targetTable=record.target_table,
        targetColumn=record.target_column,
        sourceNullable=record.source_nullable,
        targetPrimaryKey=record.target_primary_key,
        relationKind=record.relation_kind,
    )


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


def _video_generation_response(
    record: OpsVideoGenerationRecord,
) -> OpsVideoGenerationResponse:
    return OpsVideoGenerationResponse(
        cues=OpsVideoCueGenerationResponse(
            generated=record.cues.generated,
            transcriptId=record.cues.transcript_id,
            cueCount=record.cues.cue_count,
            latestTaskId=record.cues.latest_task_id,
            latestTaskStatus=record.cues.latest_task_status,
            latestTaskUpdatedAt=record.cues.latest_task_updated_at,
        ),
        microEvents=OpsVideoMicroEventGenerationResponse(
            generated=record.micro_events.generated,
            videoTaskId=record.micro_events.video_task_id,
            windowCount=record.micro_events.window_count,
            microEventCount=record.micro_events.micro_event_count,
            latestTaskId=record.micro_events.latest_task_id,
            latestTaskStatus=record.micro_events.latest_task_status,
            latestTaskUpdatedAt=record.micro_events.latest_task_updated_at,
        ),
        timeline=OpsVideoTimelineGenerationResponse(
            generated=record.timeline.generated,
            compositionId=record.timeline.composition_id,
            videoTaskId=record.timeline.video_task_id,
            episodeCount=record.timeline.episode_count,
            latestTaskId=record.timeline.latest_task_id,
            latestTaskStatus=record.timeline.latest_task_status,
            latestTaskUpdatedAt=record.timeline.latest_task_updated_at,
        ),
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
