from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.operator_context import OperatorReason
from codex_sdk_cli.api.schemas.publication_config import (
    CatalogDestinationCreateRequest,
    CatalogDestinationResponse,
    ObjectDestinationCreateRequest,
    ObjectDestinationResponse,
    PublishProfileCreateRequest,
    PublishProfileDetailResponse,
    PublishProfileRevisionCreateRequest,
    PublishProfileRevisionResponse,
    PublishProfileSummaryResponse,
    catalog_destination_response,
    object_destination_response,
    publish_profile_detail_response,
    publish_profile_revision_response,
    publish_profile_summary_response,
)
from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    RecordOperatorMutationUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.publication_config import (
    ActivatePublishProfileRevisionUseCaseDep,
    CreateCatalogDestinationUseCaseDep,
    CreateObjectDestinationUseCaseDep,
    CreatePublishProfileRevisionUseCaseDep,
    CreatePublishProfileUseCaseDep,
    GetPublishProfileUseCaseDep,
    ListCatalogDestinationsUseCaseDep,
    ListObjectDestinationsUseCaseDep,
    ListPublishProfilesUseCaseDep,
)

router = APIRouter()


@router.post(
    "/publish/object-destinations",
    response_model=ObjectDestinationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_object_destination(
    request: ObjectDestinationCreateRequest,
    reason: OperatorReason,
    use_case: CreateObjectDestinationUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> ObjectDestinationResponse:
    destination = await use_case.execute(request.to_command())
    await audit.execute(
        mutation="created",
        target_type="publish_object_destination",
        target_id=destination.id,
        action="create",
        reason=reason,
        metadata={"key": destination.key, "connectionRef": destination.connection_ref},
    )
    return object_destination_response(destination)


@router.get(
    "/publish/object-destinations",
    response_model=list[ObjectDestinationResponse],
)
async def list_object_destinations(
    use_case: ListObjectDestinationsUseCaseDep,
) -> list[ObjectDestinationResponse]:
    return [object_destination_response(item) for item in await use_case.execute()]


@router.post(
    "/publish/catalog-destinations",
    response_model=CatalogDestinationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_destination(
    request: CatalogDestinationCreateRequest,
    reason: OperatorReason,
    use_case: CreateCatalogDestinationUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> CatalogDestinationResponse:
    destination = await use_case.execute(request.to_command())
    await audit.execute(
        mutation="created",
        target_type="publish_catalog_destination",
        target_id=destination.id,
        action="create",
        reason=reason,
        metadata={"key": destination.key, "connectionRef": destination.connection_ref},
    )
    return catalog_destination_response(destination)


@router.get(
    "/publish/catalog-destinations",
    response_model=list[CatalogDestinationResponse],
)
async def list_catalog_destinations(
    use_case: ListCatalogDestinationsUseCaseDep,
) -> list[CatalogDestinationResponse]:
    return [catalog_destination_response(item) for item in await use_case.execute()]


@router.post(
    "/publish/profiles",
    response_model=PublishProfileSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publish_profile(
    request: PublishProfileCreateRequest,
    reason: OperatorReason,
    use_case: CreatePublishProfileUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> PublishProfileSummaryResponse:
    profile = await use_case.execute(request.to_command())
    await audit.execute(
        mutation="created",
        target_type="publish_profile",
        target_id=profile.id,
        action="create",
        reason=reason,
        metadata={"key": profile.key},
    )
    return publish_profile_summary_response(profile)


@router.get(
    "/publish/profiles",
    response_model=list[PublishProfileSummaryResponse],
)
async def list_publish_profiles(
    use_case: ListPublishProfilesUseCaseDep,
) -> list[PublishProfileSummaryResponse]:
    return [publish_profile_summary_response(item) for item in await use_case.execute()]


@router.get(
    "/publish/profiles/{profileId}",
    response_model=PublishProfileDetailResponse,
)
async def get_publish_profile(
    profile_id: Annotated[int, Path(alias="profileId", ge=1)],
    use_case: GetPublishProfileUseCaseDep,
) -> PublishProfileDetailResponse:
    return publish_profile_detail_response(await use_case.execute(profile_id))


@router.post(
    "/publish/profiles/{profileId}/revisions",
    response_model=PublishProfileRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publish_profile_revision(
    profile_id: Annotated[int, Path(alias="profileId", ge=1)],
    request: PublishProfileRevisionCreateRequest,
    reason: OperatorReason,
    use_case: CreatePublishProfileRevisionUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> PublishProfileRevisionResponse:
    revision = await use_case.execute(request.to_command(profile_id))
    await audit.execute(
        mutation="created",
        target_type="publish_profile_revision",
        target_id=revision.id,
        action="create",
        reason=reason,
        metadata={
            "profileId": profile_id,
            "revisionNumber": revision.revision_number,
        },
    )
    return publish_profile_revision_response(revision)


@router.post(
    "/publish/profiles/{profileId}/revisions/{revisionId}/activate",
    response_model=PublishProfileRevisionResponse,
)
async def activate_publish_profile_revision(
    profile_id: Annotated[int, Path(alias="profileId", ge=1)],
    revision_id: Annotated[int, Path(alias="revisionId", ge=1)],
    reason: OperatorReason,
    use_case: ActivatePublishProfileRevisionUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> PublishProfileRevisionResponse:
    revision = await use_case.execute(profile_id=profile_id, revision_id=revision_id)
    await audit.execute(
        mutation="activated",
        target_type="publish_profile_revision",
        target_id=revision.id,
        action="activate",
        reason=reason,
        metadata={"profileId": profile_id},
    )
    return publish_profile_revision_response(revision)
