from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PublicationStageName = Literal[
    "artifactBuild",
    "objectDeliver",
    "catalogPublish",
    "publicationBuild",
    "pointerPublish",
]
PublicationStageStatus = Literal["succeeded", "succeededWithWarnings", "failed"]


@dataclass(frozen=True, slots=True)
class PublicationMembershipAuthorization:
    purpose: Literal["cutover_target"]
    cutover_id: int
    streamer_id: int
    source_profile_id: int
    target_profile_id: int
    artifact_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PublicationDestinationResult:
    destination_id: int
    binding_id: int
    destination_type: Literal["object", "catalog"]
    required: bool
    status: str
    reused: bool = False
    public_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationStageResult:
    stage: PublicationStageName
    status: PublicationStageStatus
    artifact_ids: tuple[int, ...] = ()
    profile_revision_id: int | None = None
    route_id: int | None = None
    publication_id: int | None = None
    destination_results: tuple[PublicationDestinationResult, ...] = ()
    missing_preconditions: tuple[dict[str, object], ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
