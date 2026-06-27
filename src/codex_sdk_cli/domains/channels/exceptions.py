from __future__ import annotations


class ChannelDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ChannelNotFound(ChannelDomainError):
    """Raised when a channel cannot be found."""


class ChannelAlreadyExists(ChannelDomainError):
    """Raised when a YouTube channel identity already belongs to another row."""


class ChannelPersistenceError(ChannelDomainError):
    """Raised when channel persistence fails."""
