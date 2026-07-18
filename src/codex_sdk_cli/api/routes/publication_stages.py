from __future__ import annotations

from fastapi import APIRouter, status

from codex_sdk_cli.api.schemas.publication_stages import (
    ArchiveArtifactBuildOperationRequest,
    PublicationArtifactStageRequest,
    PublicationBuildStageRequest,
    PublicationPointerStageRequest,
    PublicationStageResponse,
    publication_stage_response,
)
from codex_sdk_cli.api.use_case_dependencies.archive_publish import (
    ArchivePublishUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.publication_stages import (
    PublicationStageServiceDep,
)
from codex_sdk_cli.application.publication.models import (
    PublicationDestinationResult,
    PublicationStageResult,
)
from codex_sdk_cli.domains.archive_publish.schemas import ArchivePublishRequest

router = APIRouter()


@router.post(
    "/operations/archive-artifact-build",
    response_model=PublicationStageResponse,
    status_code=status.HTTP_200_OK,
)
async def build_archive_artifacts(
    request: ArchiveArtifactBuildOperationRequest,
    use_case: ArchivePublishUseCaseDep,
    _stages: PublicationStageServiceDep,
) -> PublicationStageResponse:
    result = await use_case.publish(
        ArchivePublishRequest(
            target="selected_videos",
            videoIds=request.video_ids,
            limit=len(request.video_ids),
            publishMode=request.publish_mode,
            environment=request.environment,
            variant=request.variant,
            schemaVersion=request.schema_version,
            retryFailed=request.retry_failed,
            regenerateSucceeded=request.rerun_succeeded,
            includeNonEmbeddable=request.include_non_embeddable,
            stopAfterStage="artifact",
        )
    )
    destinations = tuple(
        PublicationDestinationResult(
            destination_id=0,
            binding_id=0,
            destination_type="object",
            required=True,
            status=("succeeded" if item.status == "succeeded" else "failed"),
            reused=item.reason == "already_published",
            public_url=item.public_url,
            error_code=item.error_type,
            error_message=item.error_message,
        )
        for item in result.items
    )
    artifact_ids = tuple(item.artifact_id for item in result.items if item.artifact_id is not None)
    return publication_stage_response(
        PublicationStageResult(
            stage="artifactBuild",
            status="failed" if result.failed_count else "succeeded",
            artifact_ids=artifact_ids,
            destination_results=destinations,
            metadata={
                "requestedCount": result.requested_count,
                "processedCount": result.processed_count,
                "failedCount": result.failed_count,
            },
        )
    )


@router.post(
    "/operations/archive-object-deliver",
    response_model=PublicationStageResponse,
    status_code=status.HTTP_200_OK,
)
async def deliver_archive_objects(
    request: PublicationArtifactStageRequest,
    stages: PublicationStageServiceDep,
) -> PublicationStageResponse:
    route = await stages.revision_route(
        profile_revision_id=request.profile_revision_id,
        publish_mode=request.publish_mode,
        environment=request.environment,
    )
    return publication_stage_response(
        await stages.deliver_objects(
            artifact_ids=tuple(request.artifact_ids),
            route=route,
            destination_ids=_optional_ids(request.destination_ids),
        )
    )


@router.post(
    "/operations/archive-catalog-publish",
    response_model=PublicationStageResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_archive_catalogs(
    request: PublicationArtifactStageRequest,
    stages: PublicationStageServiceDep,
) -> PublicationStageResponse:
    route = await stages.revision_route(
        profile_revision_id=request.profile_revision_id,
        publish_mode=request.publish_mode,
        environment=request.environment,
    )
    return publication_stage_response(
        await stages.publish_catalogs(
            artifact_ids=tuple(request.artifact_ids),
            route=route,
            destination_ids=_optional_ids(request.destination_ids),
        )
    )


@router.post(
    "/operations/archive-publication-build",
    response_model=PublicationStageResponse,
    status_code=status.HTTP_200_OK,
)
async def build_archive_publication(
    request: PublicationBuildStageRequest,
    stages: PublicationStageServiceDep,
) -> PublicationStageResponse:
    route = await stages.revision_route(
        profile_revision_id=request.profile_revision_id,
        publish_mode=request.publish_mode,
        environment=request.environment,
    )
    return publication_stage_response(
        await stages.build_publication(
            artifact_ids=tuple(request.artifact_ids),
            route=route,
            schema_version=request.schema_version,
            destination_ids=_optional_ids(request.destination_ids),
        )
    )


@router.post(
    "/operations/archive-pointer-publish",
    response_model=PublicationStageResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_archive_pointer(
    request: PublicationPointerStageRequest,
    stages: PublicationStageServiceDep,
) -> PublicationStageResponse:
    return publication_stage_response(
        await stages.publish_pointer(
            publication_id=request.publication_id,
            destination_ids=_optional_ids(request.destination_ids),
            expected_artifact_ids=tuple(sorted(request.artifact_ids)),
            expected_profile_revision_id=request.profile_revision_id,
            expected_publish_mode=request.publish_mode,
            expected_environment=request.environment,
        )
    )


def _optional_ids(values: list[int] | None) -> tuple[int, ...] | None:
    return tuple(values) if values is not None else None
