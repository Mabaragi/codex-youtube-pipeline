from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from typing_extensions import override

from codex_sdk_cli.domains.asr.exceptions import (
    AudioChunkFailed,
    AudioDownloadFailed,
    AudioProbeFailed,
    AudioToolNotConfigured,
)
from codex_sdk_cli.domains.asr.ports import AudioChunkerPort, YouTubeAudioDownloaderPort


class YtDlpAudioDownloader(YouTubeAudioDownloaderPort):
    def __init__(self, yt_dlp_bin: Path | None = None) -> None:
        self._yt_dlp_bin = _resolve_tool("yt-dlp", yt_dlp_bin)

    @override
    async def download_audio(self, *, video_id: str, output_dir: Path) -> Path:
        output_template = output_dir / "source.%(ext)s"
        before = {path.resolve() for path in output_dir.glob("source.*")}
        await _run_command(
            [
                str(self._yt_dlp_bin),
                "--no-playlist",
                "--no-progress",
                "-f",
                "ba/bestaudio",
                "-o",
                str(output_template),
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            error_cls=AudioDownloadFailed,
            error_message="yt-dlp audio download failed.",
        )
        candidates = sorted(
            path
            for path in output_dir.glob("source.*")
            if path.resolve() not in before and path.is_file()
        )
        if not candidates:
            candidates = sorted(path for path in output_dir.glob("source.*") if path.is_file())
        if not candidates:
            raise AudioDownloadFailed("yt-dlp did not produce an audio file.")
        return candidates[0]


class FfmpegAudioChunker(AudioChunkerPort):
    def __init__(
        self,
        *,
        ffmpeg_bin: Path | None = None,
        ffprobe_bin: Path | None = None,
    ) -> None:
        self._ffmpeg_bin = _resolve_tool("ffmpeg", ffmpeg_bin)
        self._ffprobe_bin = _resolve_tool("ffprobe", ffprobe_bin)

    @override
    async def probe_duration_seconds(self, audio_path: Path) -> float:
        output = await _run_command(
            [
                str(self._ffprobe_bin),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            error_cls=AudioProbeFailed,
            error_message="ffprobe duration probe failed.",
        )
        try:
            duration = float(output.strip())
        except ValueError as exc:
            raise AudioProbeFailed("ffprobe returned an invalid duration.") from exc
        if duration <= 0:
            raise AudioProbeFailed("Audio duration must be greater than zero.")
        return duration

    @override
    async def create_chunk(
        self,
        *,
        audio_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        if duration_seconds <= 0:
            raise AudioChunkFailed("Audio chunk duration must be greater than zero.")
        await _run_command(
            [
                str(self._ffmpeg_bin),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{start_seconds:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-vn",
                str(output_path),
            ],
            error_cls=AudioChunkFailed,
            error_message="ffmpeg audio chunk creation failed.",
        )
        if not output_path.exists():
            raise AudioChunkFailed("ffmpeg did not produce an audio chunk.")
        return output_path


def _resolve_tool(name: str, explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        if not explicit_path.exists():
            raise AudioToolNotConfigured(f"{name} was not found: {explicit_path}")
        return explicit_path

    found = shutil.which(name)
    if found is None:
        raise AudioToolNotConfigured(f"{name} executable was not found on PATH.")
    return Path(found)


async def _run_command(
    args: list[str],
    *,
    error_cls: type[Exception],
    error_message: str,
) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        message = f"{error_message} {detail}".strip()
        raise error_cls(message)
    return stdout.decode("utf-8", errors="replace")
