from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from codex_sdk_cli.application.one_shot.ports import RunOptions
from codex_sdk_cli.domains.asr.use_cases import (
    FasterWhisperTranscribeRequest,
    TranscribeYouTubeAudioUseCase,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptResponse
from codex_sdk_cli.infra.asr.faster_whisper import FasterWhisperTranscriber
from codex_sdk_cli.infra.asr.local_audio import FfmpegAudioChunker, YtDlpAudioDownloader
from codex_sdk_cli.settings import CliSettings

from .files import (
    FileAsrCheckpoints,
    FileCueRepository,
    FileTranscriptRepository,
    FileTranscriptStorage,
)


class LocalAsrRunner:
    def __init__(self, settings: CliSettings) -> None:
        self._settings = settings

    async def transcribe(
        self, *, youtube_video_id: str, run_dir: Path, options: RunOptions
    ) -> TranscriptResponse:
        use_case = TranscribeYouTubeAudioUseCase(
            downloader=YtDlpAudioDownloader(self._settings.ytdlp_bin),
            chunker=FfmpegAudioChunker(
                ffmpeg_bin=self._settings.ffmpeg_bin,
                ffprobe_bin=self._settings.ffprobe_bin,
            ),
            transcriber=FasterWhisperTranscriber(),
            storage=FileTranscriptStorage(run_dir),
            transcripts=cast(Any, FileTranscriptRepository(run_dir)),
            cues=cast(Any, FileCueRepository(run_dir)),
            checkpoints=FileAsrCheckpoints(run_dir),
            storage_prefix="one-shot",
        )
        result = await use_case.execute(
            FasterWhisperTranscribeRequest(
                video=youtube_video_id,
                model_size=options.asr_model,
                language=options.asr_language,
                device=options.asr_device,
                compute_type=options.asr_compute_type,
                chunk_minutes=options.asr_chunk_minutes,
                overlap_seconds=options.asr_overlap_seconds,
                beam_size=options.asr_beam_size,
                vad_filter=options.asr_vad_filter,
            )
        )
        return result.transcript
