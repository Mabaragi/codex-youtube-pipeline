from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from codex_sdk_cli.domains.archive_publish.constants import ARCHIVE_PUBLISH_TASK_NAME
from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.video_availability.ports import (
    AvailabilityOutcome,
    VideoAvailabilityCandidateInboxPort,
    VideoAvailabilityResolution,
    VideoPendingWorkCancelerPort,
)
from codex_sdk_cli.domains.video_tasks.constants import (
    TIMELINE_COMPOSE_TASK_NAME,
    TRANSCRIPT_COLLECT_TASK_NAME,
    TRANSCRIPT_CUE_GENERATE_TASK_NAME,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.ports import YouTubeDataClientPort

_DOWNSTREAM_TASK_NAMES = (
    TRANSCRIPT_COLLECT_TASK_NAME,
    TRANSCRIPT_CUE_GENERATE_TASK_NAME,
    MICRO_EVENT_EXTRACT_TASK_NAME,
    TIMELINE_COMPOSE_TASK_NAME,
    ARCHIVE_PUBLISH_TASK_NAME,
)


@dataclass(frozen=True, slots=True)
class VideoAvailabilityCheckResult:
    youtube_video_id: str
    video_id: int | None
    outcome: AvailabilityOutcome
    reason: str
    is_embeddable: bool | None
    source_api_call_id: int | None
    canceled_pending_task_count: int
    checked_at: datetime
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessVideoAvailabilityCandidatesResult:
    claimed_count: int
    available_count: int
    unavailable_count: int
    retry_count: int


class VerifyVideoAvailabilityUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pending_work: VideoPendingWorkCancelerPort,
        youtube_data: YouTubeDataClientPort,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._pending_work = pending_work
        self._youtube_data = youtube_data
        self._events = events

    async def execute(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        actor_type: OperationEventActorType,
        source: str,
    ) -> tuple[VideoAvailabilityCheckResult, ...]:
        if not youtube_video_ids:
            return ()
        checked_at = datetime.now(UTC)
        event_type = (
            "video.embed_status_refreshed"
            if actor_type == "manual_api"
            else "video.availability_checked"
        )
        try:
            details = await self._youtube_data.get_video_details(youtube_video_ids)
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            return tuple(
                VideoAvailabilityCheckResult(
                    youtube_video_id=youtube_video_id,
                    video_id=None,
                    outcome="retry",
                    reason="youtube_api_error",
                    is_embeddable=None,
                    source_api_call_id=None,
                    canceled_pending_task_count=0,
                    checked_at=checked_at,
                    error_type=error_type,
                    error_message=error_message,
                )
                for youtube_video_id in youtube_video_ids
            )

        details_by_id = {item.youtube_video_id: item for item in details.videos}
        results: list[VideoAvailabilityCheckResult] = []
        for youtube_video_id in youtube_video_ids:
            detail = details_by_id.get(youtube_video_id)
            if detail is None:
                outcome: AvailabilityOutcome = "unavailable"
                reason = "not_returned"
                is_embeddable: bool | None = False
                source_api_call_id = details.source_api_call_id
            elif detail.is_embeddable is False:
                outcome = "unavailable"
                reason = "not_embeddable"
                is_embeddable = False
                source_api_call_id = detail.source_api_call_id
            elif detail.is_embeddable is True:
                outcome = "available"
                reason = "available"
                is_embeddable = True
                source_api_call_id = detail.source_api_call_id
            else:
                results.append(
                    VideoAvailabilityCheckResult(
                        youtube_video_id=youtube_video_id,
                        video_id=None,
                        outcome="retry",
                        reason="embed_status_missing",
                        is_embeddable=None,
                        source_api_call_id=detail.source_api_call_id,
                        canceled_pending_task_count=0,
                        checked_at=checked_at,
                        error_type="YouTubeEmbedStatusMissing",
                        error_message="YouTube videos.list returned no embeddable status.",
                    )
                )
                continue

            assert is_embeddable is not None
            try:
                result = await self._apply_result(
                    youtube_video_id=youtube_video_id,
                    outcome=outcome,
                    reason=reason,
                    is_embeddable=is_embeddable,
                    source_api_call_id=source_api_call_id,
                    checked_at=checked_at,
                    actor_type=actor_type,
                    source=source,
                    event_type=event_type,
                )
            except Exception as exc:
                error_type = exc.__class__.__name__
                results.append(
                    VideoAvailabilityCheckResult(
                        youtube_video_id=youtube_video_id,
                        video_id=None,
                        outcome="retry",
                        reason="local_update_error",
                        is_embeddable=is_embeddable,
                        source_api_call_id=source_api_call_id,
                        canceled_pending_task_count=0,
                        checked_at=checked_at,
                        error_type=error_type,
                        error_message=str(exc) or error_type,
                    )
                )
            else:
                results.append(result)
        return tuple(results)

    async def _apply_result(
        self,
        *,
        youtube_video_id: str,
        outcome: AvailabilityOutcome,
        reason: str,
        is_embeddable: bool,
        source_api_call_id: int | None,
        checked_at: datetime,
        actor_type: OperationEventActorType,
        source: str,
        event_type: str,
    ) -> VideoAvailabilityCheckResult:
        video = await self._videos.get_video_by_youtube_video_id(youtube_video_id)
        canceled_count = 0
        updated = None
        if video is not None:
            updated = await self._videos.update_embed_status(
                video.id,
                is_embeddable=is_embeddable,
                checked_at=checked_at,
                source_api_call_id=source_api_call_id,
            )
            if outcome == "unavailable":
                cancellation_reason = (
                    f"YouTube video is unavailable ({reason}); downstream work was canceled."
                )
                canceled_tasks = await self._video_tasks.cancel_pending_tasks_for_video(
                    video_id=updated.id,
                    task_names=_DOWNSTREAM_TASK_NAMES,
                    error_type="VideoUnavailable",
                    error_message=cancellation_reason,
                )
                canceled_work_count = await self._pending_work.execute(
                    subject_type="video",
                    subject_id=updated.id,
                    task_types=_DOWNSTREAM_TASK_NAMES,
                    outcome_code=reason,
                    reason=cancellation_reason,
                )
                canceled_count = max(len(canceled_tasks), canceled_work_count)

        local_video_id = updated.id if updated is not None else None
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity="warning" if outcome == "unavailable" else "info",
                message="Video availability was verified with YouTube videos.list.",
                actor_type=actor_type,
                source=source,
                video_id=local_video_id,
                external_api_call_id=source_api_call_id,
                subject_type="video" if local_video_id is not None else None,
                subject_id=local_video_id,
                external_key=youtube_video_id,
                metadata_json={
                    "outcome": outcome,
                    "reason": reason,
                    "isEmbeddable": is_embeddable,
                    "sourceApiCallId": source_api_call_id,
                    "localVideoFound": local_video_id is not None,
                    "canceledPendingTaskCount": canceled_count,
                },
            ),
        )
        return VideoAvailabilityCheckResult(
            youtube_video_id=youtube_video_id,
            video_id=local_video_id,
            outcome=outcome,
            reason=reason,
            is_embeddable=is_embeddable,
            source_api_call_id=source_api_call_id,
            canceled_pending_task_count=canceled_count,
            checked_at=checked_at,
        )


class ProcessVideoAvailabilityCandidatesUseCase:
    def __init__(
        self,
        *,
        inbox: VideoAvailabilityCandidateInboxPort,
        verifier: VerifyVideoAvailabilityUseCase,
        worker_id: str,
        claim_limit: int,
        lease_seconds: int,
    ) -> None:
        self._inbox = inbox
        self._verifier = verifier
        self._worker_id = worker_id
        self._claim_limit = claim_limit
        self._lease_seconds = lease_seconds

    async def execute_once(self) -> ProcessVideoAvailabilityCandidatesResult:
        candidates = await self._inbox.claim(
            worker_id=self._worker_id,
            limit=self._claim_limit,
            lease_seconds=self._lease_seconds,
        )
        if not candidates:
            return ProcessVideoAvailabilityCandidatesResult(0, 0, 0, 0)

        checks = await self._verifier.execute(
            tuple(candidate.youtube_video_id for candidate in candidates),
            actor_type="system",
            source="video_availability.worker",
        )
        checks_by_id = {check.youtube_video_id: check for check in checks}
        resolutions = tuple(
            VideoAvailabilityResolution(
                candidate_id=candidate.candidate_id,
                lease_token=candidate.lease_token,
                outcome=checks_by_id[candidate.youtube_video_id].outcome,
                reason=checks_by_id[candidate.youtube_video_id].reason,
                checked_at=checks_by_id[candidate.youtube_video_id].checked_at,
            )
            for candidate in candidates
        )
        await self._inbox.resolve(resolutions)
        return ProcessVideoAvailabilityCandidatesResult(
            claimed_count=len(candidates),
            available_count=sum(1 for item in resolutions if item.outcome == "available"),
            unavailable_count=sum(
                1 for item in resolutions if item.outcome == "unavailable"
            ),
            retry_count=sum(1 for item in resolutions if item.outcome == "retry"),
        )
