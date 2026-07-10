from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from codex_sdk_cli.domains.asr.exceptions import AudioTranscriptionOutputInvalid
from codex_sdk_cli.domains.asr.ports import (
    AudioChunk,
    AudioChunkerPort,
    AudioTranscriberPort,
    AudioTranscriptionRequest,
    AudioTranscriptionSegment,
    YouTubeAudioDownloaderPort,
)
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueCreate,
    TranscriptCueRepositoryPort,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageSaveRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptResponse,
    TranscriptSegmentResponse,
    TranscriptStorageResponse,
)
from codex_sdk_cli.domains.youtube_transcripts.use_cases import (
    build_transcript_object_name,
    normalize_video_id,
)

DEFAULT_ASR_STORAGE_SUBPREFIX = "asr/faster-whisper"


@dataclass(frozen=True, slots=True)
class FasterWhisperTranscribeRequest:
    video: str
    model_size: str = "turbo"
    language: str = "ko"
    device: str = "auto"
    compute_type: str = "auto"
    chunk_minutes: int = 15
    overlap_seconds: int = 3
    beam_size: int = 5
    vad_filter: bool = True
    keep_temp: bool = False


@dataclass(frozen=True, slots=True)
class FasterWhisperTranscribeResult:
    youtube_video_id: str
    transcript_id: int
    segment_count: int
    cue_count: int
    storage_object_name: str
    model_size: str
    device: str
    compute_type: str
    duration_seconds: float
    elapsed_seconds: float
    transcript: TranscriptResponse
    temp_dir: Path | None = None

    def summary_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "youtubeVideoId": self.youtube_video_id,
            "transcriptId": self.transcript_id,
            "segmentCount": self.segment_count,
            "cueCount": self.cue_count,
            "storageObjectName": self.storage_object_name,
            "modelSize": self.model_size,
            "device": self.device,
            "computeType": self.compute_type,
            "durationSeconds": self.duration_seconds,
            "elapsedSeconds": self.elapsed_seconds,
        }
        if self.temp_dir is not None:
            payload["tempDir"] = str(self.temp_dir)
        return payload


class TranscribeYouTubeAudioUseCase:
    def __init__(
        self,
        *,
        downloader: YouTubeAudioDownloaderPort,
        chunker: AudioChunkerPort,
        transcriber: AudioTranscriberPort,
        storage: YouTubeTranscriptStoragePort,
        transcripts: YouTubeTranscriptRepositoryPort,
        cues: TranscriptCueRepositoryPort,
        storage_prefix: str = "youtube/transcripts",
        date_provider: Callable[[], date] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._downloader = downloader
        self._chunker = chunker
        self._transcriber = transcriber
        self._storage = storage
        self._transcripts = transcripts
        self._cues = cues
        self._storage_prefix = storage_prefix
        self._date_provider = date_provider or _utc_today
        self._monotonic = monotonic or time.monotonic

    async def execute(
        self,
        request: FasterWhisperTranscribeRequest,
    ) -> FasterWhisperTranscribeResult:
        started_at = self._monotonic()
        video_id = normalize_video_id(request.video)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"codex-asr-{video_id}-"))
        try:
            result = await self._execute_in_temp_dir(video_id, request, temp_dir, started_at)
        finally:
            if not request.keep_temp:
                shutil.rmtree(temp_dir, ignore_errors=True)
        return result

    async def _execute_in_temp_dir(
        self,
        video_id: str,
        request: FasterWhisperTranscribeRequest,
        temp_dir: Path,
        started_at: float,
    ) -> FasterWhisperTranscribeResult:
        audio_path = await self._downloader.download_audio(
            video_id=video_id,
            output_dir=temp_dir,
        )
        duration_seconds = await self._chunker.probe_duration_seconds(audio_path)
        chunks = await self._create_chunks(audio_path, temp_dir, request, duration_seconds)
        segments, resolved_device, resolved_compute_type = await self._transcribe_chunks(
            chunks,
            request,
        )
        if not segments:
            raise AudioTranscriptionOutputInvalid("ASR output did not contain transcript text.")

        transcript = await self._store_transcript(
            video_id=video_id,
            request=request,
            segments=segments,
        )
        cue_records = await self._cues.replace_cues(
            transcript.metadata_id,
            _cue_creates(transcript.metadata_id, transcript.response.segments),
        )
        return FasterWhisperTranscribeResult(
            youtube_video_id=video_id,
            transcript_id=transcript.metadata_id,
            segment_count=len(transcript.response.segments),
            cue_count=len(cue_records),
            storage_object_name=transcript.response.storage.object_name,
            model_size=request.model_size,
            device=resolved_device,
            compute_type=resolved_compute_type,
            duration_seconds=duration_seconds,
            elapsed_seconds=round(self._monotonic() - started_at, 3),
            transcript=transcript.response,
            temp_dir=temp_dir if request.keep_temp else None,
        )

    async def _create_chunks(
        self,
        audio_path: Path,
        temp_dir: Path,
        request: FasterWhisperTranscribeRequest,
        duration_seconds: float,
    ) -> list[AudioChunk]:
        chunk_seconds = request.chunk_minutes * 60
        overlap_seconds = max(0, request.overlap_seconds)
        chunks: list[AudioChunk] = []
        body_start = 0.0
        index = 0
        while body_start < duration_seconds:
            body_end = min(duration_seconds, body_start + chunk_seconds)
            media_start = max(0.0, body_start - overlap_seconds)
            media_end = min(duration_seconds, body_end + overlap_seconds)
            output_path = temp_dir / f"chunk-{index:05d}.wav"
            await self._chunker.create_chunk(
                audio_path=audio_path,
                output_path=output_path,
                start_seconds=media_start,
                duration_seconds=max(0.0, media_end - media_start),
            )
            chunks.append(
                AudioChunk(
                    index=index,
                    path=output_path,
                    media_start_seconds=media_start,
                    body_start_seconds=body_start,
                    body_end_seconds=body_end,
                )
            )
            index += 1
            body_start += chunk_seconds
        return chunks

    async def _transcribe_chunks(
        self,
        chunks: list[AudioChunk],
        request: FasterWhisperTranscribeRequest,
    ) -> tuple[list[TranscriptSegmentResponse], str, str]:
        segments: list[TranscriptSegmentResponse] = []
        resolved_device = request.device
        resolved_compute_type = request.compute_type
        for chunk in chunks:
            result = await self._transcriber.transcribe(
                AudioTranscriptionRequest(
                    audio_path=chunk.path,
                    language=request.language,
                    model_size=request.model_size,
                    device=request.device,
                    compute_type=request.compute_type,
                    beam_size=request.beam_size,
                    vad_filter=request.vad_filter,
                )
            )
            resolved_device = result.device
            resolved_compute_type = result.compute_type
            for segment in _mergeable_segments(chunk, result.segments):
                text = segment.text.strip()
                if not text:
                    continue
                start = max(0.0, segment.start_seconds)
                end = max(start, segment.end_seconds)
                segments.append(
                    TranscriptSegmentResponse(
                        text=text,
                        start=round(start, 3),
                        duration=round(max(0.0, end - start), 3),
                    )
                )
        segments.sort(key=lambda segment: (segment.start, segment.duration, segment.text))
        return segments, resolved_device, resolved_compute_type

    async def _store_transcript(
        self,
        *,
        video_id: str,
        request: FasterWhisperTranscribeRequest,
        segments: list[TranscriptSegmentResponse],
    ) -> _StoredAsrTranscript:
        requested_languages = _requested_languages(request.language, request.model_size)
        object_name = build_transcript_object_name(
            prefix=_asr_storage_prefix(self._storage_prefix, request.model_size),
            storage_date=self._date_provider(),
            video_id=video_id,
            languages=requested_languages,
            preserve_formatting=False,
        )
        location = self._storage.location_for(object_name)
        response = TranscriptResponse(
            videoId=video_id,
            language=_language_label(request.language),
            languageCode=request.language,
            isGenerated=True,
            text="\n".join(segment.text for segment in segments),
            segments=segments,
            storage=TranscriptStorageResponse(
                bucket=location.bucket,
                objectName=location.object_name,
                uri=location.uri,
            ),
        )
        response_payload = response.model_dump_json(by_alias=True).encode("utf-8")
        await self._storage.save_transcript(
            YouTubeTranscriptStorageSaveRequest(
                object_name=object_name,
                payload=response_payload,
            )
        )
        metadata = await self._transcripts.save_transcript_record(
            YouTubeTranscriptRecord(
                video_id=video_id,
                language=response.language,
                language_code=response.language_code,
                is_generated=response.is_generated,
                requested_languages=requested_languages,
                preserve_formatting=False,
                storage_bucket=location.bucket,
                storage_object_name=location.object_name,
                storage_uri=location.uri,
                response_sha256=hashlib.sha256(response_payload).hexdigest(),
                segment_count=len(response.segments),
                text_length=len(response.text),
            )
        )
        return _StoredAsrTranscript(response=response, metadata_id=metadata.id)


@dataclass(frozen=True, slots=True)
class _StoredAsrTranscript:
    response: TranscriptResponse
    metadata_id: int


def _mergeable_segments(
    chunk: AudioChunk,
    segments: tuple[AudioTranscriptionSegment, ...],
) -> list[AudioTranscriptionSegment]:
    kept: list[AudioTranscriptionSegment] = []
    for segment in segments:
        global_start = chunk.media_start_seconds + segment.start_seconds
        global_end = chunk.media_start_seconds + segment.end_seconds
        if global_start < chunk.body_start_seconds:
            continue
        if global_start >= chunk.body_end_seconds:
            continue
        kept.append(
            AudioTranscriptionSegment(
                text=segment.text,
                start_seconds=global_start,
                end_seconds=global_end,
            )
        )
    return kept


def _cue_creates(
    transcript_id: int,
    segments: list[TranscriptSegmentResponse],
) -> list[TranscriptCueCreate]:
    cues: list[TranscriptCueCreate] = []
    for segment_index, segment in enumerate(segments):
        cue_index = segment_index + 1
        start_ms = round(segment.start * 1000)
        duration_ms = max(0, round(segment.duration * 1000))
        cues.append(
            TranscriptCueCreate(
                transcript_id=transcript_id,
                cue_id=f"tr{transcript_id}-c{cue_index:06d}",
                cue_index=cue_index,
                text=segment.text,
                start_ms=start_ms,
                end_ms=start_ms + duration_ms,
                duration_ms=duration_ms,
                source_segment_index=segment_index,
                source_job_id=None,
                source_job_attempt_id=None,
            )
        )
    return cues


def _requested_languages(language: str, model_size: str) -> tuple[str, str]:
    return (language, f"asr:faster-whisper-{model_size}")


def _asr_storage_prefix(storage_prefix: str, model_size: str) -> str:
    return f"{storage_prefix.strip('/')}/{DEFAULT_ASR_STORAGE_SUBPREFIX}/{model_size}"


def _language_label(language: str) -> str:
    return "Korean" if language == "ko" else language


def _utc_today() -> date:
    return datetime.now(UTC).date()
