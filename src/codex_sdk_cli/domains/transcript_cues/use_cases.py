from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

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
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptMetadataNotFound,
    YouTubeTranscriptStorageError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptResponse

from .ports import (
    TranscriptCueCreate,
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
    TranscriptCueSummaryRecord,
)
from .schemas import (
    PromptCueResponse,
    TranscriptCueGenerateResponse,
    TranscriptCueListResponse,
    TranscriptCueResponse,
    TranscriptPromptCuesResponse,
)

TRANSCRIPT_CUE_GENERATE_STEP = "transcript_cue_generate"
TRANSCRIPT_CUE_GENERATE_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class TranscriptCueGenerationResult:
    response: TranscriptCueGenerateResponse
    job: PipelineJobRecord
    attempt: PipelineJobAttemptRecord


class GenerateTranscriptCuesUseCase:
    def __init__(
        self,
        *,
        transcripts: YouTubeTranscriptRepositoryPort,
        storage: YouTubeTranscriptStoragePort,
        cues: TranscriptCueRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        events: OperationEventRecorderPort,
    ) -> None:
        self._transcripts = transcripts
        self._storage = storage
        self._cues = cues
        self._pipeline_jobs = pipeline_jobs
        self._events = events

    async def execute(
        self,
        transcript_id: int,
        *,
        parent_job_id: int | None = None,
        actor_type: OperationEventActorType = "manual_api",
    ) -> TranscriptCueGenerateResponse:
        metadata = await self._get_metadata(transcript_id)
        input_json = _input_json(metadata)
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=TRANSCRIPT_CUE_GENERATE_STEP,
                status="running",
                subject_type="transcript",
                subject_id=metadata.id,
                external_key=metadata.video_id,
                input_json=input_json,
                input_hash=_input_hash(input_json),
                parent_job_id=parent_job_id,
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)
        result = await self.execute_job_attempt(
            job,
            attempt,
            metadata=metadata,
            actor_type=actor_type,
        )
        return result.response

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        transcript_id = _required_int(job.input_json, "transcriptId")
        metadata = await self._get_metadata(transcript_id)
        result = await self.execute_job_attempt(
            job,
            attempt,
            metadata=metadata,
            actor_type="retry_executor",
        )
        return result.response.model_dump(by_alias=True)

    async def execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        metadata: YouTubeTranscriptMetadataRecord,
        actor_type: OperationEventActorType,
    ) -> TranscriptCueGenerationResult:
        await self._record_event(
            "transcript_cue_generate.started",
            "info",
            "Transcript cue generation started.",
            job=job,
            attempt=attempt,
            actor_type=actor_type,
            metadata_json={
                "transcriptId": metadata.id,
                "youtubeVideoId": metadata.video_id,
                "responseSha256": metadata.response_sha256,
            },
        )
        try:
            content = await self._read_content(metadata)
            cue_rows = _cue_creates(
                metadata.id,
                content,
                source_job_id=job.id,
                source_job_attempt_id=attempt.id,
            )
            records = await self._cues.replace_cues(metadata.id, cue_rows)
            summary = _summary_from_records(
                metadata.id,
                records,
                source_job_id=job.id,
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            await self._record_event(
                "transcript_cue_generate.failed",
                "error",
                "Transcript cue generation failed.",
                job=job,
                attempt=attempt,
                actor_type=actor_type,
                error_type=error_type,
                error_message=error_message,
            )
            raise

        output_json = _output_json(metadata, summary, job_id=job.id, attempt_id=attempt.id)
        await self._pipeline_jobs.mark_attempt_succeeded(attempt.id, output_json=output_json)
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        await self._record_event(
            "transcript_cue_generate.succeeded",
            "info",
            "Transcript cue generation succeeded.",
            job=job,
            attempt=attempt,
            actor_type=actor_type,
            metadata_json=output_json,
        )
        return TranscriptCueGenerationResult(
            response=TranscriptCueGenerateResponse(
                transcriptId=metadata.id,
                youtubeVideoId=metadata.video_id,
                jobId=job.id,
                jobAttemptId=attempt.id,
                cueCount=summary.cue_count,
                firstCueId=summary.first_cue_id,
                lastCueId=summary.last_cue_id,
            ),
            job=job,
            attempt=attempt,
        )

    async def _get_metadata(self, transcript_id: int) -> YouTubeTranscriptMetadataRecord:
        metadata = await self._transcripts.get_transcript_metadata(transcript_id)
        if metadata is None:
            raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")
        return metadata

    async def _read_content(
        self,
        metadata: YouTubeTranscriptMetadataRecord,
    ) -> TranscriptResponse:
        payload = await self._storage.read_transcript(
            YouTubeTranscriptStorageReadRequest(object_name=metadata.storage_object_name)
        )
        try:
            return TranscriptResponse.model_validate_json(payload)
        except ValueError as exc:
            raise YouTubeTranscriptStorageError("Stored transcript payload is invalid.") from exc

    async def _record_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        actor_type: OperationEventActorType,
        metadata_json: JsonObject | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=actor_type,
                source="transcript_cues.generate",
                job_id=job.id,
                job_attempt_id=attempt.id,
                subject_type=job.subject_type,
                subject_id=job.subject_id,
                external_key=job.external_key,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata_json or {},
            ),
        )


class ListTranscriptCuesUseCase:
    def __init__(
        self,
        *,
        transcripts: YouTubeTranscriptRepositoryPort,
        cues: TranscriptCueRepositoryPort,
    ) -> None:
        self._transcripts = transcripts
        self._cues = cues

    async def execute(self, transcript_id: int) -> TranscriptCueListResponse:
        await _ensure_transcript_exists(self._transcripts, transcript_id)
        records = await self._cues.list_cues(transcript_id)
        return TranscriptCueListResponse(
            transcriptId=transcript_id,
            cueCount=len(records),
            items=[_cue_response(record) for record in records],
        )


class GetTranscriptPromptCuesUseCase:
    def __init__(
        self,
        *,
        transcripts: YouTubeTranscriptRepositoryPort,
        cues: TranscriptCueRepositoryPort,
    ) -> None:
        self._transcripts = transcripts
        self._cues = cues

    async def execute(self, transcript_id: int) -> TranscriptPromptCuesResponse:
        await _ensure_transcript_exists(self._transcripts, transcript_id)
        records = await self._cues.list_cues(transcript_id)
        prompt_cues = [
            PromptCueResponse(
                cueId=record.cue_id,
                cueIndex=record.cue_index,
                text=record.text,
            )
            for record in records
        ]
        return TranscriptPromptCuesResponse(
            transcriptId=transcript_id,
            cueCount=len(records),
            promptText="\n".join(
                f"[{cue.cue_id}] {cue.text}" for cue in prompt_cues
            ),
            cues=prompt_cues,
        )


async def _ensure_transcript_exists(
    transcripts: YouTubeTranscriptRepositoryPort,
    transcript_id: int,
) -> None:
    if await transcripts.get_transcript_metadata(transcript_id) is None:
        raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")


def _cue_creates(
    transcript_id: int,
    content: TranscriptResponse,
    *,
    source_job_id: int,
    source_job_attempt_id: int,
) -> list[TranscriptCueCreate]:
    cues: list[TranscriptCueCreate] = []
    for segment_index, segment in enumerate(content.segments):
        cue_index = segment_index + 1
        start_ms = _seconds_to_ms(segment.start)
        duration_ms = max(0, _seconds_to_ms(segment.duration))
        end_ms = max(start_ms, start_ms + duration_ms)
        cues.append(
            TranscriptCueCreate(
                transcript_id=transcript_id,
                cue_id=_cue_id(transcript_id, cue_index),
                cue_index=cue_index,
                text=segment.text,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=duration_ms,
                source_segment_index=segment_index,
                source_job_id=source_job_id,
                source_job_attempt_id=source_job_attempt_id,
            )
        )
    return cues


def _cue_id(transcript_id: int, cue_index: int) -> str:
    return f"tr{transcript_id}-c{cue_index:06d}"


def _seconds_to_ms(value: float) -> int:
    return round(value * 1000)


def _cue_response(record: TranscriptCueRecord) -> TranscriptCueResponse:
    return TranscriptCueResponse(
        id=record.id,
        transcriptId=record.transcript_id,
        cueId=record.cue_id,
        cueIndex=record.cue_index,
        text=record.text,
        startMs=record.start_ms,
        endMs=record.end_ms,
        durationMs=record.duration_ms,
        sourceSegmentIndex=record.source_segment_index,
        sourceJobId=record.source_job_id,
        sourceJobAttemptId=record.source_job_attempt_id,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _input_json(metadata: YouTubeTranscriptMetadataRecord) -> JsonObject:
    return {
        "transcriptId": metadata.id,
        "youtubeVideoId": metadata.video_id,
        "responseSha256": metadata.response_sha256,
        "storageObjectName": metadata.storage_object_name,
        "cueVersion": TRANSCRIPT_CUE_GENERATE_VERSION,
    }


def _input_hash(input_json: JsonObject) -> str:
    return hashlib.sha256(
        json.dumps(input_json, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _output_json(
    metadata: YouTubeTranscriptMetadataRecord,
    summary: TranscriptCueSummaryRecord,
    *,
    job_id: int,
    attempt_id: int,
) -> JsonObject:
    return {
        "transcriptId": metadata.id,
        "youtubeVideoId": metadata.video_id,
        "cueCount": summary.cue_count,
        "firstCueId": summary.first_cue_id,
        "lastCueId": summary.last_cue_id,
        "jobId": job_id,
        "jobAttemptId": attempt_id,
    }


def _summary_from_records(
    transcript_id: int,
    records: list[TranscriptCueRecord],
    *,
    source_job_id: int,
) -> TranscriptCueSummaryRecord:
    return TranscriptCueSummaryRecord(
        transcript_id=transcript_id,
        cue_count=len(records),
        first_cue_id=records[0].cue_id if records else None,
        last_cue_id=records[-1].cue_id if records else None,
        source_job_id=source_job_id,
    )


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise YouTubeTranscriptStorageError(
            f"Pipeline job input is missing integer '{key}'."
        )
    return value
