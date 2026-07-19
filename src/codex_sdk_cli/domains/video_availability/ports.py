from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeAlias

CandidateId: TypeAlias = int | str
AvailabilityOutcome = Literal["available", "unavailable", "retry"]


@dataclass(frozen=True, slots=True)
class VideoAvailabilityCandidate:
    candidate_id: CandidateId
    lease_token: str
    environment: str
    video_id: int
    youtube_video_id: str


@dataclass(frozen=True, slots=True)
class VideoAvailabilityResolution:
    candidate_id: CandidateId
    lease_token: str
    outcome: AvailabilityOutcome
    reason: str
    checked_at: datetime


class VideoAvailabilityCandidateInboxPort(Protocol):
    async def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[VideoAvailabilityCandidate, ...]:
        """Claim due candidates from the remote durable inbox."""

    async def resolve(
        self,
        resolutions: tuple[VideoAvailabilityResolution, ...],
    ) -> None:
        """Acknowledge candidate outcomes while their leases are owned."""

    async def cleanup(self) -> int:
        """Recover expired claims and due retries without scanning all videos."""


class VideoPendingWorkCancelerPort(Protocol):
    async def execute(
        self,
        *,
        subject_type: str,
        subject_id: int,
        task_types: tuple[str, ...],
        outcome_code: str,
        reason: str,
    ) -> int:
        """Cancel pending unified work for a video."""
