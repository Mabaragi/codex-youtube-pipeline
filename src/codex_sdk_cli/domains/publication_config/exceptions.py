from __future__ import annotations


class PublishConfigurationDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PublishConfigurationNotFound(PublishConfigurationDomainError):
    """Raised when a publication configuration resource does not exist."""


class PublishConfigurationConflict(PublishConfigurationDomainError):
    """Raised when a publication configuration invariant would be violated."""


class PublishConfigurationInvalidConnection(PublishConfigurationDomainError):
    """Raised when a destination does not reference a compatible registry entry."""


class PublishConfigurationPersistenceError(PublishConfigurationDomainError):
    """Raised when publication configuration persistence fails."""
