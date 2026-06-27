from __future__ import annotations


class TimelineDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TimelineCompositionNotFound(TimelineDomainError):
    """Raised when a timeline composition cannot be found."""


class TimelineCompositionPreconditionFailed(TimelineDomainError):
    """Raised when required upstream data is missing."""


class TimelineCompositionOutputInvalid(TimelineDomainError):
    """Raised when the composer returns unusable output."""


class TimelineCompositionPersistenceError(TimelineDomainError):
    """Raised when timeline persistence fails."""
