from __future__ import annotations


class YouTubeTranscriptDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidYouTubeVideo(YouTubeTranscriptDomainError):
    """Raised when a request does not identify a supported YouTube video."""


class YouTubeTranscriptNotFound(YouTubeTranscriptDomainError):
    """Raised when YouTube has no retrievable transcript for the video."""


class YouTubeTranscriptForbidden(YouTubeTranscriptDomainError):
    """Raised when YouTube requires access the API cannot provide."""


class YouTubeTranscriptUpstreamError(YouTubeTranscriptDomainError):
    """Raised when YouTube or the transcript provider blocks/fails the request."""


class YouTubeTranscriptStorageError(YouTubeTranscriptDomainError):
    """Raised when transcript object storage is unavailable or misconfigured."""


class YouTubeTranscriptPersistenceError(YouTubeTranscriptDomainError):
    """Raised when transcript metadata cannot be persisted."""


class YouTubeTranscriptMetadataNotFound(YouTubeTranscriptDomainError):
    """Raised when stored transcript metadata cannot be found."""
