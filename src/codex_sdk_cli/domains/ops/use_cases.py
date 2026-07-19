from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.ops.ports import (
    OpsCandidateCategory,
    OpsCandidateListQuery,
    OpsEmbedStatusFilter,
    OpsLatestEventRecord,
    OpsMicroEventReadyCandidateListResult,
    OpsMicroEventReadyCandidateRecord,
    OpsPendingWorkCancelerPort,
    OpsRepositoryPort,
    OpsSchemaColumnRecord,
    OpsSchemaForeignKeyConstraintRecord,
    OpsSchemaGraphRecord,
    OpsSchemaIndexRecord,
    OpsSchemaRelationRecord,
    OpsSchemaTableRecord,
    OpsSchemaUniqueConstraintRecord,
    OpsStuckTaskListResult,
    OpsStuckTaskQuery,
    OpsStuckTaskRecord,
    OpsTaskSummaryRecord,
    OpsTimelineReadyCandidateListResult,
    OpsTimelineReadyCandidateRecord,
    OpsVideoGenerationRecord,
    OpsVideoListQuery,
    OpsVideoTaskListQuery,
    OpsVideoTaskRecord,
)
from codex_sdk_cli.domains.ops.schemas import (
    OpsCandidateRecommendedEnqueueResponse,
    OpsChannelListResponse,
    OpsChannelResponse,
    OpsLatestEventResponse,
    OpsMicroEventReadyCandidateListResponse,
    OpsMicroEventReadyCandidateResponse,
    OpsRecentFailureResponse,
    OpsRefreshVideoEmbedStatusItemResponse,
    OpsRefreshVideoEmbedStatusRequest,
    OpsRefreshVideoEmbedStatusResponse,
    OpsSchemaColumnResponse,
    OpsSchemaForeignKeyConstraintResponse,
    OpsSchemaGraphResponse,
    OpsSchemaIndexResponse,
    OpsSchemaRelationResponse,
    OpsSchemaTableResponse,
    OpsSchemaUniqueConstraintResponse,
    OpsStatusCountResponse,
    OpsStuckTaskListResponse,
    OpsStuckTaskResponse,
    OpsSummaryCountsResponse,
    OpsSummaryResponse,
    OpsTaskSummaryResponse,
    OpsTimelineReadyCandidateListResponse,
    OpsTimelineReadyCandidateResponse,
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
from codex_sdk_cli.domains.video_availability.use_cases import (
    VerifyVideoAvailabilityUseCase,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.ports import YouTubeDataClientPort
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
        embed_status: OpsEmbedStatusFilter | None,
        limit: int,
        offset: int,
    ) -> OpsVideoListResponse:
        result = await self._repository.list_videos(
            OpsVideoListQuery(
                channel_id=channel_id,
                task_status=task_status,
                search=search,
                embed_status=embed_status,
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
                    isEmbeddable=record.is_embeddable,
                    embedStatusCheckedAt=record.embed_status_checked_at,
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


class RefreshOpsVideoEmbedStatusUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pending_work: OpsPendingWorkCancelerPort,
        youtube_data: YouTubeDataClientPort,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._verifier = VerifyVideoAvailabilityUseCase(
            videos=videos,
            video_tasks=video_tasks,
            pending_work=pending_work,
            youtube_data=youtube_data,
            events=events,
        )

    async def execute(
        self,
        request: OpsRefreshVideoEmbedStatusRequest,
    ) -> OpsRefreshVideoEmbedStatusResponse:
        records = await self._videos.list_videos_for_embed_status_refresh(
            video_ids=tuple(request.video_ids) if request.video_ids is not None else None,
            limit=request.limit,
        )
        items: list[OpsRefreshVideoEmbedStatusItemResponse] = []
        for batch in _chunks(records, 50):
            items.extend(await self._refresh_batch(batch))
        return OpsRefreshVideoEmbedStatusResponse(
            scannedCount=len(records),
            updatedCount=sum(1 for item in items if item.status == "updated"),
            failedCount=sum(1 for item in items if item.status == "failed"),
            items=items,
        )

    async def _refresh_batch(
        self,
        videos: list[VideoRecord],
    ) -> list[OpsRefreshVideoEmbedStatusItemResponse]:
        original_by_youtube_id = {video.youtube_video_id: video for video in videos}
        results = await self._verifier.execute(
            tuple(video.youtube_video_id for video in videos),
            actor_type="manual_api",
            source="ops.videos.embed_status",
        )
        return [
            OpsRefreshVideoEmbedStatusItemResponse(
                videoId=(
                    result.video_id
                    if result.video_id is not None
                    else original_by_youtube_id[result.youtube_video_id].id
                ),
                youtubeVideoId=result.youtube_video_id,
                status="failed" if result.outcome == "retry" else "updated",
                isEmbeddable=(
                    original_by_youtube_id[result.youtube_video_id].is_embeddable
                    if result.outcome == "retry"
                    else result.is_embeddable
                ),
                sourceApiCallId=result.source_api_call_id,
                canceledPendingTaskCount=result.canceled_pending_task_count,
                errorType=result.error_type,
                errorMessage=result.error_message,
            )
            for result in results
        ]


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
            isEmbeddable=record.is_embeddable,
            embedStatusCheckedAt=record.embed_status_checked_at,
            thumbnailUrl=record.thumbnail_url,
            sourceListingApiCallId=record.source_listing_api_call_id,
            sourceDetailsApiCallId=record.source_details_api_call_id,
            sourceEmbedStatusApiCallId=record.source_embed_status_api_call_id,
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


class ListOpsMicroEventReadyCandidatesUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        channel_id: int | None,
        search: str | None,
        category: OpsCandidateCategory | None,
        limit: int,
        offset: int,
    ) -> OpsMicroEventReadyCandidateListResponse:
        result = await self._repository.list_micro_event_ready_candidates(
            OpsCandidateListQuery(
                channel_id=channel_id,
                search=search,
                category=category,
                limit=limit,
                offset=offset,
            )
        )
        return _micro_event_candidates_response(result, limit=limit, offset=offset)


class ListOpsTimelineReadyCandidatesUseCase:
    def __init__(self, repository: OpsRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        channel_id: int | None,
        search: str | None,
        category: OpsCandidateCategory | None,
        limit: int,
        offset: int,
    ) -> OpsTimelineReadyCandidateListResponse:
        result = await self._repository.list_timeline_ready_candidates(
            OpsCandidateListQuery(
                channel_id=channel_id,
                search=search,
                category=category,
                limit=limit,
                offset=offset,
            )
        )
        return _timeline_candidates_response(result, limit=limit, offset=offset)


class DetectOpsStuckTasksUseCase:
    def __init__(
        self,
        repository: OpsRepositoryPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, task_name: str, minutes: int) -> OpsStuckTaskListResponse:
        now = _utc(self._clock())
        result = await self._repository.detect_stuck_tasks(
            OpsStuckTaskQuery(
                task_name=task_name,
                older_than=now - timedelta(minutes=minutes),
            )
        )
        return _stuck_tasks_response(
            result,
            task_name=task_name,
            minutes=minutes,
            now=now,
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


def _micro_event_candidates_response(
    result: OpsMicroEventReadyCandidateListResult,
    *,
    limit: int,
    offset: int,
) -> OpsMicroEventReadyCandidateListResponse:
    return OpsMicroEventReadyCandidateListResponse(
        items=[_micro_event_candidate_response(item) for item in result.items],
        total=result.total,
        limit=limit,
        offset=offset,
    )


def _micro_event_candidate_response(
    record: OpsMicroEventReadyCandidateRecord,
) -> OpsMicroEventReadyCandidateResponse:
    return OpsMicroEventReadyCandidateResponse(
        videoId=record.video_id,
        channelId=record.channel_id,
        channelName=record.channel_name,
        youtubeVideoId=record.youtube_video_id,
        title=record.title,
        publishedAt=record.published_at,
        transcriptId=record.transcript_id,
        cueCount=record.cue_count,
        latestCueTask=(
            _task_summary_response(record.latest_cue_task)
            if record.latest_cue_task is not None
            else None
        ),
        latestMicroTask=(
            _task_summary_response(record.latest_micro_task)
            if record.latest_micro_task is not None
            else None
        ),
        category=record.category,
        recommendedEnqueue=OpsCandidateRecommendedEnqueueResponse(
            videoIds=[record.video_id],
            retryFailed=record.recommended_retry_failed,
        ),
    )


def _timeline_candidates_response(
    result: OpsTimelineReadyCandidateListResult,
    *,
    limit: int,
    offset: int,
) -> OpsTimelineReadyCandidateListResponse:
    return OpsTimelineReadyCandidateListResponse(
        items=[_timeline_candidate_response(item) for item in result.items],
        total=result.total,
        limit=limit,
        offset=offset,
    )


def _timeline_candidate_response(
    record: OpsTimelineReadyCandidateRecord,
) -> OpsTimelineReadyCandidateResponse:
    return OpsTimelineReadyCandidateResponse(
        videoId=record.video_id,
        channelId=record.channel_id,
        channelName=record.channel_name,
        youtubeVideoId=record.youtube_video_id,
        title=record.title,
        publishedAt=record.published_at,
        sourceMicroEventTaskId=record.source_micro_event_task_id,
        microEventCount=record.micro_event_count,
        windowCount=record.window_count,
        latestTimelineTask=(
            _task_summary_response(record.latest_timeline_task)
            if record.latest_timeline_task is not None
            else None
        ),
        category=record.category,
        recommendedEnqueue=OpsCandidateRecommendedEnqueueResponse(
            videoIds=[record.video_id],
            retryFailed=record.recommended_retry_failed,
        ),
    )


def _chunks(items: list[VideoRecord], size: int) -> list[list[VideoRecord]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _task_summary_response(record: OpsTaskSummaryRecord) -> OpsTaskSummaryResponse:
    return OpsTaskSummaryResponse(
        videoTaskId=record.video_task_id,
        status=record.status,
        workerId=record.worker_id,
        jobId=record.job_id,
        jobAttemptId=record.job_attempt_id,
        errorType=record.error_type,
        errorMessage=record.error_message,
        updatedAt=record.updated_at,
    )


def _stuck_tasks_response(
    result: OpsStuckTaskListResult,
    *,
    task_name: str,
    minutes: int,
    now: datetime,
) -> OpsStuckTaskListResponse:
    return OpsStuckTaskListResponse(
        items=[_stuck_task_response(item, now=now) for item in result.items],
        total=result.total,
        taskName=task_name,
        minutes=minutes,
    )


def _stuck_task_response(
    record: OpsStuckTaskRecord,
    *,
    now: datetime,
) -> OpsStuckTaskResponse:
    stale_age = max(0, int((now - _utc(record.stale_since)).total_seconds()))
    return OpsStuckTaskResponse(
        videoTaskId=record.video_task_id,
        videoId=record.video_id,
        channelId=record.channel_id,
        channelName=record.channel_name,
        youtubeVideoId=record.youtube_video_id,
        title=record.title,
        taskName=record.task_name,
        status=record.status,
        workerId=record.worker_id,
        workerPid=record.worker_pid,
        jobId=record.job_id,
        jobAttemptId=record.job_attempt_id,
        jobAttemptStatus=record.job_attempt_status,
        startedAt=record.started_at,
        updatedAt=record.updated_at,
        staleSince=record.stale_since,
        staleAgeSeconds=stale_age,
        latestEvent=(
            _latest_event_response(record.latest_event)
            if record.latest_event is not None
            else None
        ),
        errorType=record.error_type,
        errorMessage=record.error_message,
    )


def _latest_event_response(record: OpsLatestEventRecord) -> OpsLatestEventResponse:
    return OpsLatestEventResponse(
        operationEventId=record.operation_event_id,
        occurredAt=record.occurred_at,
        eventType=record.event_type,
        severity=record.severity,
        message=record.message,
        errorType=record.error_type,
        errorMessage=record.error_message,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
