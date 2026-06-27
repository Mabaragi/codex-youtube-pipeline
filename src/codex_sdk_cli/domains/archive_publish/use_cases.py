from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventCandidateRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionWindowRecord,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.timelines.ports import (
    TimelineCompositionRecord,
    TimelineCompositionRepositoryPort,
    TimelineEpisodeRecord,
)
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
)
from codex_sdk_cli.domains.video_tasks.exceptions import VideoTaskRetryNotAllowed
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskCreate,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
)
from codex_sdk_cli.domains.videos.exceptions import VideoNotFound
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort

from .constants import (
    ARCHIVE_IMMUTABLE_CACHE_CONTROL,
    ARCHIVE_POINTER_CACHE_CONTROL,
    ARCHIVE_PUBLISH_BATCH_SCAN_LIMIT,
    ARCHIVE_PUBLISH_RUNNER_ID,
    ARCHIVE_PUBLISH_TASK_NAME,
    ARCHIVE_PUBLISH_TASK_VERSION,
)
from .exceptions import (
    ArchivePublishArtifactInvalid,
    ArchivePublishConfigurationError,
    ArchivePublishPreconditionFailed,
)
from .ports import (
    ArchiveIndexArtifact,
    ArchiveIndexPublicationCreate,
    ArchiveIndexPublicationRecord,
    ArchiveObjectSaveRequest,
    ArchiveOpsVideoListResult,
    ArchiveOpsVideoQuery,
    ArchivePublishCandidateQuery,
    ArchivePublishCandidateRecord,
    ArchivePublishRepositoryPort,
    ArchivePublishStatusFilter,
    ArchivePublishStoragePort,
    ArchiveTimelineArtifact,
    ArchiveVideoArtifactCreate,
    ArchiveVideoArtifactRecord,
    ArchiveVideoArtifactWithVideoRecord,
)
from .schemas import (
    ArchiveCurrentResponse,
    ArchiveIndexPublicationResponse,
    ArchiveOpsVideoListResponse,
    ArchiveOpsVideoResponse,
    ArchivePublishItemResponse,
    ArchivePublishRequest,
    ArchivePublishResponse,
    ArchiveStorageConfigResponse,
    ArchiveVideoArtifactResponse,
    ArchiveVideoTaskSummaryResponse,
)

ArchivePublishStorageFactory = Callable[[], ArchivePublishStoragePort]


@dataclass(slots=True)
class _PublishCounters:
    scanned_count: int = 0
    processed_count: int = 0
    published_count: int = 0
    already_published_count: int = 0
    regenerated_count: int = 0
    failed_count: int = 0
    failed_skipped_count: int = 0
    ineligible_count: int = 0


@dataclass(frozen=True, slots=True)
class _PreparedArchivePublish:
    video: VideoRecord
    composition: TimelineCompositionRecord
    input_hash: str
    input_json: JsonObject
    existing_artifact: ArchiveVideoArtifactRecord | None


class ArchivePublishUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        timelines: TimelineCompositionRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        archive: ArchivePublishRepositoryPort,
        events: OperationEventRecorderPort,
        timeout_seconds: int,
        public_base_url: str | None,
        prefix: str,
        default_environment: str,
        default_schema_version: int,
        storage_bucket: str | None = None,
        storage_endpoint: str | None = None,
        storage_factory: ArchivePublishStorageFactory | None = None,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._timelines = timelines
        self._micro_events = micro_events
        self._transcript_cues = transcript_cues
        self._pipeline_jobs = pipeline_jobs
        self._archive = archive
        self._events = events
        self._timeout_seconds = timeout_seconds
        self._public_base_url = _normalized_public_base_url(public_base_url)
        self._prefix = _clean_path_part(prefix) or "archive"
        self._default_environment = default_environment
        self._default_schema_version = default_schema_version
        self._storage_bucket = storage_bucket
        self._storage_endpoint = storage_endpoint
        self._storage_factory = storage_factory

    async def publish(
        self,
        request: ArchivePublishRequest,
    ) -> ArchivePublishResponse:
        counters = _PublishCounters()
        items: list[ArchivePublishItemResponse] = []
        if request.target == "selected_videos":
            for video_id in request.video_ids[: request.limit]:
                counters.scanned_count += 1
                items.append(await self._publish_video_id(video_id, request, counters))
            return _publish_response(request, counters, items)

        candidates = await self._archive.list_publish_candidates(
            ArchivePublishCandidateQuery(
                channel_id=request.channel_id,
                search=request.search,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                limit=ARCHIVE_PUBLISH_BATCH_SCAN_LIMIT,
            )
        )
        for candidate in candidates:
            counters.scanned_count += 1
            item = await self._publish_candidate(candidate, request, counters)
            if request.target == "next_eligible" and item.reason in {
                "already_running",
                "already_published",
                "failed_skipped",
                "ineligible",
            }:
                continue
            items.append(item)
            if len(items) >= request.limit:
                break
        return _publish_response(request, counters, items)

    async def get_current(self, *, environment: str | None) -> ArchiveCurrentResponse:
        resolved_environment = environment or self._default_environment
        publication = await self._archive.get_latest_index_publication(
            environment=resolved_environment
        )
        return ArchiveCurrentResponse(
            environment=resolved_environment,
            storage=ArchiveStorageConfigResponse(
                configured=self._public_base_url is not None and self._storage_factory is not None,
                bucket=self._storage_bucket,
                endpoint=self._storage_endpoint,
                publicBaseUrl=self._public_base_url,
                prefix=self._prefix,
            ),
            latestPublication=(
                _index_publication_response(publication) if publication is not None else None
            ),
        )

    async def list_ops_videos(
        self,
        *,
        environment: str | None,
        channel_id: int | None,
        publish_status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> ArchiveOpsVideoListResponse:
        result = await self._archive.list_ops_videos(
            ArchiveOpsVideoQuery(
                environment=environment or self._default_environment,
                channel_id=channel_id,
                publish_status=_publish_status_filter(publish_status),
                search=search,
                limit=limit,
                offset=offset,
            )
        )
        return _ops_video_list_response(result, limit=limit, offset=offset)

    async def _execute_task_now(
        self,
        task: VideoTaskRecord,
        *,
        input_json: JsonObject,
    ) -> JsonObject:
        if task.task_name != ARCHIVE_PUBLISH_TASK_NAME:
            raise VideoTaskRetryNotAllowed("Only archive publish tasks can be executed.")
        if not input_json:
            await self._video_tasks.mark_task_failed(
                task.id,
                error_type="ArchivePublishInputMissing",
                error_message="Archive publish task is missing input_json.",
            )
            raise VideoTaskRetryNotAllowed("Archive publish task is missing input_json.")
        job_input_json = {**input_json, "videoTaskId": task.id}
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=ARCHIVE_PUBLISH_TASK_NAME,
                status="running",
                subject_type="video",
                subject_id=_required_int(job_input_json, "videoId"),
                external_key=_str_output(job_input_json, "youtubeVideoId"),
                input_json=job_input_json,
                input_hash=_required_str(job_input_json, "inputHash"),
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(
            job_id=job.id,
            worker_id=ARCHIVE_PUBLISH_RUNNER_ID,
        )
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=ARCHIVE_PUBLISH_RUNNER_ID,
            timeout_seconds=_required_int(job_input_json, "timeoutSeconds"),
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        await self._record_event(
            "archive_publish.task_running",
            "info",
            "Archive publish task started running.",
            task=task,
            job=job,
            attempt=attempt,
            metadata_json={"runner": ARCHIVE_PUBLISH_RUNNER_ID},
        )
        return await self._execute_job_attempt(job, attempt, task=task)

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        task_id = _required_int(job.input_json, "videoTaskId")
        task = await self._video_tasks.get_task(task_id)
        if task is None:
            raise VideoTaskRetryNotAllowed("Video task not found.")
        if task.task_name != ARCHIVE_PUBLISH_TASK_NAME:
            raise VideoTaskRetryNotAllowed("Pipeline job is not an archive publish task.")
        if task.status not in {"failed", "timed_out"}:
            raise VideoTaskRetryNotAllowed("Only failed archive publish tasks can be retried.")
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=ARCHIVE_PUBLISH_RUNNER_ID,
            timeout_seconds=_required_int(job.input_json, "timeoutSeconds"),
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        return await self._execute_job_attempt(job, attempt, task=task, actor_type="retry_executor")

    async def _publish_video_id(
        self,
        video_id: int,
        request: ArchivePublishRequest,
        counters: _PublishCounters,
    ) -> ArchivePublishItemResponse:
        candidate = await self._archive.get_publish_candidate(
            video_id=video_id,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
        )
        if candidate is None:
            counters.ineligible_count += 1
            return _publish_item(
                video_id=video_id,
                youtube_video_id=None,
                task=None,
                status="skipped",
                reason="video_not_found",
                composition=None,
                artifact=None,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                error_type="VideoNotFound",
                error_message="Video not found.",
            )
        return await self._publish_candidate(candidate, request, counters)

    async def _publish_candidate(
        self,
        candidate: ArchivePublishCandidateRecord,
        request: ArchivePublishRequest,
        counters: _PublishCounters,
    ) -> ArchivePublishItemResponse:
        try:
            prepared = self._prepare(candidate, request)
        except ArchivePublishPreconditionFailed as exc:
            counters.ineligible_count += 1
            return _publish_item(
                video_id=candidate.video.id,
                youtube_video_id=candidate.video.youtube_video_id,
                task=None,
                status="skipped",
                reason="ineligible",
                composition=candidate.composition,
                artifact=candidate.latest_artifact,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                error_type=exc.__class__.__name__,
                error_message=exc.message,
            )

        existing = await self._video_tasks.get_task_for_input(
            video_id=prepared.video.id,
            task_name=ARCHIVE_PUBLISH_TASK_NAME,
            task_version=ARCHIVE_PUBLISH_TASK_VERSION,
            input_hash=prepared.input_hash,
        )
        if existing is None:
            task = await self._video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=prepared.video.id,
                    task_name=ARCHIVE_PUBLISH_TASK_NAME,
                    task_version=ARCHIVE_PUBLISH_TASK_VERSION,
                    input_hash=prepared.input_hash,
                    timeout_seconds=self._timeout_seconds,
                    input_json=prepared.input_json,
                    status="pending",
                )
            )
            await self._record_event(
                "archive_publish.task_requested",
                "info",
                "Archive publish task requested.",
                task=task,
                metadata_json=prepared.input_json,
            )
            return await self._run_prepared_task(
                task=task,
                prepared=prepared,
                request=request,
                counters=counters,
                reason="published",
            )
        return await self._handle_existing_task(existing, prepared, request, counters)

    async def _run_prepared_task(
        self,
        *,
        task: VideoTaskRecord,
        prepared: _PreparedArchivePublish,
        request: ArchivePublishRequest,
        counters: _PublishCounters,
        reason: str,
    ) -> ArchivePublishItemResponse:
        counters.processed_count += 1
        try:
            output = await self._execute_task_now(
                task=task,
                input_json=task.input_json or prepared.input_json,
            )
        except Exception as exc:
            counters.failed_count += 1
            return _publish_item(
                video_id=prepared.video.id,
                youtube_video_id=prepared.video.youtube_video_id,
                task=task,
                status="failed",
                reason="failed",
                composition=prepared.composition,
                artifact=prepared.existing_artifact,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
        counters.published_count += 1
        if reason == "regenerated":
            counters.regenerated_count += 1
        return _publish_item(
            video_id=prepared.video.id,
            youtube_video_id=prepared.video.youtube_video_id,
            task=task,
            status="succeeded",
            reason=reason,
            composition=prepared.composition,
            artifact=prepared.existing_artifact,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
            artifact_id=_int_output(output, "artifactId"),
            public_url=_str_output(output, "publicUrl"),
        )

    async def _handle_existing_task(
        self,
        task: VideoTaskRecord,
        prepared: _PreparedArchivePublish,
        request: ArchivePublishRequest,
        counters: _PublishCounters,
    ) -> ArchivePublishItemResponse:
        if task.status == "pending":
            return await self._run_prepared_task(
                task=task,
                prepared=prepared,
                request=request,
                counters=counters,
                reason="published",
            )
        if task.status == "running":
            return _publish_item(
                video_id=prepared.video.id,
                youtube_video_id=prepared.video.youtube_video_id,
                task=task,
                status="skipped",
                reason="already_running",
                composition=prepared.composition,
                artifact=prepared.existing_artifact,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
            )
        elif task.status == "succeeded" and not request.regenerate_succeeded:
            counters.already_published_count += 1
            reason = "already_published"
        elif task.status in {"failed", "timed_out"} and not request.retry_failed:
            counters.failed_skipped_count += 1
            return _publish_item(
                video_id=prepared.video.id,
                youtube_video_id=prepared.video.youtube_video_id,
                task=task,
                status=task.status,
                reason="failed_skipped",
                composition=prepared.composition,
                artifact=prepared.existing_artifact,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                error_type=task.error_type,
                error_message=task.error_message,
            )
        else:
            reset = await self._video_tasks.reset_task_to_pending(
                task.id,
                timeout_seconds=self._timeout_seconds,
                input_json=prepared.input_json,
            )
            reason = "regenerated" if task.status == "succeeded" else "published"
            return await self._run_prepared_task(
                task=reset,
                reason=reason,
                prepared=prepared,
                request=request,
                counters=counters,
            )
        return _publish_item(
            video_id=prepared.video.id,
            youtube_video_id=prepared.video.youtube_video_id,
            task=task,
            status="skipped",
            reason=reason,
            composition=prepared.composition,
            artifact=prepared.existing_artifact,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
        )

    def _prepare(
        self,
        candidate: ArchivePublishCandidateRecord,
        request: ArchivePublishRequest,
    ) -> _PreparedArchivePublish:
        if candidate.composition is None:
            raise ArchivePublishPreconditionFailed(
                "Latest succeeded timeline composition is required before archive publish."
            )
        input_hash = _task_input_hash(
            video=candidate.video,
            composition=candidate.composition,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
        )
        input_json = _task_input_json(
            video=candidate.video,
            composition=candidate.composition,
            input_hash=input_hash,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
            timeout_seconds=self._timeout_seconds,
        )
        return _PreparedArchivePublish(
            video=candidate.video,
            composition=candidate.composition,
            input_hash=input_hash,
            input_json=input_json,
            existing_artifact=candidate.latest_artifact,
        )

    async def _execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        actor_type: OperationEventActorType = "manual_api",
    ) -> JsonObject:
        try:
            storage = self._storage()
            video = await self._videos.get_video(task.video_id)
            if video is None:
                raise VideoNotFound("Video not found.")
            composition = await self._timelines.get_composition(
                video_id=video.id,
                video_task_id=_required_int(job.input_json, "sourceTimelineTaskId"),
            )
            if composition is None:
                raise ArchivePublishPreconditionFailed("Timeline composition not found.")
            micro_detail = await self._micro_events.get_extraction(
                video_id=video.id,
                video_task_id=composition.source_micro_event_task_id,
            )
            if micro_detail is None or micro_detail.transcript_id is None:
                raise ArchivePublishPreconditionFailed("Source micro-event extraction not found.")
            cues = await self._transcript_cues.list_cues(micro_detail.transcript_id)
            timeline_artifact = _timeline_artifact(
                video=video,
                composition=composition,
                micro_events=_flatten_micro_events(micro_detail.windows),
                cues=cues,
                prefix=self._prefix,
                public_base_url=_required_public_base_url(self._public_base_url),
                environment=_required_str(job.input_json, "environment"),
                variant=_required_str(job.input_json, "variant"),
                schema_version=_required_int(job.input_json, "schemaVersion"),
            )
            await storage.save_json(
                ArchiveObjectSaveRequest(
                    object_key=timeline_artifact.object_key,
                    payload=timeline_artifact.payload_bytes,
                    cache_control=ARCHIVE_IMMUTABLE_CACHE_CONTROL,
                )
            )
            artifact = await self._archive.create_video_artifact(
                ArchiveVideoArtifactCreate(
                    video_id=video.id,
                    source_timeline_composition_id=composition.id,
                    source_timeline_task_id=composition.video_task_id,
                    source_micro_event_task_id=composition.source_micro_event_task_id,
                    publish_task_id=task.id,
                    publish_job_id=job.id,
                    environment=_required_str(job.input_json, "environment"),
                    variant=_required_str(job.input_json, "variant"),
                    schema_version=_required_int(job.input_json, "schemaVersion"),
                    version=timeline_artifact.version,
                    object_key=timeline_artifact.object_key,
                    public_url=timeline_artifact.public_url,
                    sha256=timeline_artifact.sha256,
                    byte_size=timeline_artifact.byte_size,
                    block_count=timeline_artifact.block_count,
                    episode_count=timeline_artifact.episode_count,
                    topic_cluster_count=timeline_artifact.topic_cluster_count,
                    review_flag_count=timeline_artifact.review_flag_count,
                    micro_event_count=timeline_artifact.micro_event_count,
                )
            )
            index_artifact = _index_artifact(
                artifacts=await self._archive.list_latest_video_artifacts(
                    environment=_required_str(job.input_json, "environment"),
                    schema_version=_required_int(job.input_json, "schemaVersion"),
                ),
                prefix=self._prefix,
                public_base_url=_required_public_base_url(self._public_base_url),
                environment=_required_str(job.input_json, "environment"),
                schema_version=_required_int(job.input_json, "schemaVersion"),
            )
            await storage.save_json(
                ArchiveObjectSaveRequest(
                    object_key=index_artifact.object_key,
                    payload=index_artifact.payload_bytes,
                    cache_control=ARCHIVE_IMMUTABLE_CACHE_CONTROL,
                )
            )
            index_record = await self._archive.create_index_publication(
                ArchiveIndexPublicationCreate(
                    environment=_required_str(job.input_json, "environment"),
                    schema_version=_required_int(job.input_json, "schemaVersion"),
                    version=index_artifact.version,
                    pointer_key=index_artifact.pointer_key,
                    index_key=index_artifact.object_key,
                    public_url=index_artifact.public_url,
                    sha256=index_artifact.sha256,
                    byte_size=index_artifact.byte_size,
                    video_count=index_artifact.video_count,
                )
            )
            await storage.save_json(
                ArchiveObjectSaveRequest(
                    object_key=index_artifact.pointer_key,
                    payload=index_artifact.pointer_payload_bytes,
                    cache_control=ARCHIVE_POINTER_CACHE_CONTROL,
                )
            )
            output = _publish_output_json(
                artifact=artifact,
                index=index_record,
                pointer_public_url=index_artifact.pointer_public_url,
                job=job,
                attempt=attempt,
            )
            await self._pipeline_jobs.mark_attempt_succeeded(
                attempt.id,
                output_json=output,
            )
            await self._pipeline_jobs.mark_job_succeeded(job.id)
            await self._video_tasks.mark_task_succeeded(
                task.id,
                output_transcript_id=None,
                output_json=output,
            )
            await self._record_event(
                "archive_publish.task_succeeded",
                "info",
                "Archive publish task succeeded.",
                task=task,
                job=job,
                attempt=attempt,
                actor_type=actor_type,
                metadata_json=output,
            )
            return output
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            failed_output: JsonObject = {
                "videoTaskId": task.id,
                "jobId": job.id,
                "jobAttemptId": attempt.id,
                "errorType": error_type,
                "errorMessage": error_message,
            }
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
                output_json=failed_output,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json=failed_output,
            )
            await self._record_event(
                "archive_publish.task_failed",
                "error",
                "Archive publish task failed.",
                task=task,
                job=job,
                attempt=attempt,
                actor_type=actor_type,
                error_type=error_type,
                error_message=error_message,
                metadata_json=failed_output,
            )
            raise

    def _storage(self) -> ArchivePublishStoragePort:
        if self._storage_factory is None:
            raise ArchivePublishConfigurationError("Archive publish storage is not configured.")
        if self._public_base_url is None:
            raise ArchivePublishConfigurationError(
                "Archive publish public base URL is not configured."
            )
        return self._storage_factory()

    async def _record_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord | None = None,
        attempt: PipelineJobAttemptRecord | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
        actor_type: OperationEventActorType = "manual_api",
    ) -> None:
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=actor_type,
                source="archive.publish",
                job_id=job.id if job is not None else task.job_id,
                job_attempt_id=attempt.id if attempt is not None else task.job_attempt_id,
                video_task_id=task.id,
                video_id=task.video_id,
                subject_type=job.subject_type if job is not None else "video",
                subject_id=job.subject_id if job is not None else task.video_id,
                external_key=job.external_key if job is not None else None,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata_json or {},
            ),
        )


def _timeline_artifact(
    *,
    video: VideoRecord,
    composition: TimelineCompositionRecord,
    micro_events: list[MicroEventCandidateRecord],
    cues: list[TranscriptCueRecord],
    prefix: str,
    public_base_url: str,
    environment: str,
    variant: str,
    schema_version: int,
) -> ArchiveTimelineArtifact:
    candidate_by_id = {candidate.id: candidate for candidate in micro_events}
    cue_by_id = {cue.cue_id: cue for cue in cues}
    version = _version()
    object_key = (
        f"{prefix}/archive/v{schema_version}/videos/{video.id}/"
        f"timeline.{version}.{_clean_path_part(variant)}.json"
    )
    episodes = [
        _episode_json(
            episode,
            ordered_candidates=micro_events,
            candidate_by_id=candidate_by_id,
            cue_by_id=cue_by_id,
        )
        for episode in composition.episodes
    ]
    episodes_by_id = {
        episode.episode_id: episode_json
        for episode, episode_json in zip(composition.episodes, episodes, strict=True)
    }
    payload: JsonObject = {
        "schemaVersion": schema_version,
        "environment": environment,
        "variant": variant,
        "version": version,
        "generatedAt": _now_iso(),
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceTimelineCompositionId": composition.id,
        "sourceTimelineTaskId": composition.video_task_id,
        "sourceMicroEventTaskId": composition.source_micro_event_task_id,
        "video": {
            "id": video.id,
            "youtubeId": video.youtube_video_id,
            "title": video.title,
            "publishedAt": video.published_at.isoformat(),
            "duration": video.duration,
            "durationSec": _duration_seconds(video.duration),
            "thumbnailUrl": video.thumbnail_url,
            "summary": composition.summary,
            "displayTitle": composition.display_title,
            "displaySummary": composition.display_summary,
            "mainTopics": composition.main_topics,
        },
        "blocks": [
            {
                "blockId": block.block_id,
                "blockIndex": block.block_index,
                "blockType": block.block_type,
                "title": block.title,
                "summary": block.summary,
                "displayTitle": block.display_title,
                "displaySummary": block.display_summary,
                "episodeIds": block.episode_ids,
                "episodes": _block_episode_jsons(
                    block_id=block.block_id,
                    episode_ids=block.episode_ids,
                    episodes_by_id=episodes_by_id,
                ),
            }
            for block in composition.blocks
        ],
        "episodes": episodes,
        "topicClusters": [
            {
                "topicId": topic.topic_id,
                "topicIndex": topic.topic_index,
                "label": topic.label,
                "summary": topic.summary,
                "displayLabel": topic.display_label,
                "episodeIds": topic.episode_ids,
            }
            for topic in composition.topic_clusters
        ],
        "reviewFlags": [
            {
                "flagIndex": flag.flag_index,
                "startMicroEventCandidateId": flag.start_micro_event_candidate_id,
                "endMicroEventCandidateId": flag.end_micro_event_candidate_id,
                "type": flag.type,
                "reason": flag.reason,
            }
            for flag in composition.review_flags
        ],
    }
    payload_bytes = _json_bytes(payload)
    return ArchiveTimelineArtifact(
        object_key=object_key,
        public_url=_public_url(public_base_url, object_key),
        payload=payload,
        payload_bytes=payload_bytes,
        sha256=_sha256(payload_bytes),
        byte_size=len(payload_bytes),
        version=version,
        block_count=len(composition.blocks),
        episode_count=len(composition.episodes),
        topic_cluster_count=len(composition.topic_clusters),
        review_flag_count=len(composition.review_flags),
        micro_event_count=len(micro_events),
    )


def _episode_json(
    episode: TimelineEpisodeRecord,
    *,
    ordered_candidates: list[MicroEventCandidateRecord],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
    cue_by_id: dict[str, TranscriptCueRecord],
) -> JsonObject:
    start_candidate = _candidate(candidate_by_id, episode.start_micro_event_candidate_id)
    end_candidate = _candidate(candidate_by_id, episode.end_micro_event_candidate_id)
    start_cue = _cue(cue_by_id, start_candidate.start_cue_id)
    end_cue = _cue(cue_by_id, end_candidate.end_cue_id)
    return {
        "episodeId": episode.episode_id,
        "episodeIndex": episode.episode_index,
        "parentBlockId": episode.parent_block_id,
        "startMicroEventCandidateId": episode.start_micro_event_candidate_id,
        "endMicroEventCandidateId": episode.end_micro_event_candidate_id,
        "startCueId": start_cue.cue_id,
        "endCueId": end_cue.cue_id,
        "startMs": start_cue.start_ms,
        "endMs": end_cue.end_ms,
        "programMode": episode.program_mode,
        "primaryContentKind": episode.primary_content_kind,
        "title": episode.title,
        "summary": episode.summary,
        "displayTitle": episode.display_title,
        "displaySummary": episode.display_summary,
        "topics": episode.topics,
        "viewerTags": episode.viewer_tags,
        "highlightMicroEventCandidateIds": episode.highlight_micro_event_candidate_ids,
        "visibility": episode.visibility,
        "microEvents": _micro_event_jsons(
            episode,
            ordered_candidates=ordered_candidates,
            candidate_by_id=candidate_by_id,
            cue_by_id=cue_by_id,
        ),
    }


def _block_episode_jsons(
    *,
    block_id: str,
    episode_ids: list[str],
    episodes_by_id: dict[str, JsonObject],
) -> list[JsonObject]:
    episodes: list[JsonObject] = []
    for episode_id in episode_ids:
        episode = episodes_by_id.get(episode_id)
        if episode is None:
            raise ArchivePublishArtifactInvalid(
                f"Timeline block {block_id} references missing episode '{episode_id}'."
            )
        episodes.append(episode)
    return episodes


def _micro_event_jsons(
    episode: TimelineEpisodeRecord,
    *,
    ordered_candidates: list[MicroEventCandidateRecord],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
    cue_by_id: dict[str, TranscriptCueRecord],
) -> list[JsonObject]:
    start_candidate = _candidate(candidate_by_id, episode.start_micro_event_candidate_id)
    end_candidate = _candidate(candidate_by_id, episode.end_micro_event_candidate_id)
    candidate_positions = {
        candidate.id: index for index, candidate in enumerate(ordered_candidates)
    }
    start_position = candidate_positions.get(start_candidate.id)
    end_position = candidate_positions.get(end_candidate.id)
    if start_position is None or end_position is None or start_position > end_position:
        raise ArchivePublishArtifactInvalid(
            f"Timeline episode {episode.episode_id} references an invalid micro-event range."
        )
    return [
        _micro_event_json(candidate, cue_by_id=cue_by_id)
        for candidate in ordered_candidates[start_position : end_position + 1]
    ]


def _micro_event_json(
    candidate: MicroEventCandidateRecord,
    *,
    cue_by_id: dict[str, TranscriptCueRecord],
) -> JsonObject:
    start_cue = _cue(cue_by_id, candidate.start_cue_id)
    end_cue = _cue(cue_by_id, candidate.end_cue_id)
    evidence_cue_ids = [
        cue_id for cue_id in candidate.evidence_cue_ids if cue_id in cue_by_id
    ]
    return {
        "microEventCandidateId": candidate.id,
        "candidateIndex": candidate.candidate_index,
        "event": candidate.event,
        "activity": candidate.activity,
        "programMode": candidate.program_mode,
        "contentKind": candidate.content_kind,
        "topics": candidate.topics or [],
        "startCueId": start_cue.cue_id,
        "endCueId": end_cue.cue_id,
        "startMs": start_cue.start_ms,
        "endMs": end_cue.end_ms,
        "evidenceCueIds": evidence_cue_ids,
        "boundaryBefore": candidate.boundary_before,
        "boundaryAfter": candidate.boundary_after,
        "relationToPrevious": candidate.relation_to_previous,
        "continuesToNext": candidate.continues_to_next,
        "supportLevel": candidate.support_level,
    }


def _index_artifact(
    *,
    artifacts: list[ArchiveVideoArtifactWithVideoRecord],
    prefix: str,
    public_base_url: str,
    environment: str,
    schema_version: int,
) -> ArchiveIndexArtifact:
    version = _version()
    object_key = f"{prefix}/archive/v{schema_version}/index.{version}.json"
    pointer_key = f"{prefix}/channels/{_clean_path_part(environment)}.json"
    videos_by_id: dict[int, dict[str, object]] = {}
    for item in artifacts:
        artifact = item.artifact
        video = item.video
        row = videos_by_id.setdefault(
            video.id,
            {
                "id": video.id,
                "youtubeId": video.youtube_video_id,
                "title": video.title,
                "publishedAt": video.published_at.isoformat(),
                "durationText": video.duration,
                "episodeCount": artifact.episode_count,
                "eventCount": artifact.micro_event_count,
                "thumbnailUrl": video.thumbnail_url,
                "timelineVariants": [],
            },
        )
        variants = row["timelineVariants"]
        if isinstance(variants, list):
            variants.append(
                {
                    "key": artifact.variant,
                    "url": artifact.public_url,
                    "version": artifact.version,
                    "sourceTimelineTaskId": artifact.source_timeline_task_id,
                    "artifactId": artifact.id,
                }
            )
    videos = list(videos_by_id.values())
    videos.sort(
        key=lambda item: (str(item.get("publishedAt")), int(item.get("id", 0))), reverse=True
    )
    payload: JsonObject = {
        "schemaVersion": schema_version,
        "environment": environment,
        "generatedAt": _now_iso(),
        "version": version,
        "videos": videos,
    }
    pointer_payload: JsonObject = {
        "schemaVersion": schema_version,
        "environment": environment,
        "generatedAt": _now_iso(),
        "currentIndexUrl": _public_url(public_base_url, object_key),
        "currentIndexVersion": version,
        "videoCount": len(videos),
    }
    payload_bytes = _json_bytes(payload)
    pointer_payload_bytes = _json_bytes(pointer_payload)
    return ArchiveIndexArtifact(
        object_key=object_key,
        public_url=_public_url(public_base_url, object_key),
        payload=payload,
        payload_bytes=payload_bytes,
        sha256=_sha256(payload_bytes),
        byte_size=len(payload_bytes),
        version=version,
        video_count=len(videos),
        pointer_key=pointer_key,
        pointer_payload=pointer_payload,
        pointer_payload_bytes=pointer_payload_bytes,
        pointer_sha256=_sha256(pointer_payload_bytes),
        pointer_byte_size=len(pointer_payload_bytes),
        pointer_public_url=_public_url(public_base_url, pointer_key),
        artifact_ids=[item.artifact.id for item in artifacts],
    )


def _candidate(
    candidates: dict[int, MicroEventCandidateRecord],
    candidate_id: int | None,
) -> MicroEventCandidateRecord:
    if candidate_id is None or candidate_id not in candidates:
        raise ArchivePublishArtifactInvalid(
            f"Timeline episode references missing micro-event candidate #{candidate_id}."
        )
    return candidates[candidate_id]


def _cue(cues: dict[str, TranscriptCueRecord], cue_id: str) -> TranscriptCueRecord:
    cue = cues.get(cue_id)
    if cue is None:
        raise ArchivePublishArtifactInvalid(
            f"Micro-event candidate references missing cue '{cue_id}'."
        )
    return cue


def _flatten_micro_events(
    windows: list[MicroEventExtractionWindowRecord],
) -> list[MicroEventCandidateRecord]:
    return [
        candidate
        for window in sorted(windows, key=lambda item: item.window_index)
        for candidate in sorted(window.micro_events, key=lambda item: item.candidate_index)
    ]


def _task_input_hash(
    *,
    video: VideoRecord,
    composition: TimelineCompositionRecord,
    environment: str,
    variant: str,
    schema_version: int,
) -> str:
    payload = {
        "environment": environment,
        "schemaVersion": schema_version,
        "sourceMicroEventTaskId": composition.source_micro_event_task_id,
        "sourceTimelineCompositionId": composition.id,
        "sourceTimelineTaskId": composition.video_task_id,
        "taskVersion": ARCHIVE_PUBLISH_TASK_VERSION,
        "variant": variant,
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    *,
    video: VideoRecord,
    composition: TimelineCompositionRecord,
    input_hash: str,
    environment: str,
    variant: str,
    schema_version: int,
    timeout_seconds: int,
) -> JsonObject:
    return {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceTimelineCompositionId": composition.id,
        "sourceTimelineTaskId": composition.video_task_id,
        "sourceMicroEventTaskId": composition.source_micro_event_task_id,
        "taskVersion": ARCHIVE_PUBLISH_TASK_VERSION,
        "inputHash": input_hash,
        "environment": environment,
        "variant": variant,
        "schemaVersion": schema_version,
        "timeoutSeconds": timeout_seconds,
    }


def _publish_response(
    request: ArchivePublishRequest,
    counters: _PublishCounters,
    items: list[ArchivePublishItemResponse],
) -> ArchivePublishResponse:
    requested_count = (
        min(len(request.video_ids), request.limit)
        if request.target == "selected_videos"
        else request.limit
    )
    return ArchivePublishResponse(
        requestedCount=requested_count,
        scannedCount=counters.scanned_count,
        processedCount=counters.processed_count,
        publishedCount=counters.published_count,
        alreadyPublishedCount=counters.already_published_count,
        regeneratedCount=counters.regenerated_count,
        failedCount=counters.failed_count,
        failedSkippedCount=counters.failed_skipped_count,
        ineligibleCount=counters.ineligible_count,
        items=items,
    )


def _publish_item(
    *,
    video_id: int,
    youtube_video_id: str | None,
    task: VideoTaskRecord | None,
    status: str,
    reason: str,
    composition: TimelineCompositionRecord | None,
    artifact: ArchiveVideoArtifactRecord | None,
    environment: str,
    variant: str,
    schema_version: int,
    artifact_id: int | None = None,
    public_url: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> ArchivePublishItemResponse:
    return ArchivePublishItemResponse(
        videoId=video_id,
        youtubeVideoId=youtube_video_id,
        videoTaskId=task.id if task is not None else None,
        status=status,
        reason=reason,
        sourceTimelineTaskId=composition.video_task_id if composition is not None else None,
        sourceTimelineCompositionId=composition.id if composition is not None else None,
        environment=environment,
        variant=variant,
        schemaVersion=schema_version,
        artifactId=(
            artifact_id if artifact_id is not None else (artifact.id if artifact else None)
        ),
        publicUrl=(
            public_url if public_url is not None else (artifact.public_url if artifact else None)
        ),
        errorType=error_type,
        errorMessage=error_message,
    )


def _ops_video_list_response(
    result: ArchiveOpsVideoListResult,
    *,
    limit: int,
    offset: int,
) -> ArchiveOpsVideoListResponse:
    return ArchiveOpsVideoListResponse(
        items=[
            ArchiveOpsVideoResponse(
                videoId=item.video.id,
                channelId=item.video.channel_id,
                channelName=item.channel_name,
                youtubeVideoId=item.video.youtube_video_id,
                title=item.video.title,
                publishedAt=item.video.published_at,
                duration=item.video.duration,
                thumbnailUrl=item.video.thumbnail_url,
                timelineReady=item.timeline_composition_id is not None,
                timelineCompositionId=item.timeline_composition_id,
                timelineTaskId=item.timeline_task_id,
                timelineEpisodeCount=item.timeline_episode_count,
                latestTask=(
                    _task_summary_response(item.latest_archive_task)
                    if item.latest_archive_task is not None
                    else None
                ),
                latestArtifact=(
                    _artifact_response(item.latest_artifact)
                    if item.latest_artifact is not None
                    else None
                ),
            )
            for item in result.items
        ],
        total=result.total,
        limit=limit,
        offset=offset,
    )


def _task_summary_response(task: VideoTaskRecord) -> ArchiveVideoTaskSummaryResponse:
    return ArchiveVideoTaskSummaryResponse(
        videoTaskId=task.id,
        status=task.status,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        errorType=task.error_type,
        errorMessage=task.error_message,
        updatedAt=task.updated_at,
    )


def _artifact_response(artifact: ArchiveVideoArtifactRecord) -> ArchiveVideoArtifactResponse:
    return ArchiveVideoArtifactResponse(
        artifactId=artifact.id,
        sourceTimelineCompositionId=artifact.source_timeline_composition_id,
        sourceTimelineTaskId=artifact.source_timeline_task_id,
        sourceMicroEventTaskId=artifact.source_micro_event_task_id,
        publishTaskId=artifact.publish_task_id,
        publishJobId=artifact.publish_job_id,
        environment=artifact.environment,
        variant=artifact.variant,
        schemaVersion=artifact.schema_version,
        version=artifact.version,
        objectKey=artifact.object_key,
        publicUrl=artifact.public_url,
        sha256=artifact.sha256,
        byteSize=artifact.byte_size,
        blockCount=artifact.block_count,
        episodeCount=artifact.episode_count,
        topicClusterCount=artifact.topic_cluster_count,
        reviewFlagCount=artifact.review_flag_count,
        microEventCount=artifact.micro_event_count,
        createdAt=artifact.created_at,
    )


def _index_publication_response(
    record: ArchiveIndexPublicationRecord,
) -> ArchiveIndexPublicationResponse:
    return ArchiveIndexPublicationResponse(
        publicationId=record.id,
        environment=record.environment,
        schemaVersion=record.schema_version,
        version=record.version,
        pointerKey=record.pointer_key,
        indexKey=record.index_key,
        publicUrl=record.public_url,
        sha256=record.sha256,
        byteSize=record.byte_size,
        videoCount=record.video_count,
        createdAt=record.created_at,
    )


def _publish_output_json(
    *,
    artifact: ArchiveVideoArtifactRecord,
    index: ArchiveIndexPublicationRecord,
    pointer_public_url: str,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> JsonObject:
    return {
        "videoTaskId": artifact.publish_task_id,
        "videoId": artifact.video_id,
        "artifactId": artifact.id,
        "objectKey": artifact.object_key,
        "publicUrl": artifact.public_url,
        "version": artifact.version,
        "sha256": artifact.sha256,
        "byteSize": artifact.byte_size,
        "indexPublicationId": index.id,
        "indexKey": index.index_key,
        "indexUrl": index.public_url,
        "pointerKey": index.pointer_key,
        "pointerUrl": pointer_public_url,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }


def _duration_seconds(duration: str | None) -> int | None:
    if not duration or not duration.startswith("PT"):
        return None
    total = 0
    number = ""
    for char in duration[2:]:
        if char.isdigit():
            number += char
            continue
        if not number:
            continue
        value = int(number)
        number = ""
        if char == "H":
            total += value * 3600
        elif char == "M":
            total += value * 60
        elif char == "S":
            total += value
    return total or None


def _json_bytes(payload: JsonObject) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _version() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_path_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return cleaned.strip("-_") or "default"


def _normalized_public_base_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().rstrip("/")


def _required_public_base_url(value: str | None) -> str:
    if value is None:
        raise ArchivePublishConfigurationError("Archive publish public base URL is not configured.")
    return value


def _public_url(public_base_url: str, object_key: str) -> str:
    return f"{public_base_url}/{object_key.lstrip('/')}"


def _int_output(input_json: JsonObject, key: str) -> int | None:
    value = input_json.get(key)
    return value if isinstance(value, int) else None


def _str_output(input_json: JsonObject, key: str) -> str | None:
    value = input_json.get(key)
    return value if isinstance(value, str) else None


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str) or not value:
        raise VideoTaskRetryNotAllowed(f"Task input is missing string '{key}'.")
    return value


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Task input is missing integer '{key}'.")
    return value


def _publish_status_filter(value: str | None) -> ArchivePublishStatusFilter | None:
    allowed: set[ArchivePublishStatusFilter] = {
        "not_ready",
        "ready",
        "pending",
        "running",
        "failed",
        "published",
    }
    return cast(ArchivePublishStatusFilter, value) if value in allowed else None
