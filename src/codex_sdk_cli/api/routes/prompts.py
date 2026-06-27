from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, status

from codex_sdk_cli.api.use_case_dependencies.prompts import (
    ArchivePromptVersionUseCaseDep,
    CreatePromptVersionUseCaseDep,
    GetPromptUseCaseDep,
    InvalidatePromptCacheUseCaseDep,
    ListPromptsUseCaseDep,
    PublishPromptVersionUseCaseDep,
    UpdatePromptVersionUseCaseDep,
)
from codex_sdk_cli.domains.prompts.constants import PromptKey
from codex_sdk_cli.domains.prompts.schemas import (
    PromptCacheInvalidateRequest,
    PromptCacheInvalidateResponse,
    PromptDetailResponse,
    PromptSummaryResponse,
    PromptVersionCreateRequest,
    PromptVersionResponse,
    PromptVersionUpdateRequest,
)

router = APIRouter()


@router.post(
    "/prompts/cache/invalidate",
    response_model=PromptCacheInvalidateResponse,
)
async def invalidate_prompt_cache(
    use_case: InvalidatePromptCacheUseCaseDep,
    request: Annotated[PromptCacheInvalidateRequest | None, Body()] = None,
) -> PromptCacheInvalidateResponse:
    return await use_case.execute(request or PromptCacheInvalidateRequest())


@router.get("/prompts", response_model=list[PromptSummaryResponse])
async def list_prompts(
    use_case: ListPromptsUseCaseDep,
) -> list[PromptSummaryResponse]:
    return await use_case.execute()


@router.get("/prompts/{promptKey}", response_model=PromptDetailResponse)
async def get_prompt(
    prompt_key: Annotated[PromptKey, Path(alias="promptKey")],
    use_case: GetPromptUseCaseDep,
) -> PromptDetailResponse:
    return await use_case.execute(prompt_key)


@router.post(
    "/prompts/{promptKey}/versions",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_version(
    prompt_key: Annotated[PromptKey, Path(alias="promptKey")],
    request: PromptVersionCreateRequest,
    use_case: CreatePromptVersionUseCaseDep,
) -> PromptVersionResponse:
    return await use_case.execute(prompt_key, request)


@router.patch(
    "/prompts/{promptKey}/versions/{versionId}",
    response_model=PromptVersionResponse,
)
async def update_prompt_version(
    prompt_key: Annotated[PromptKey, Path(alias="promptKey")],
    version_id: Annotated[int, Path(alias="versionId", ge=1)],
    request: PromptVersionUpdateRequest,
    use_case: UpdatePromptVersionUseCaseDep,
) -> PromptVersionResponse:
    return await use_case.execute(prompt_key, version_id, request)


@router.post(
    "/prompts/{promptKey}/versions/{versionId}/publish",
    response_model=PromptVersionResponse,
)
async def publish_prompt_version(
    prompt_key: Annotated[PromptKey, Path(alias="promptKey")],
    version_id: Annotated[int, Path(alias="versionId", ge=1)],
    use_case: PublishPromptVersionUseCaseDep,
) -> PromptVersionResponse:
    return await use_case.execute(prompt_key, version_id)


@router.post(
    "/prompts/{promptKey}/versions/{versionId}/archive",
    response_model=PromptVersionResponse,
)
async def archive_prompt_version(
    prompt_key: Annotated[PromptKey, Path(alias="promptKey")],
    version_id: Annotated[int, Path(alias="versionId", ge=1)],
    use_case: ArchivePromptVersionUseCaseDep,
) -> PromptVersionResponse:
    return await use_case.execute(prompt_key, version_id)
