from __future__ import annotations

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind


class TranscriptPersistenceUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="transcript.persistence_failed",
            message="Transcript metadata persistence failed.",
            kind=ErrorKind.UNAVAILABLE,
        )
