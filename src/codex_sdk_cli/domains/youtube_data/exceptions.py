from __future__ import annotations


class YouTubeDataDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidYouTubeChannelHandle(YouTubeDataDomainError):
    """Raised when a YouTube channel handle is empty or malformed."""


class YouTubeDataConfigurationError(YouTubeDataDomainError):
    """Raised when YouTube Data API configuration is missing."""


class YouTubeDataChannelNotFound(YouTubeDataDomainError):
    """Raised when YouTube Data API finds no channel for a handle."""


class YouTubeDataChannelResolutionError(YouTubeDataDomainError):
    """Raised when a resolved channel row is missing required resolution data."""


class YouTubeDataUpstreamError(YouTubeDataDomainError):
    """Raised when YouTube Data API fails or returns an unexpected response."""
