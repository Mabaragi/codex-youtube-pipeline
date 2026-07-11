from __future__ import annotations


class MicroEventDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MicroEventExtractionNotFound(MicroEventDomainError):
    """Raised when a micro-event extraction cannot be found."""


class MicroEventExtractionPreconditionFailed(MicroEventDomainError):
    """Raised when cue rows or upstream tasks required for extraction are missing."""


class MicroEventExtractionPersistenceError(MicroEventDomainError):
    """Raised when micro-event extraction persistence fails."""


class MicroEventExtractionOutputInvalid(MicroEventDomainError):
    """Raised when the extractor returns invalid JSON or invalid cue references."""
