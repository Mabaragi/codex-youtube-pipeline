from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .constants import PromptKey, PromptSource, PromptStatus


@dataclass(frozen=True, slots=True)
class PromptVersionRecord:
    id: int
    prompt_key: PromptKey
    version_label: str
    body: str
    body_sha256: str
    status: PromptStatus
    source_note: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class PromptVersionCreate:
    prompt_key: PromptKey
    version_label: str
    body: str
    body_sha256: str
    source_note: str | None = None


@dataclass(frozen=True, slots=True)
class PromptVersionUpdate:
    body: str | None = None
    body_sha256: str | None = None
    body_set: bool = False
    source_note: str | None = None
    source_note_set: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    key: PromptKey
    version_id: int | None
    version_label: str
    body: str
    body_sha256: str
    source: PromptSource


class PromptRepositoryPort(Protocol):
    async def list_versions(self, prompt_key: PromptKey) -> list[PromptVersionRecord]:
        """List versions for one prompt key."""

    async def get_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        """Return one version for one prompt key."""

    async def get_active_version(
        self,
        prompt_key: PromptKey,
    ) -> PromptVersionRecord | None:
        """Return active published version for one prompt key."""

    async def create_version(
        self,
        create: PromptVersionCreate,
    ) -> PromptVersionRecord:
        """Create a draft version."""

    async def update_draft(
        self,
        prompt_key: PromptKey,
        version_id: int,
        update: PromptVersionUpdate,
    ) -> PromptVersionRecord | None:
        """Update a draft version."""

    async def publish_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        """Publish a draft/published version and make it active."""

    async def archive_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        """Archive a draft or inactive published version."""


class PromptResolverPort(Protocol):
    async def resolve_prompt(self, prompt_key: PromptKey) -> ResolvedPrompt:
        """Resolve active DB prompt or fallback prompt."""

    async def resolve_prompt_for_request(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        """Resolve a request-selected prompt; explicit versions must be published."""

    async def resolve_prompt_version(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        """Resolve an exact DB prompt version, or fallback when version id is None."""
