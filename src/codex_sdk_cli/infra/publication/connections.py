from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from sqlalchemy.engine import make_url

from codex_sdk_cli.domains.publication.exceptions import (
    PublicationConnectionConfigurationError,
    PublicationConnectionNotFoundError,
)
from codex_sdk_cli.domains.publication_config.connections import (
    PublicationConnectionKind,
    is_safe_connection_ref,
)


class S3CompatibleObjectConnection(BaseModel):
    kind: Literal["s3_compatible_object"]
    endpoint: str = Field(min_length=1)
    access_key: SecretStr = Field(alias="accessKey")
    secret_key: SecretStr = Field(alias="secretKey")
    bucket: str = Field(min_length=1, max_length=255)
    secure: bool = True
    region: str = Field(default="auto", min_length=1, max_length=64)
    public_base_url: str = Field(min_length=1, alias="publicBaseUrl")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class HttpCatalogConnection(BaseModel):
    kind: Literal["http_catalog"]
    url: str = Field(min_length=1)
    token: SecretStr | None = None
    timeout_seconds: float = Field(default=15.0, gt=0, alias="timeoutSeconds")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SqlCatalogConnection(BaseModel):
    kind: Literal["sql_catalog"]
    database_url: SecretStr = Field(alias="databaseUrl")
    echo: bool = False

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


PublicationConnection = Annotated[
    S3CompatibleObjectConnection | HttpCatalogConnection | SqlCatalogConnection,
    Field(discriminator="kind"),
]


class PublicationConnectionSummary(BaseModel):
    connection_ref: str = Field(alias="connectionRef")
    kind: PublicationConnectionKind
    target: str
    public_base_url: str | None = Field(default=None, alias="publicBaseUrl")
    secret_fields: list[str] = Field(default_factory=list, alias="secretFields")
    configured: bool = True

    model_config = ConfigDict(populate_by_name=True)


class PublicationConnectionRegistry(BaseModel):
    version: Literal[1] = 1
    connections: dict[str, PublicationConnection] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("connections")
    @classmethod
    def _validate_connection_refs(
        cls,
        connections: dict[str, PublicationConnection],
    ) -> dict[str, PublicationConnection]:
        for connection_ref in connections:
            if not is_safe_connection_ref(connection_ref):
                raise ValueError(
                    "connection refs must contain only lowercase letters, digits, '.', '_', or '-'"
                )
        return connections

    def connection(self, connection_ref: str) -> PublicationConnection:
        try:
            return self.connections[connection_ref]
        except KeyError as exc:
            raise PublicationConnectionNotFoundError(
                f"Publication connection '{connection_ref}' is not configured."
            ) from exc

    def connection_kind(self, connection_ref: str) -> PublicationConnectionKind | None:
        connection = self.connections.get(connection_ref)
        return connection.kind if connection is not None else None

    def safe_summaries(self) -> tuple[PublicationConnectionSummary, ...]:
        return tuple(
            _safe_summary(connection_ref, connection)
            for connection_ref, connection in sorted(self.connections.items())
        )


def load_publication_connection_registry(
    path: Path | None,
) -> PublicationConnectionRegistry:
    if path is None:
        return PublicationConnectionRegistry()
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublicationConnectionConfigurationError(
            f"Publication connection registry could not be read: {path}"
        ) from exc
    try:
        return PublicationConnectionRegistry.model_validate_json(payload)
    except ValidationError as exc:
        raise PublicationConnectionConfigurationError(
            f"Publication connection registry is invalid: {path}"
        ) from exc


def _safe_summary(
    connection_ref: str,
    connection: PublicationConnection,
) -> PublicationConnectionSummary:
    if isinstance(connection, S3CompatibleObjectConnection):
        return PublicationConnectionSummary(
            connectionRef=connection_ref,
            kind=connection.kind,
            target=_safe_http_target(connection.endpoint),
            publicBaseUrl=_safe_http_target(connection.public_base_url),
            secretFields=["accessKey", "secretKey"],
        )
    if isinstance(connection, HttpCatalogConnection):
        return PublicationConnectionSummary(
            connectionRef=connection_ref,
            kind=connection.kind,
            target=_safe_http_target(connection.url),
            secretFields=["token"] if connection.token is not None else [],
        )
    return PublicationConnectionSummary(
        connectionRef=connection_ref,
        kind=connection.kind,
        target=_safe_database_target(connection.database_url.get_secret_value()),
        secretFields=["databaseUrl"],
    )


def _safe_http_target(value: str) -> str:
    has_scheme = "://" in value
    parsed = urlsplit(value if has_scheme else f"//{value}")
    if not parsed.hostname:
        return "configured-target"
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return "configured-target"
    if port is not None:
        host = f"{host}:{port}"
    if not has_scheme:
        return host
    return urlunsplit((parsed.scheme, host, "", "", ""))


def _safe_database_target(database_url: str) -> str:
    try:
        url = make_url(database_url)
        host = url.host or "local"
        port = url.port
    except ValueError:
        return "invalid-database-url"
    if port is not None:
        host = f"{host}:{port}"
    database = (url.database or "").lstrip("/")
    suffix = f"/{database}" if database else ""
    return f"{url.drivername}://{host}{suffix}"
