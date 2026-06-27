from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import PromptCacheDep, PromptRepositoryDep, SettingsDep
from codex_sdk_cli.domains.prompts.use_cases import (
    ArchivePromptVersionUseCase,
    CreatePromptVersionUseCase,
    GetPromptUseCase,
    InvalidatePromptCacheUseCase,
    ListPromptsUseCase,
    PromptResolver,
    PublishPromptVersionUseCase,
    UpdatePromptVersionUseCase,
)


def get_prompt_resolver(
    repository: PromptRepositoryDep,
    cache: PromptCacheDep,
    settings: SettingsDep,
) -> PromptResolver:
    return PromptResolver(
        repository,
        cache=cache,
        ttl_seconds=settings.prompt_cache_ttl_seconds,
    )


def get_list_prompts_use_case(
    repository: PromptRepositoryDep,
    resolver: Annotated[PromptResolver, Depends(get_prompt_resolver)],
) -> ListPromptsUseCase:
    return ListPromptsUseCase(repository, resolver)


def get_get_prompt_use_case(
    repository: PromptRepositoryDep,
    resolver: Annotated[PromptResolver, Depends(get_prompt_resolver)],
) -> GetPromptUseCase:
    return GetPromptUseCase(repository, resolver)


def get_create_prompt_version_use_case(
    repository: PromptRepositoryDep,
) -> CreatePromptVersionUseCase:
    return CreatePromptVersionUseCase(repository)


def get_update_prompt_version_use_case(
    repository: PromptRepositoryDep,
) -> UpdatePromptVersionUseCase:
    return UpdatePromptVersionUseCase(repository)


def get_publish_prompt_version_use_case(
    repository: PromptRepositoryDep,
    cache: PromptCacheDep,
) -> PublishPromptVersionUseCase:
    return PublishPromptVersionUseCase(repository, cache)


def get_archive_prompt_version_use_case(
    repository: PromptRepositoryDep,
    cache: PromptCacheDep,
) -> ArchivePromptVersionUseCase:
    return ArchivePromptVersionUseCase(repository, cache)


def get_invalidate_prompt_cache_use_case(
    cache: PromptCacheDep,
) -> InvalidatePromptCacheUseCase:
    return InvalidatePromptCacheUseCase(cache)


PromptResolverDep = Annotated[PromptResolver, Depends(get_prompt_resolver)]
ListPromptsUseCaseDep = Annotated[
    ListPromptsUseCase,
    Depends(get_list_prompts_use_case),
]
GetPromptUseCaseDep = Annotated[
    GetPromptUseCase,
    Depends(get_get_prompt_use_case),
]
CreatePromptVersionUseCaseDep = Annotated[
    CreatePromptVersionUseCase,
    Depends(get_create_prompt_version_use_case),
]
UpdatePromptVersionUseCaseDep = Annotated[
    UpdatePromptVersionUseCase,
    Depends(get_update_prompt_version_use_case),
]
PublishPromptVersionUseCaseDep = Annotated[
    PublishPromptVersionUseCase,
    Depends(get_publish_prompt_version_use_case),
]
ArchivePromptVersionUseCaseDep = Annotated[
    ArchivePromptVersionUseCase,
    Depends(get_archive_prompt_version_use_case),
]
InvalidatePromptCacheUseCaseDep = Annotated[
    InvalidatePromptCacheUseCase,
    Depends(get_invalidate_prompt_cache_use_case),
]
