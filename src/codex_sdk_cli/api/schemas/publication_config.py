from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from codex_sdk_cli.application.publication_config.ports import (
    CreateCatalogDestination,
    CreateObjectDestination,
    CreatePublishProfile,
    CreatePublishProfileRevision,
    CreatePublishProfileRoute,
    CreateRouteCatalogBinding,
    CreateRouteObjectBinding,
)
from codex_sdk_cli.domains.publication_config.models import (
    PublishCatalogDestination,
    PublishMode,
    PublishObjectDestination,
    PublishProfile,
    PublishProfileDetail,
    PublishProfileRevision,
    PublishProfileRevisionState,
    PublishProfileRoute,
    PublishRouteCatalogBinding,
    PublishRouteObjectBinding,
)


class ObjectDestinationCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=255)
    connection_ref: str = Field(min_length=1, max_length=255, alias="connectionRef")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_command(self) -> CreateObjectDestination:
        return CreateObjectDestination(
            key=self.key,
            name=self.name,
            connection_ref=self.connection_ref,
        )


class ObjectDestinationResponse(BaseModel):
    id: int
    key: str
    name: str
    connection_ref: str = Field(alias="connectionRef")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class CatalogDestinationCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=255)
    connection_ref: str = Field(min_length=1, max_length=255, alias="connectionRef")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_command(self) -> CreateCatalogDestination:
        return CreateCatalogDestination(
            key=self.key,
            name=self.name,
            connection_ref=self.connection_ref,
        )


class CatalogDestinationResponse(BaseModel):
    id: int
    key: str
    name: str
    connection_ref: str = Field(alias="connectionRef")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class PublishProfileCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    def to_command(self) -> CreatePublishProfile:
        return CreatePublishProfile(
            key=self.key,
            name=self.name,
            description=self.description,
        )


class PublishProfileSummaryResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str | None
    active_revision_id: int | None = Field(alias="activeRevisionId")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class RouteObjectBindingCreateRequest(BaseModel):
    destination_id: int = Field(ge=1, alias="destinationId")
    key_prefix: str = Field(min_length=1, max_length=512, alias="keyPrefix")
    required: bool = True
    is_primary: bool = Field(default=False, alias="isPrimary")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    @field_validator("key_prefix")
    @classmethod
    def normalize_key_prefix(cls, value: str) -> str:
        normalized = value.strip("/")
        if not normalized:
            raise ValueError("keyPrefix must contain at least one non-slash character.")
        return normalized

    def to_command(self) -> CreateRouteObjectBinding:
        return CreateRouteObjectBinding(
            destination_id=self.destination_id,
            key_prefix=self.key_prefix,
            required=self.required,
            is_primary=self.is_primary,
        )


class RouteCatalogBindingCreateRequest(BaseModel):
    destination_id: int = Field(ge=1, alias="destinationId")
    source_object_destination_id: int = Field(
        ge=1,
        alias="sourceObjectDestinationId",
    )
    required: bool = True

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_command(self) -> CreateRouteCatalogBinding:
        return CreateRouteCatalogBinding(
            destination_id=self.destination_id,
            source_object_destination_id=self.source_object_destination_id,
            required=self.required,
        )


class PublishProfileRouteCreateRequest(BaseModel):
    publish_mode: PublishMode = Field(alias="publishMode")
    environment: str = Field(min_length=1, max_length=64)
    object_bindings: list[RouteObjectBindingCreateRequest] = Field(
        min_length=1,
        alias="objectBindings",
    )
    catalog_bindings: list[RouteCatalogBindingCreateRequest] = Field(
        default_factory=list,
        alias="catalogBindings",
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_command(self) -> CreatePublishProfileRoute:
        return CreatePublishProfileRoute(
            publish_mode=self.publish_mode,
            environment=self.environment,
            object_bindings=tuple(item.to_command() for item in self.object_bindings),
            catalog_bindings=tuple(item.to_command() for item in self.catalog_bindings),
        )


class PublishProfileRevisionCreateRequest(BaseModel):
    routes: list[PublishProfileRouteCreateRequest] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    def to_command(self, profile_id: int) -> CreatePublishProfileRevision:
        return CreatePublishProfileRevision(
            profile_id=profile_id,
            routes=tuple(route.to_command() for route in self.routes),
        )


class RouteObjectBindingResponse(BaseModel):
    id: int
    destination_id: int = Field(alias="destinationId")
    destination_key: str = Field(alias="destinationKey")
    connection_ref: str = Field(alias="connectionRef")
    key_prefix: str = Field(alias="keyPrefix")
    required: bool
    is_primary: bool = Field(alias="isPrimary")

    model_config = ConfigDict(populate_by_name=True)


class RouteCatalogBindingResponse(BaseModel):
    id: int
    destination_id: int = Field(alias="destinationId")
    destination_key: str = Field(alias="destinationKey")
    connection_ref: str = Field(alias="connectionRef")
    source_object_binding_id: int = Field(alias="sourceObjectBindingId")
    required: bool

    model_config = ConfigDict(populate_by_name=True)


class PublishProfileRouteResponse(BaseModel):
    id: int
    publish_mode: PublishMode = Field(alias="publishMode")
    environment: str
    object_bindings: list[RouteObjectBindingResponse] = Field(alias="objectBindings")
    catalog_bindings: list[RouteCatalogBindingResponse] = Field(alias="catalogBindings")

    model_config = ConfigDict(populate_by_name=True)


class PublishProfileRevisionResponse(BaseModel):
    id: int
    profile_id: int = Field(alias="profileId")
    revision_number: int = Field(alias="revisionNumber")
    state: PublishProfileRevisionState
    created_at: datetime = Field(alias="createdAt")
    activated_at: datetime | None = Field(alias="activatedAt")
    routes: list[PublishProfileRouteResponse]

    model_config = ConfigDict(populate_by_name=True)


class PublishProfileDetailResponse(PublishProfileSummaryResponse):
    revisions: list[PublishProfileRevisionResponse]


def object_destination_response(
    destination: PublishObjectDestination,
) -> ObjectDestinationResponse:
    return ObjectDestinationResponse.model_validate(destination, from_attributes=True)


def catalog_destination_response(
    destination: PublishCatalogDestination,
) -> CatalogDestinationResponse:
    return CatalogDestinationResponse.model_validate(destination, from_attributes=True)


def publish_profile_summary_response(profile: PublishProfile) -> PublishProfileSummaryResponse:
    return PublishProfileSummaryResponse.model_validate(profile, from_attributes=True)


def publish_profile_detail_response(detail: PublishProfileDetail) -> PublishProfileDetailResponse:
    return PublishProfileDetailResponse(
        **publish_profile_summary_response(detail.profile).model_dump(),
        revisions=[publish_profile_revision_response(item) for item in detail.revisions],
    )


def publish_profile_revision_response(
    revision: PublishProfileRevision,
) -> PublishProfileRevisionResponse:
    return PublishProfileRevisionResponse(
        id=revision.id,
        profileId=revision.profile_id,
        revisionNumber=revision.revision_number,
        state=revision.state,
        createdAt=revision.created_at,
        activatedAt=revision.activated_at,
        routes=[_route_response(item) for item in revision.routes],
    )


def _route_response(route: PublishProfileRoute) -> PublishProfileRouteResponse:
    return PublishProfileRouteResponse(
        id=route.id,
        publishMode=route.publish_mode,
        environment=route.environment,
        objectBindings=[_object_binding_response(item) for item in route.object_bindings],
        catalogBindings=[_catalog_binding_response(item) for item in route.catalog_bindings],
    )


def _object_binding_response(
    binding: PublishRouteObjectBinding,
) -> RouteObjectBindingResponse:
    return RouteObjectBindingResponse.model_validate(binding, from_attributes=True)


def _catalog_binding_response(
    binding: PublishRouteCatalogBinding,
) -> RouteCatalogBindingResponse:
    return RouteCatalogBindingResponse.model_validate(binding, from_attributes=True)
