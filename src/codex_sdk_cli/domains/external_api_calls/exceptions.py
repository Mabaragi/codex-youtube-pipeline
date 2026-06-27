from __future__ import annotations


class ExternalApiCallDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ExternalApiCallConfigurationError(ExternalApiCallDomainError):
    """Raised when raw API call storage configuration is missing."""


class ExternalApiCallStorageError(ExternalApiCallDomainError):
    """Raised when raw API response object storage fails."""


class ExternalApiCallPersistenceError(ExternalApiCallDomainError):
    """Raised when raw API call metadata persistence fails."""
