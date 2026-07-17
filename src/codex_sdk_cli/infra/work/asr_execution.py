from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.asr.ports import AsrTranscriberPort, AsrTranscriptResult
from codex_sdk_cli.domains.asr.use_cases import (
    FasterWhisperTranscribeRequest,
    TranscribeYouTubeAudioUseCase,
)
from codex_sdk_cli.infra.asr.checkpoints import SqlAlchemyAsrChunkCheckpointRepository
from codex_sdk_cli.infra.asr.faster_whisper import FasterWhisperTranscriber
from codex_sdk_cli.infra.asr.local_audio import FfmpegAudioChunker, YtDlpAudioDownloader
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings


class StoredAsrTranscriber(AsrTranscriberPort):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: CliSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._transcriber = FasterWhisperTranscriber()

    @override
    async def transcribe(
        self,
        *,
        work_item_id: int,
        youtube_video_id: str,
        model: str,
        language: str,
        device: str,
        compute_type: str,
        chunk_minutes: int,
        overlap_seconds: int,
        beam_size: int,
        vad_filter: bool,
    ) -> AsrTranscriptResult:
        async with self._session_factory() as session:
            result = await TranscribeYouTubeAudioUseCase(
                downloader=YtDlpAudioDownloader(self._settings.ytdlp_bin),
                chunker=FfmpegAudioChunker(
                    ffmpeg_bin=self._settings.ffmpeg_bin,
                    ffprobe_bin=self._settings.ffprobe_bin,
                ),
                transcriber=self._transcriber,
                storage=MinioTranscriptStorage.from_settings(self._settings),
                transcripts=SqlAlchemyYouTubeTranscriptRepository(session),
                cues=SqlAlchemyTranscriptCueRepository(session),
                checkpoints=SqlAlchemyAsrChunkCheckpointRepository(
                    self._session_factory,
                    work_item_id=work_item_id,
                ),
                storage_prefix=self._settings.transcript_minio_prefix,
            ).execute(
                FasterWhisperTranscribeRequest(
                    video=youtube_video_id,
                    model_size=model,
                    language=language,
                    device=device,
                    compute_type=compute_type,
                    chunk_minutes=chunk_minutes,
                    overlap_seconds=overlap_seconds,
                    beam_size=beam_size,
                    vad_filter=vad_filter,
                    generate_cues=False,
                )
            )
        payload = result.transcript.model_dump_json(by_alias=True).encode("utf-8")
        return AsrTranscriptResult(
            transcript_id=result.transcript_id,
            segment_count=result.segment_count,
            response_sha256=hashlib.sha256(payload).hexdigest(),
            storage_object_name=result.storage_object_name,
            device=result.device,
            compute_type=result.compute_type,
            duration_seconds=result.duration_seconds,
            elapsed_seconds=result.elapsed_seconds,
        )
