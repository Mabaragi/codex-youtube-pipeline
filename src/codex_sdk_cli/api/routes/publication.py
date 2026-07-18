from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, status

from codex_sdk_cli.api.operator_context import OperatorReason
from codex_sdk_cli.api.schemas.publication import (
    PublicationConnectionListResponse,
    PublicationConnectionResponse,
    PublicationStatusListResponse,
    PublicationStatusResponse,
)
from codex_sdk_cli.api.schemas.publication_cutovers import (
    PublicationCutoverPrepareRequest,
    PublicationCutoverResponse,
    publication_cutover_response,
)
from codex_sdk_cli.api.use_case_dependencies.publication import (
    ListPublicationStatusesUseCaseDep,
    PublicationConnectionRegistryDep,
)
from codex_sdk_cli.api.use_case_dependencies.publication_cutovers import (
    GetPublicationCutoverUseCaseDep,
    ListPublicationCutoversUseCaseDep,
    PublicationCutoverServiceDep,
)
from codex_sdk_cli.application.publication.status import PublicationStatusQuery

router = APIRouter()


@router.get(
    "/publish/connections",
    response_model=PublicationConnectionListResponse,
)
async def list_publication_connections(
    registry: PublicationConnectionRegistryDep,
) -> PublicationConnectionListResponse:
    items = [
        PublicationConnectionResponse.model_validate(summary.model_dump(by_alias=True))
        for summary in registry.safe_summaries()
    ]
    return PublicationConnectionListResponse(items=items, total=len(items))


@router.get(
    "/publish/publications",
    response_model=PublicationStatusListResponse,
)
async def list_publications(
    use_case: ListPublicationStatusesUseCaseDep,
    streamer_id: Annotated[int | None, Query(alias="streamerId", ge=1)] = None,
    profile_id: Annotated[int | None, Query(alias="profileId", ge=1)] = None,
    publish_mode: Annotated[
        Literal["prod", "dev"] | None,
        Query(alias="publishMode"),
    ] = None,
    environment: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    status: Annotated[
        Literal[
            "building",
            "ready",
            "partially_published",
            "published",
            "failed",
            "unavailable",
        ]
        | None,
        Query(),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PublicationStatusListResponse:
    result = await use_case.execute(
        PublicationStatusQuery(
            streamer_id=streamer_id,
            profile_id=profile_id,
            publish_mode=publish_mode,
            environment=environment,
            status=status,
            limit=limit,
            offset=offset,
        )
    )
    return PublicationStatusListResponse(
        items=[PublicationStatusResponse.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/publish/cutovers",
    response_model=PublicationCutoverResponse,
    status_code=status.HTTP_200_OK,
)
async def prepare_publication_cutover(
    request: PublicationCutoverPrepareRequest,
    reason: OperatorReason,
    cutovers: PublicationCutoverServiceDep,
) -> PublicationCutoverResponse:
    return publication_cutover_response(
        await cutovers.prepare(request.to_command(operator_reason=reason))
    )


@router.post(
    "/publish/cutovers/{cutoverId}/resume",
    response_model=PublicationCutoverResponse,
)
async def resume_publication_cutover(
    cutover_id: Annotated[int, Path(alias="cutoverId", ge=1)],
    reason: OperatorReason,
    cutovers: PublicationCutoverServiceDep,
) -> PublicationCutoverResponse:
    return publication_cutover_response(await cutovers.resume(cutover_id, operator_reason=reason))


@router.get(
    "/publish/cutovers",
    response_model=list[PublicationCutoverResponse],
)
async def list_publication_cutovers(
    use_case: ListPublicationCutoversUseCaseDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PublicationCutoverResponse]:
    return [publication_cutover_response(item) for item in await use_case.execute(limit=limit)]


@router.get(
    "/publish/cutovers/{cutoverId}",
    response_model=PublicationCutoverResponse,
)
async def get_publication_cutover(
    cutover_id: Annotated[int, Path(alias="cutoverId", ge=1)],
    use_case: GetPublicationCutoverUseCaseDep,
) -> PublicationCutoverResponse:
    return publication_cutover_response(await use_case.execute(cutover_id))
