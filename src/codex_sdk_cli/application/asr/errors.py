from __future__ import annotations

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind


class AsrAudioUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="asr.audio_unavailable",
            message="Video audio is unavailable for transcription.",
            kind=ErrorKind.UPSTREAM,
        )
