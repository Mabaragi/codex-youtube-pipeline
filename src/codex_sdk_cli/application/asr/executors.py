from __future__ import annotations

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)
from codex_sdk_cli.domains.asr.exceptions import AudioDownloadFailed

from .errors import AsrAudioUnavailable
from .ports import AsrTranscriberPort

ASR_TRANSCRIBE_TASK = "asr_transcribe"
ASR_TRANSCRIBE_VERSION = "v1"


class AsrTranscriptionExecutor(WorkExecutorPort):
    def __init__(self, transcriber: AsrTranscriberPort) -> None:
        self._transcriber = transcriber

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        try:
            result = await self._transcriber.transcribe(
                work_item_id=context.work_item.id,
                youtube_video_id=_required_str(values, "youtubeVideoId"),
                model=_required_str(values, "model"),
                language=_required_str(values, "language"),
                device=_required_str(values, "device"),
                compute_type=_required_str(values, "computeType"),
                chunk_minutes=_required_int(values, "chunkMinutes"),
                overlap_seconds=_required_int(values, "overlapSeconds"),
                beam_size=_required_int(values, "beamSize"),
                vad_filter=_required_bool(values, "vadFilter"),
            )
        except AudioDownloadFailed as exc:
            if _permanently_unavailable(str(exc)):
                raise AsrAudioUnavailable() from exc
            raise
        return WorkExecutionResult(
            output_json={
                "videoId": _required_int(values, "videoId"),
                "youtubeVideoId": _required_str(values, "youtubeVideoId"),
                "transcriptId": result.transcript_id,
                "segmentCount": result.segment_count,
                "responseSha256": result.response_sha256,
                "storageObjectName": result.storage_object_name,
                "device": result.device,
                "computeType": result.compute_type,
                "durationSeconds": result.duration_seconds,
                "elapsedSeconds": result.elapsed_seconds,
            },
            output_transcript_id=result.transcript_id,
        )


def _required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"{key} must be a non-empty string.")


def _required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer.")


def _required_bool(values: dict[str, object], key: str) -> bool:
    value = values.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be a boolean.")


def _permanently_unavailable(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "video unavailable",
            "removed by the uploader",
            "private video",
            "this video is not available",
        )
    )
