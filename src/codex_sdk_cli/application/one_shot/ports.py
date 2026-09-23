from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from codex_sdk_cli.domains.codex.choices import (
    DEFAULT_MICRO_EVENT_MODEL,
    DEFAULT_MICRO_EVENT_REASONING_EFFORT,
    DEFAULT_TIMELINE_MODEL,
    DEFAULT_TIMELINE_REASONING_EFFORT,
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.prompts.constants import PromptKey
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptFetchResult
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptResponse


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    duration: str
    duration_seconds: int
    thumbnail_url: str | None
    channel_id: str
    channel_name: str
    is_embeddable: bool


@dataclass(frozen=True, slots=True)
class RunOptions:
    languages: tuple[str, ...] = ("ko", "en")
    transcript_mode: str = "auto"
    streamer_name: str | None = None
    window_minutes: int = 30
    overlap_minutes: int = 5
    micro_model: CodexModelChoice = DEFAULT_MICRO_EVENT_MODEL
    micro_reasoning_effort: ReasoningEffortChoice = DEFAULT_MICRO_EVENT_REASONING_EFFORT
    timeline_model: CodexModelChoice = DEFAULT_TIMELINE_MODEL
    timeline_reasoning_effort: ReasoningEffortChoice = DEFAULT_TIMELINE_REASONING_EFFORT
    asr_model: str = "turbo"
    asr_language: str = "ko"
    asr_device: str = "cuda"
    asr_compute_type: str = "auto"
    asr_chunk_minutes: int = 15
    asr_overlap_seconds: int = 3
    asr_beam_size: int = 5
    asr_vad_filter: bool = True
    micro_window_concurrency: int = 1


class VideoLookupPort(Protocol):
    async def lookup(self, youtube_video_id: str) -> VideoMetadata: ...


class TranscriptLookupPort(Protocol):
    async def fetch(
        self, youtube_video_id: str, languages: tuple[str, ...]
    ) -> YouTubeTranscriptFetchResult: ...


class ActivePromptSourcePort(Protocol):
    async def resolve(self) -> dict[PromptKey, ResolvedPrompt]: ...


class LocalAsrPort(Protocol):
    async def transcribe(
        self, *, youtube_video_id: str, run_dir: Path, options: RunOptions
    ) -> TranscriptResponse: ...


class LocalGenerationPort(Protocol):
    async def generate_micro(self, *, run_dir: Path, resume: bool) -> dict[str, object]: ...

    async def generate_timeline(
        self, *, run_dir: Path, micro: dict[str, object]
    ) -> dict[str, object]: ...


class OneShotStorePort(Protocol):
    def create_plan(
        self,
        *,
        output_root: Path,
        video_id: str,
        plan_hash: str,
        plan: dict[str, object],
        caption: YouTubeTranscriptFetchResult | None,
    ) -> Path: ...

    def load_plan(self, plan_path: Path) -> dict[str, Any]: ...

    def load_manifest(self, run_dir: Path) -> dict[str, Any]: ...

    def save_manifest(self, run_dir: Path, manifest: dict[str, object]) -> None: ...

    def lock(self, run_dir: Path) -> AbstractContextManager[object]: ...

    def transcript_exists(self, run_dir: Path) -> bool: ...

    def micro_exists(self, run_dir: Path) -> bool: ...

    def load_micro(self, run_dir: Path) -> dict[str, object]: ...

    def save_micro(self, run_dir: Path, result: dict[str, object]) -> None: ...

    def save_timeline(self, run_dir: Path, result: dict[str, object]) -> str: ...

    def snapshot_artifact_hashes(self, run_dir: Path) -> dict[str, str]: ...

    def status(self, run_dir: Path) -> dict[str, object]: ...

    def verify(self, run_dir: Path) -> dict[str, object]: ...
