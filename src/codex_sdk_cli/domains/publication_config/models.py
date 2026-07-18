from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PublishMode = Literal["prod", "dev"]
PublishProfileRevisionState = Literal["draft", "active", "retired"]


@dataclass(frozen=True, slots=True)
class PublishObjectDestination:
    id: int
    key: str
    name: str
    connection_ref: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublishCatalogDestination:
    id: int
    key: str
    name: str
    connection_ref: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublishRouteObjectBinding:
    id: int
    destination_id: int
    destination_key: str
    connection_ref: str
    key_prefix: str
    required: bool
    is_primary: bool


@dataclass(frozen=True, slots=True)
class PublishRouteCatalogBinding:
    id: int
    destination_id: int
    destination_key: str
    connection_ref: str
    source_object_binding_id: int
    required: bool


@dataclass(frozen=True, slots=True)
class PublishProfileRoute:
    id: int
    publish_mode: PublishMode
    environment: str
    object_bindings: tuple[PublishRouteObjectBinding, ...]
    catalog_bindings: tuple[PublishRouteCatalogBinding, ...]


@dataclass(frozen=True, slots=True)
class PublishProfileRevision:
    id: int
    profile_id: int
    revision_number: int
    state: PublishProfileRevisionState
    created_at: datetime
    activated_at: datetime | None
    routes: tuple[PublishProfileRoute, ...]


@dataclass(frozen=True, slots=True)
class PublishProfile:
    id: int
    key: str
    name: str
    description: str | None
    active_revision_id: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublishProfileDetail:
    profile: PublishProfile
    revisions: tuple[PublishProfileRevision, ...]
