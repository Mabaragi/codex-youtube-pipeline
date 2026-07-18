from __future__ import annotations


class PublicationError(Exception):
    """Base error for publication infrastructure boundaries."""


class PublicationConnectionConfigurationError(PublicationError):
    """A private publication connection registry is invalid or unavailable."""


class PublicationConnectionNotFoundError(PublicationConnectionConfigurationError):
    """A requested connection reference does not exist."""


class PublicationConnectionTypeError(PublicationConnectionConfigurationError):
    """A connection reference was resolved through the wrong adapter family."""


class PublicationObjectStoreError(PublicationError):
    """An object store operation failed."""


class PublicationCatalogPublishError(PublicationError):
    """A catalog destination could not atomically accept a video projection."""
