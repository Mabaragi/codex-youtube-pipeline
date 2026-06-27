from __future__ import annotations


class VideoTaskDomainError(Exception):
    """Base class for video task domain errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class VideoTaskNotFound(VideoTaskDomainError):
    """Raised when a video task cannot be found."""


class VideoTaskRetryNotAllowed(VideoTaskDomainError):
    """Raised when a video task cannot be retried in its current state."""


class VideoTaskCancelNotAllowed(VideoTaskDomainError):
    """Raised when a video task cannot be canceled in its current state."""


class TranscriptCollectAlreadyRunning(VideoTaskDomainError):
    """Raised when a transcript collection batch is already active."""


class VideoTaskPersistenceError(VideoTaskDomainError):
    """Raised when video task persistence fails."""
