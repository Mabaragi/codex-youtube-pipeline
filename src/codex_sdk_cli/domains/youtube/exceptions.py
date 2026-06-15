from __future__ import annotations


class YouTubeDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidYouTubeVideo(YouTubeDomainError):
    """Raised when a request does not identify a supported YouTube video."""


class YouTubeTranscriptNotFound(YouTubeDomainError):
    """Raised when YouTube has no retrievable transcript for the video."""


class YouTubeTranscriptForbidden(YouTubeDomainError):
    """Raised when YouTube requires access the API cannot provide."""


class YouTubeTranscriptUpstreamError(YouTubeDomainError):
    """Raised when YouTube or the transcript provider blocks/fails the request."""


class YouTubeTranscriptStorageError(YouTubeDomainError):
    """Raised when transcript object storage is unavailable or misconfigured."""
