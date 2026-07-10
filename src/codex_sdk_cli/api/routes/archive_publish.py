from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query

from codex_sdk_cli.api.use_case_dependencies.archive_publish import (
    ArchivePublishUseCaseDep,
)
from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchiveCurrentResponse,
    ArchiveOpsVideoListResponse,
    ArchivePublishModeLiteral,
    ArchivePublishRequest,
    ArchivePublishResponse,
    ArchivePublishStatusFilterLiteral,
)

router = APIRouter()


@router.post(
    "/video-tasks/archive-publish",
    response_model=ArchivePublishResponse,
)
async def publish_archive(
    use_case: ArchivePublishUseCaseDep,
    request: Annotated[ArchivePublishRequest | None, Body()] = None,
) -> ArchivePublishResponse:
    return await use_case.publish(request or ArchivePublishRequest())


@router.get(
    "/ops/archive/current",
    response_model=ArchiveCurrentResponse,
)
async def get_current_archive_publication(
    use_case: ArchivePublishUseCaseDep,
    environment: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    publish_mode: Annotated[
        ArchivePublishModeLiteral,
        Query(alias="publishMode"),
    ] = "prod",
) -> ArchiveCurrentResponse:
    return await use_case.get_current(environment=environment, publish_mode=publish_mode)


@router.get(
    "/ops/archive/videos",
    response_model=ArchiveOpsVideoListResponse,
)
async def list_archive_videos(
    use_case: ArchivePublishUseCaseDep,
    environment: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    channel_id: Annotated[int | None, Query(ge=1, alias="channelId")] = None,
    publish_status: Annotated[
        ArchivePublishStatusFilterLiteral | None,
        Query(alias="publishStatus"),
    ] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArchiveOpsVideoListResponse:
    return await use_case.list_ops_videos(
        environment=environment,
        channel_id=channel_id,
        publish_status=publish_status,
        search=search,
        limit=limit,
        offset=offset,
    )
