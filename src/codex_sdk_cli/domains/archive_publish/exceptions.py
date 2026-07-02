from __future__ import annotations


class ArchivePublishDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ArchivePublishConfigurationError(ArchivePublishDomainError):
    """Archive publish storage or public URL configuration is missing."""


class ArchivePublishPersistenceError(ArchivePublishDomainError):
    """Archive publish metadata persistence failed."""


class ArchivePublishStorageError(ArchivePublishDomainError):
    """Archive publish object storage operation failed."""


class ArchivePublishPreconditionFailed(ArchivePublishDomainError):
    """A video is not ready to be published."""


class ArchivePublishArtifactInvalid(ArchivePublishDomainError):
    """A publishable archive artifact cannot be built safely."""


class ArchivePublishCatalogSyncError(ArchivePublishDomainError):
    """Archive publish public catalog synchronization failed."""
