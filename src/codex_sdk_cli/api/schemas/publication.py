from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicationConnectionResponse(BaseModel):
    connection_ref: str = Field(alias="connectionRef")
    kind: Literal["s3_compatible_object", "http_catalog", "sql_catalog"]
    target: str
    public_base_url: str | None = Field(default=None, alias="publicBaseUrl")
    secret_fields: list[str] = Field(default_factory=list, alias="secretFields")
    configured: bool

    model_config = ConfigDict(populate_by_name=True)


class PublicationConnectionListResponse(BaseModel):
    items: list[PublicationConnectionResponse]
    total: int

    model_config = ConfigDict(populate_by_name=True)


class PublicationDeliveryStatusResponse(BaseModel):
    id: int
    object_binding_id: int = Field(alias="objectBindingId")
    destination_id: int = Field(alias="destinationId")
    destination_key: str = Field(alias="destinationKey")
    destination_name: str = Field(alias="destinationName")
    required: bool
    status: str
    index_public_url: str | None = Field(alias="indexPublicUrl")
    pointer_public_url: str | None = Field(alias="pointerPublicUrl")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PublicationStatusResponse(BaseModel):
    id: int
    profile_id: int = Field(alias="profileId")
    profile_key: str = Field(alias="profileKey")
    profile_name: str = Field(alias="profileName")
    profile_revision_id: int = Field(alias="profileRevisionId")
    route_id: int = Field(alias="routeId")
    publish_mode: str = Field(alias="publishMode")
    environment: str
    schema_version: int = Field(alias="schemaVersion")
    version: str
    status: str
    video_count: int = Field(alias="videoCount")
    artifact_count: int = Field(alias="artifactCount")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    deliveries: list[PublicationDeliveryStatusResponse]

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PublicationStatusListResponse(BaseModel):
    items: list[PublicationStatusResponse]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(populate_by_name=True)
