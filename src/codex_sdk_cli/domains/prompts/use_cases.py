from __future__ import annotations

import hashlib

from .cache import PromptCache
from .constants import KNOWN_PROMPT_KEYS, PromptKey
from .exceptions import PromptInvalid, PromptNotFound
from .fallbacks import fallback_prompt
from .ports import (
    PromptRepositoryPort,
    PromptVersionCreate,
    PromptVersionRecord,
    PromptVersionUpdate,
    ResolvedPrompt,
)
from .schemas import (
    PromptBodyResponse,
    PromptCacheInvalidateRequest,
    PromptCacheInvalidateResponse,
    PromptDetailResponse,
    PromptSummaryResponse,
    PromptVersionCreateRequest,
    PromptVersionResponse,
    PromptVersionUpdateRequest,
)


class PromptResolver:
    def __init__(
        self,
        repository: PromptRepositoryPort,
        *,
        cache: PromptCache,
        ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._ttl_seconds = ttl_seconds

    async def resolve_prompt(self, prompt_key: PromptKey) -> ResolvedPrompt:
        cached = self._cache.get(prompt_key)
        if cached is not None:
            return cached
        prompt = await self._resolve_uncached(prompt_key)
        return self._cache.set(prompt, ttl_seconds=self._ttl_seconds)

    async def resolve_prompt_version(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        if version_id is None:
            return fallback_prompt(prompt_key)
        record = await self._repository.get_version(prompt_key, version_id)
        if record is None:
            raise PromptNotFound("Prompt version not found.")
        return _resolved_from_record(record)

    async def _resolve_uncached(self, prompt_key: PromptKey) -> ResolvedPrompt:
        record = await self._repository.get_active_version(prompt_key)
        if record is None:
            return fallback_prompt(prompt_key)
        return _resolved_from_record(record)


class ListPromptsUseCase:
    def __init__(self, repository: PromptRepositoryPort, resolver: PromptResolver) -> None:
        self._repository = repository
        self._resolver = resolver

    async def execute(self) -> list[PromptSummaryResponse]:
        responses: list[PromptSummaryResponse] = []
        for prompt_key in KNOWN_PROMPT_KEYS:
            versions = await self._repository.list_versions(prompt_key)
            responses.append(
                PromptSummaryResponse(
                    key=prompt_key,
                    active=_prompt_body_response(
                        await self._resolver.resolve_prompt(prompt_key)
                    ),
                    versionCount=len(versions),
                )
            )
        return responses


class GetPromptUseCase:
    def __init__(self, repository: PromptRepositoryPort, resolver: PromptResolver) -> None:
        self._repository = repository
        self._resolver = resolver

    async def execute(self, prompt_key: PromptKey) -> PromptDetailResponse:
        versions = await self._repository.list_versions(prompt_key)
        active = await self._resolver.resolve_prompt(prompt_key)
        return PromptDetailResponse(
            key=prompt_key,
            active=_prompt_body_response(active),
            versions=_version_responses(versions, active_version_id=active.version_id),
        )


class CreatePromptVersionUseCase:
    def __init__(self, repository: PromptRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        prompt_key: PromptKey,
        request: PromptVersionCreateRequest,
    ) -> PromptVersionResponse:
        record = await self._repository.create_version(
            PromptVersionCreate(
                prompt_key=prompt_key,
                version_label=request.version_label.strip(),
                body=request.body,
                body_sha256=_sha256(request.body),
                source_note=request.source_note,
            )
        )
        return _version_response(record, active_version_id=None)


class UpdatePromptVersionUseCase:
    def __init__(self, repository: PromptRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        prompt_key: PromptKey,
        version_id: int,
        request: PromptVersionUpdateRequest,
    ) -> PromptVersionResponse:
        update = PromptVersionUpdate(
            body=request.body,
            body_sha256=_sha256(request.body) if request.body is not None else None,
            body_set=request.body is not None,
            source_note=request.source_note,
            source_note_set="source_note" in request.model_fields_set,
        )
        record = await self._repository.update_draft(prompt_key, version_id, update)
        if record is None:
            raise PromptNotFound("Prompt draft version not found.")
        return _version_response(record, active_version_id=None)


class PublishPromptVersionUseCase:
    def __init__(self, repository: PromptRepositoryPort, cache: PromptCache) -> None:
        self._repository = repository
        self._cache = cache

    async def execute(self, prompt_key: PromptKey, version_id: int) -> PromptVersionResponse:
        record = await self._repository.publish_version(prompt_key, version_id)
        if record is None:
            raise PromptNotFound("Prompt version not found.")
        self._cache.invalidate(prompt_key)
        return _version_response(record, active_version_id=record.id)


class ArchivePromptVersionUseCase:
    def __init__(self, repository: PromptRepositoryPort, cache: PromptCache) -> None:
        self._repository = repository
        self._cache = cache

    async def execute(self, prompt_key: PromptKey, version_id: int) -> PromptVersionResponse:
        record = await self._repository.archive_version(prompt_key, version_id)
        if record is None:
            raise PromptNotFound("Prompt version not found.")
        self._cache.invalidate(prompt_key)
        return _version_response(record, active_version_id=None)


class InvalidatePromptCacheUseCase:
    def __init__(self, cache: PromptCache) -> None:
        self._cache = cache

    async def execute(
        self,
        request: PromptCacheInvalidateRequest,
    ) -> PromptCacheInvalidateResponse:
        return PromptCacheInvalidateResponse(
            invalidatedCount=self._cache.invalidate(request.prompt_key)
        )


def ensure_known_prompt_key(prompt_key: PromptKey) -> None:
    if prompt_key not in KNOWN_PROMPT_KEYS:
        raise PromptInvalid(f"Unknown prompt key: {prompt_key}")


def _resolved_from_record(record: PromptVersionRecord) -> ResolvedPrompt:
    return ResolvedPrompt(
        key=record.prompt_key,
        version_id=record.id,
        version_label=record.version_label,
        body=record.body,
        body_sha256=record.body_sha256,
        source="database",
    )


def _prompt_body_response(prompt: ResolvedPrompt) -> PromptBodyResponse:
    return PromptBodyResponse(
        key=prompt.key,
        versionId=prompt.version_id,
        versionLabel=prompt.version_label,
        body=prompt.body,
        bodySha256=prompt.body_sha256,
        source=prompt.source,
    )


def _version_responses(
    records: list[PromptVersionRecord],
    *,
    active_version_id: int | None,
) -> list[PromptVersionResponse]:
    return [
        _version_response(record, active_version_id=active_version_id)
        for record in records
    ]


def _version_response(
    record: PromptVersionRecord,
    *,
    active_version_id: int | None,
) -> PromptVersionResponse:
    return PromptVersionResponse(
        id=record.id,
        promptKey=record.prompt_key,
        versionLabel=record.version_label,
        bodySha256=record.body_sha256,
        status=record.status,
        sourceNote=record.source_note,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
        publishedAt=record.published_at,
        archivedAt=record.archived_at,
        isActive=record.id == active_version_id,
    )


def _sha256(body: str) -> str:
    if not body.strip():
        raise PromptInvalid("Prompt body cannot be blank.")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
