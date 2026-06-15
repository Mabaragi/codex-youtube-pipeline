from __future__ import annotations


class StreamerDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StreamerNotFound(StreamerDomainError):
    """Raised when a streamer cannot be found."""


class ChannelNotFound(StreamerDomainError):
    """Raised when a channel cannot be found."""


class StreamerHasChannels(StreamerDomainError):
    """Raised when deleting a streamer that still owns channels."""


class StreamerPersistenceError(StreamerDomainError):
    """Raised when streamer/channel persistence fails."""

