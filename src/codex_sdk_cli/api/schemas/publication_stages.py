from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.application.publication.models import PublicationStageResult

PublishMode = Literal["prod", "dev"]


class ArchiveArtifactBuildOperationRequest(BaseModel):
    video_ids: list[int] = Field(min_length=1, max_length=200, alias="videoIds")
    publish_mode: PublishMode = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    variant: str = Field(default="control", min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1, le=100, alias="schemaVersion")
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")

    @model_validator(mode="after")
    def validate_mode_environment(self) -> ArchiveArtifactBuildOperationRequest:
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ArchiveArtifactCanonicalizeRequest(BaseModel):
    artifact_ids: list[int] = Field(min_length=1, max_length=1000, alias="artifactIds")
    publish_mode: PublishMode = Field(default="prod", alias="publishMode")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PublicationArtifactStageRequest(BaseModel):
    artifact_ids: list[int] = Field(min_length=1, max_length=1000, alias="artifactIds")
    profile_revision_id: int = Field(ge=1, alias="profileRevisionId")
    publish_mode: PublishMode = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    destination_ids: list[int] | None = Field(
        default=None,
        max_length=100,
        alias="destinationIds",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PublicationBuildStageRequest(PublicationArtifactStageRequest):
    schema_version: int = Field(default=1, ge=1, le=100, alias="schemaVersion")


class PublicationPointerStageRequest(BaseModel):
    publication_id: int = Field(ge=1, alias="publicationId")
    artifact_ids: list[int] = Field(min_length=1, max_length=1000, alias="artifactIds")
    profile_revision_id: int = Field(ge=1, alias="profileRevisionId")
    publish_mode: PublishMode = Field(alias="publishMode")
    environment: str = Field(min_length=1, max_length=64)
    destination_ids: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        alias="destinationIds",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def validate_membership(self) -> PublicationPointerStageRequest:
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("artifactIds must not contain duplicates.")
        return self


class PublicationDestinationResultResponse(BaseModel):
    destination_id: int = Field(alias="destinationId")
    binding_id: int = Field(alias="bindingId")
    destination_type: Literal["object", "catalog"] = Field(alias="destinationType")
    required: bool
    status: str
    reused: bool
    public_url: str | None = Field(alias="publicUrl")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class PublicationStageResponse(BaseModel):
    stage: str
    status: Literal["succeeded", "succeededWithWarnings", "failed"]
    artifact_ids: list[int] = Field(alias="artifactIds")
    profile_revision_id: int | None = Field(alias="profileRevisionId")
    route_id: int | None = Field(alias="routeId")
    publication_id: int | None = Field(alias="publicationId")
    destination_results: list[PublicationDestinationResultResponse] = Field(
        alias="destinationResults"
    )
    missing_preconditions: list[dict[str, object]] = Field(alias="missingPreconditions")
    metadata: dict[str, object]

    model_config = ConfigDict(populate_by_name=True)


def publication_stage_response(result: PublicationStageResult) -> PublicationStageResponse:
    return PublicationStageResponse(
        stage=result.stage,
        status=result.status,
        artifactIds=list(result.artifact_ids),
        profileRevisionId=result.profile_revision_id,
        routeId=result.route_id,
        publicationId=result.publication_id,
        destinationResults=[
            PublicationDestinationResultResponse(
                destinationId=item.destination_id,
                bindingId=item.binding_id,
                destinationType=item.destination_type,
                required=item.required,
                status=item.status,
                reused=item.reused,
                publicUrl=item.public_url,
                errorCode=item.error_code,
                errorMessage=item.error_message,
            )
            for item in result.destination_results
        ],
        missingPreconditions=list(result.missing_preconditions),
        metadata=result.metadata,
    )
