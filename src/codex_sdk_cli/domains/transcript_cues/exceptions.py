from __future__ import annotations


class TranscriptCueDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TranscriptCuePersistenceError(TranscriptCueDomainError):
    """Raised when transcript cue rows cannot be persisted."""
