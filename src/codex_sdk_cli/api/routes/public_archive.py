from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response, status

from codex_sdk_cli.api.schemas.public_archive import (
    PublicArchiveCatalogVersionResponse,
    PublicArchiveStreamersResponse,
    PublicArchiveVideoItemResponse,
    PublicArchiveVideosResponse,
    public_archive_streamer_response,
    public_archive_video_response,
    public_archive_videos_response,
)
from codex_sdk_cli.api.use_case_dependencies.public_archive import (
    GetPublicArchiveCatalogVersionUseCaseDep,
    GetPublicArchiveVideoUseCaseDep,
    ListPublicArchiveStreamersUseCaseDep,
    ListPublicArchiveVideosUseCaseDep,
    PublicArchiveScopeDep,
)
from codex_sdk_cli.application.public_archive.queries import PublicArchiveVideoQuery

router = APIRouter()


@router.get("/videos", response_model=PublicArchiveVideosResponse)
async def list_public_archive_videos(
    use_case: ListPublicArchiveVideosUseCaseDep,
    scope: PublicArchiveScopeDep,
    sort: Annotated[Literal["latest", "oldest"], Query()] = "latest",
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    cursor: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(alias="q", max_length=500)] = None,
    streamer_id: Annotated[str | None, Query(alias="streamerId")] = None,
    channel_id: Annotated[int | None, Query(alias="channelId", ge=1)] = None,
    youtube_video_id: Annotated[
        str | None,
        Query(alias="youtubeVideoId", pattern=r"^[A-Za-z0-9_-]{11}$"),
    ] = None,
    include_stats: Annotated[bool, Query(alias="includeStats")] = False,
) -> PublicArchiveVideosResponse:
    page = await use_case.execute(
        PublicArchiveVideoQuery(
            scope=scope,
            sort=sort,
            limit=limit,
            cursor=cursor,
            query=query,
            streamer_id=streamer_id,
            channel_id=channel_id,
            youtube_video_id=youtube_video_id,
            include_stats=include_stats,
        )
    )
    return public_archive_videos_response(page)


@router.get("/videos/{videoId}", response_model=PublicArchiveVideoItemResponse)
async def get_public_archive_video(
    video_id: Annotated[
        str,
        Path(pattern=r"^(?:[1-9][0-9]*|[A-Za-z0-9_-]{11})$", alias="videoId"),
    ],
    use_case: GetPublicArchiveVideoUseCaseDep,
    scope: PublicArchiveScopeDep,
    response: Response,
) -> PublicArchiveVideoItemResponse:
    response.headers["cache-control"] = "no-store"
    video = await use_case.execute(scope=scope, identifier=video_id)
    return PublicArchiveVideoItemResponse(item=public_archive_video_response(video))


@router.head("/videos/{videoId}", status_code=status.HTTP_200_OK)
async def head_public_archive_video(
    video_id: Annotated[
        str,
        Path(pattern=r"^(?:[1-9][0-9]*|[A-Za-z0-9_-]{11})$", alias="videoId"),
    ],
    use_case: GetPublicArchiveVideoUseCaseDep,
    scope: PublicArchiveScopeDep,
) -> Response:
    await use_case.execute(scope=scope, identifier=video_id)
    return Response(status_code=status.HTTP_200_OK, headers={"cache-control": "no-store"})


@router.get("/streamers", response_model=PublicArchiveStreamersResponse)
async def list_public_archive_streamers(
    use_case: ListPublicArchiveStreamersUseCaseDep,
    scope: PublicArchiveScopeDep,
) -> PublicArchiveStreamersResponse:
    items = await use_case.execute(scope)
    return PublicArchiveStreamersResponse(
        items=[public_archive_streamer_response(item) for item in items]
    )


@router.get("/catalog-version", response_model=PublicArchiveCatalogVersionResponse)
async def get_public_archive_catalog_version(
    use_case: GetPublicArchiveCatalogVersionUseCaseDep,
    scope: PublicArchiveScopeDep,
    response: Response,
) -> PublicArchiveCatalogVersionResponse:
    response.headers["cache-control"] = "no-store"
    return PublicArchiveCatalogVersionResponse(version=await use_case.execute(scope))
