from __future__ import annotations


class VideoDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class VideoAlreadyExists(VideoDomainError):
    """Raised when a YouTube video identity already belongs to another row."""


class VideoNotFound(VideoDomainError):
    """Raised when a local video row cannot be found."""


class VideoPersistenceError(VideoDomainError):
    """Raised when video persistence fails."""


class ChannelMissingYouTubeId(VideoDomainError):
    """Raised when a local channel cannot be used for YouTube video collection."""
