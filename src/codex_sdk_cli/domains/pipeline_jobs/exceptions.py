from __future__ import annotations


class PipelineJobDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PipelineJobPersistenceError(PipelineJobDomainError):
    """Raised when pipeline job persistence fails."""


class PipelineJobNotFound(PipelineJobDomainError):
    """Raised when a pipeline job does not exist."""


class PipelineJobRetryNotAllowed(PipelineJobDomainError):
    """Raised when a pipeline job cannot be retried."""
