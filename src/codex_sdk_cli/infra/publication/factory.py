from __future__ import annotations

from codex_sdk_cli.domains.publication.exceptions import PublicationConnectionTypeError
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogPublisherPort,
    PublicationCatalogReconcilerPort,
    PublicationCatalogVerifierPort,
    PublicationObjectStorePort,
)
from codex_sdk_cli.infra.publication.catalog_publishers import (
    HttpPublicationCatalogPublisher,
    SqlPublicationCatalogPublisher,
)
from codex_sdk_cli.infra.publication.connections import (
    HttpCatalogConnection,
    PublicationConnectionRegistry,
    PublicationConnectionSummary,
    S3CompatibleObjectConnection,
    SqlCatalogConnection,
    load_publication_connection_registry,
)
from codex_sdk_cli.infra.publication.object_store import (
    S3CompatiblePublicationObjectStore,
)
from codex_sdk_cli.settings import CliSettings


class PublicationConnectionFactory:
    def __init__(self, registry: PublicationConnectionRegistry) -> None:
        self._registry = registry
        self._object_stores: dict[str, PublicationObjectStorePort] = {}
        self._catalog_publishers: dict[str, PublicationCatalogPublisherPort] = {}

    @classmethod
    def from_settings(cls, settings: CliSettings) -> PublicationConnectionFactory:
        return cls(load_publication_connection_registry(settings.publish_connections_file))

    def safe_summaries(self) -> tuple[PublicationConnectionSummary, ...]:
        return self._registry.safe_summaries()

    def object_store(self, connection_ref: str) -> PublicationObjectStorePort:
        cached = self._object_stores.get(connection_ref)
        if cached is not None:
            return cached
        connection = self._registry.connection(connection_ref)
        if not isinstance(connection, S3CompatibleObjectConnection):
            raise PublicationConnectionTypeError(
                f"Publication connection '{connection_ref}' is not an object store."
            )
        adapter = S3CompatiblePublicationObjectStore.from_values(
            endpoint=connection.endpoint,
            access_key=connection.access_key.get_secret_value(),
            secret_key=connection.secret_key.get_secret_value(),
            bucket=connection.bucket,
            public_base_url=connection.public_base_url,
            secure=connection.secure,
            region=connection.region,
        )
        self._object_stores[connection_ref] = adapter
        return adapter

    def catalog_publisher(self, connection_ref: str) -> PublicationCatalogPublisherPort:
        cached = self._catalog_publishers.get(connection_ref)
        if cached is not None:
            return cached
        connection = self._registry.connection(connection_ref)
        adapter: PublicationCatalogPublisherPort
        if isinstance(connection, HttpCatalogConnection):
            adapter = HttpPublicationCatalogPublisher(
                url=connection.url,
                token=(
                    connection.token.get_secret_value() if connection.token is not None else None
                ),
                timeout_seconds=connection.timeout_seconds,
            )
        elif isinstance(connection, SqlCatalogConnection):
            adapter = SqlPublicationCatalogPublisher.from_database_url(
                connection.database_url.get_secret_value(),
                echo=connection.echo,
            )
        else:
            raise PublicationConnectionTypeError(
                f"Publication connection '{connection_ref}' is not a catalog destination."
            )
        self._catalog_publishers[connection_ref] = adapter
        return adapter

    def sql_catalog_database_url(self, connection_ref: str) -> str:
        connection = self._registry.connection(connection_ref)
        if not isinstance(connection, SqlCatalogConnection):
            raise PublicationConnectionTypeError(
                f"Publication connection '{connection_ref}' is not a SQL catalog."
            )
        return connection.database_url.get_secret_value()

    def catalog_verifier(self, connection_ref: str) -> PublicationCatalogVerifierPort:
        connection = self._registry.connection(connection_ref)
        if not isinstance(connection, SqlCatalogConnection):
            raise PublicationConnectionTypeError(
                f"Publication connection '{connection_ref}' is not a SQL catalog."
            )
        publisher = self.catalog_publisher(connection_ref)
        if not isinstance(publisher, SqlPublicationCatalogPublisher):
            raise PublicationConnectionTypeError(
                f"Publication connection '{connection_ref}' has no SQL verifier."
            )
        return publisher

    def catalog_reconciler(
        self,
        connection_ref: str,
    ) -> PublicationCatalogReconcilerPort | None:
        publisher = self.catalog_publisher(connection_ref)
        return publisher if isinstance(publisher, SqlPublicationCatalogPublisher) else None

    async def aclose(self) -> None:
        for publisher in self._catalog_publishers.values():
            if isinstance(publisher, SqlPublicationCatalogPublisher):
                await publisher.aclose()
