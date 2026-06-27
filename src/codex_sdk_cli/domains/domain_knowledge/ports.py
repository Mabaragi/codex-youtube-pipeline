from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

PromptPolicy = Literal["AUTO_ON_MATCH", "ALWAYS_FOR_SCOPED_STREAMER", "DISABLED"]
AliasKind = Literal[
    "ALIAS",
    "ASR_ERROR",
    "SEARCH_ALIAS",
    "NICKNAME",
    "WORDPLAY",
    "MISSPELLING",
]
Certainty = Literal["LOW", "MEDIUM", "HIGH"]
ApplyScope = Literal[
    "NONE",
    "SEARCH_ONLY",
    "SEARCH_AND_SUMMARY",
    "DISPLAY_ALLOWED",
]


@dataclass(frozen=True, slots=True)
class DomainEntryTypeRecord:
    id: int
    key: str
    label: str
    description: str | None
    sort_order: int
    is_system: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DomainEntryStreamerRecord:
    streamer_id: int
    streamer_name: str
    relevance: str | None
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DomainEntryAliasRecord:
    id: int
    entry_id: int
    surface_form: str
    alias_kind: AliasKind
    certainty: Certainty
    apply_scope: ApplyScope
    language_code: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DomainEntryRecord:
    id: int
    type_id: int
    type_key: str
    type_label: str
    canonical_name: str
    display_name: str | None
    disambiguation: str | None
    detail: str | None
    prompt_policy: PromptPolicy
    priority: int
    is_active: bool
    source_note: str | None
    created_at: datetime
    updated_at: datetime
    streamers: list[DomainEntryStreamerRecord] = field(default_factory=list)
    aliases: list[DomainEntryAliasRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DomainEntryTypeCreate:
    key: str | None
    label: str
    description: str | None = None
    sort_order: int = 100
    is_system: bool = False


@dataclass(frozen=True, slots=True)
class DomainEntryAliasCreate:
    surface_form: str
    alias_kind: AliasKind = "ALIAS"
    certainty: Certainty = "MEDIUM"
    apply_scope: ApplyScope = "SEARCH_ONLY"
    language_code: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DomainEntryStreamerLinkCreate:
    streamer_id: int
    relevance: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DomainEntryCreate:
    type_id: int
    canonical_name: str
    display_name: str | None = None
    disambiguation: str | None = None
    detail: str | None = None
    prompt_policy: PromptPolicy = "AUTO_ON_MATCH"
    priority: int = 50
    is_active: bool = True
    source_note: str | None = None
    streamer_links: list[DomainEntryStreamerLinkCreate] = field(default_factory=list)
    aliases: list[DomainEntryAliasCreate] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DomainEntryUpdate:
    type_id: int | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    display_name_set: bool = False
    disambiguation: str | None = None
    disambiguation_set: bool = False
    detail: str | None = None
    detail_set: bool = False
    prompt_policy: PromptPolicy | None = None
    priority: int | None = None
    is_active: bool | None = None
    source_note: str | None = None
    source_note_set: bool = False


@dataclass(frozen=True, slots=True)
class DomainEntryAliasUpdate:
    surface_form: str | None = None
    alias_kind: AliasKind | None = None
    certainty: Certainty | None = None
    apply_scope: ApplyScope | None = None
    language_code: str | None = None
    language_code_set: bool = False
    note: str | None = None
    note_set: bool = False


@dataclass(frozen=True, slots=True)
class DomainEntryListQuery:
    streamer_id: int | None = None
    type_id: int | None = None
    q: str | None = None
    active: bool | None = True
    limit: int = 200


@dataclass(frozen=True, slots=True)
class DomainKnowledgePromptAliasRecord:
    surface_form: str
    alias_kind: AliasKind
    certainty: Certainty
    apply_scope: ApplyScope
    language_code: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class DomainKnowledgePromptEntryRecord:
    entry_id: int
    type_key: str
    type_label: str
    canonical_name: str
    display_name: str | None
    disambiguation: str | None
    detail: str | None
    prompt_policy: PromptPolicy
    priority: int
    aliases: list[DomainKnowledgePromptAliasRecord] = field(default_factory=list)


class DomainKnowledgeRepositoryPort(Protocol):
    async def list_types(self) -> list[DomainEntryTypeRecord]:
        """List domain entry types."""

    async def create_type(self, create: DomainEntryTypeCreate) -> DomainEntryTypeRecord:
        """Create one type."""

    async def get_or_create_type(
        self,
        create: DomainEntryTypeCreate,
    ) -> DomainEntryTypeRecord:
        """Return an existing type or create it."""

    async def get_type(self, type_id: int) -> DomainEntryTypeRecord | None:
        """Return one type by id."""

    async def list_entries(
        self,
        query: DomainEntryListQuery,
    ) -> list[DomainEntryRecord]:
        """List domain entries."""

    async def get_entry(self, entry_id: int) -> DomainEntryRecord | None:
        """Return one entry with streamers and aliases."""

    async def create_entry(self, create: DomainEntryCreate) -> DomainEntryRecord:
        """Create one entry with links and aliases."""

    async def update_entry(
        self,
        entry_id: int,
        update: DomainEntryUpdate,
    ) -> DomainEntryRecord | None:
        """Update one entry."""

    async def archive_entry(self, entry_id: int) -> DomainEntryRecord | None:
        """Soft-delete one entry."""

    async def add_streamer_link(
        self,
        entry_id: int,
        link: DomainEntryStreamerLinkCreate,
    ) -> DomainEntryRecord | None:
        """Link one entry to one streamer."""

    async def remove_streamer_link(self, entry_id: int, streamer_id: int) -> bool:
        """Remove one streamer link."""

    async def add_alias(
        self,
        entry_id: int,
        alias: DomainEntryAliasCreate,
    ) -> DomainEntryRecord | None:
        """Add one alias to an entry."""

    async def update_alias(
        self,
        alias_id: int,
        update: DomainEntryAliasUpdate,
    ) -> DomainEntryAliasRecord | None:
        """Update one alias."""

    async def delete_alias(self, alias_id: int) -> bool:
        """Delete one alias."""

    async def list_prompt_entries_for_streamer(
        self,
        streamer_id: int | None,
    ) -> list[DomainKnowledgePromptEntryRecord]:
        """Return active entries relevant to a streamer and global active entries."""
