from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AudioChunk:
    index: int
    path: Path
    media_start_seconds: float
    body_start_seconds: float
    body_end_seconds: float


@dataclass(frozen=True, slots=True)
class AudioTranscriptionSegment:
    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class AudioTranscriptionRequest:
    audio_path: Path
    language: str
    model_size: str
    device: str
    compute_type: str
    beam_size: int
    vad_filter: bool


@dataclass(frozen=True, slots=True)
class AudioTranscriptionResult:
    segments: tuple[AudioTranscriptionSegment, ...]
    device: str
    compute_type: str


@dataclass(frozen=True, slots=True)
class AudioChunkCheckpoint:
    chunk_index: int
    segments: tuple[AudioTranscriptionSegment, ...]
    device: str
    compute_type: str


class YouTubeAudioDownloaderPort(Protocol):
    async def download_audio(self, *, video_id: str, output_dir: Path) -> Path:
        """Download best available YouTube audio and return the local file path."""


class AudioChunkerPort(Protocol):
    async def probe_duration_seconds(self, audio_path: Path) -> float:
        """Return media duration in seconds."""

    async def create_chunk(
        self,
        *,
        audio_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        """Create one normalized audio chunk."""


class AudioTranscriberPort(Protocol):
    async def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        """Transcribe one audio chunk."""


class AudioChunkCheckpointPort(Protocol):
    async def load(self, chunk_index: int) -> AudioChunkCheckpoint | None: ...

    async def save(self, checkpoint: AudioChunkCheckpoint) -> None: ...
