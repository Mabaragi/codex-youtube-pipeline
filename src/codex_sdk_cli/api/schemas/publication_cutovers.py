from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.application.publication.cutover_ports import PublicationCutoverRecord
from codex_sdk_cli.application.publication.cutovers import PreparePublicationCutover


class PublicationCutoverPrepareRequest(BaseModel):
    streamer_id: int = Field(ge=1, alias="streamerId")
    target_profile_id: int = Field(ge=1, alias="targetProfileId")
    publish_mode: Literal["prod", "dev"] = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1, le=100, alias="schemaVersion")

    @model_validator(mode="after")
    def validate_mode_environment(self) -> PublicationCutoverPrepareRequest:
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        return self

    def to_command(self, *, operator_reason: str) -> PreparePublicationCutover:
        return PreparePublicationCutover(
            streamer_id=self.streamer_id,
            target_profile_id=self.target_profile_id,
            publish_mode=self.publish_mode,
            environment=self.environment,
            schema_version=self.schema_version,
            operator_reason=operator_reason,
        )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PublicationCutoverResponse(BaseModel):
    id: int
    streamer_id: int = Field(alias="streamerId")
    source_profile_id: int = Field(alias="sourceProfileId")
    target_profile_id: int = Field(alias="targetProfileId")
    source_profile_revision_id: int = Field(alias="sourceProfileRevisionId")
    target_profile_revision_id: int = Field(alias="targetProfileRevisionId")
    source_route_id: int = Field(alias="sourceRouteId")
    target_route_id: int = Field(alias="targetRouteId")
    publish_mode: str = Field(alias="publishMode")
    environment: str
    schema_version: int = Field(alias="schemaVersion")
    artifact_ids: list[int] = Field(alias="artifactIds")
    status: str
    last_completed_step: str | None = Field(alias="lastCompletedStep")
    target_publication_id: int | None = Field(alias="targetPublicationId")
    source_publication_id: int | None = Field(alias="sourcePublicationId")
    target_pointer_published_at: datetime | None = Field(alias="targetPointerPublishedAt")
    streamer_assigned_at: datetime | None = Field(alias="streamerAssignedAt")
    source_pointer_published_at: datetime | None = Field(alias="sourcePointerPublishedAt")
    last_error_step: str | None = Field(alias="lastErrorStep")
    last_error_code: str | None = Field(alias="lastErrorCode")
    last_error_message: str | None = Field(alias="lastErrorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


def publication_cutover_response(
    record: PublicationCutoverRecord,
) -> PublicationCutoverResponse:
    return PublicationCutoverResponse(
        id=record.id,
        streamerId=record.streamer_id,
        sourceProfileId=record.source_profile_id,
        targetProfileId=record.target_profile_id,
        sourceProfileRevisionId=record.source_profile_revision_id,
        targetProfileRevisionId=record.target_profile_revision_id,
        sourceRouteId=record.source_route_id,
        targetRouteId=record.target_route_id,
        publishMode=record.publish_mode,
        environment=record.environment,
        schemaVersion=record.schema_version,
        artifactIds=list(record.artifact_ids),
        status=record.status,
        lastCompletedStep=record.last_completed_step,
        targetPublicationId=record.target_publication_id,
        sourcePublicationId=record.source_publication_id,
        targetPointerPublishedAt=record.target_pointer_published_at,
        streamerAssignedAt=record.streamer_assigned_at,
        sourcePointerPublishedAt=record.source_pointer_published_at,
        lastErrorStep=record.last_error_step,
        lastErrorCode=record.last_error_code,
        lastErrorMessage=record.last_error_message,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
