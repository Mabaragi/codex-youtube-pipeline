from __future__ import annotations

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind


class PublicationStagePreconditionFailed(ApplicationError):
    def __init__(self, *, stage: str, missing: list[dict[str, object]]) -> None:
        super().__init__(
            code="publication.stage_precondition_failed",
            message=f"Publication stage '{stage}' is missing required predecessor state.",
            kind=ErrorKind.CONFLICT,
            details={"stage": stage, "missingPreconditions": missing},
        )


class PublicationRouteNotFound(ApplicationError):
    def __init__(
        self,
        *,
        publish_mode: str,
        environment: str,
        profile_revision_id: int | None = None,
        streamer_id: int | None = None,
    ) -> None:
        details: dict[str, object] = {
            "publishMode": publish_mode,
            "environment": environment,
        }
        if profile_revision_id is not None:
            details["profileRevisionId"] = profile_revision_id
        if streamer_id is not None:
            details["streamerId"] = streamer_id
        super().__init__(
            code="publication.route_not_found",
            message="No active publication route matches the requested scope.",
            kind=ErrorKind.CONFLICT,
            details=details,
        )


class PublicationStageUnavailable(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="publication.stage_unavailable",
            message=message,
            kind=ErrorKind.UNAVAILABLE,
        )


class PublicationCutoverNotFound(ApplicationError):
    def __init__(self, cutover_id: int) -> None:
        super().__init__(
            code="publication.cutover_not_found",
            message="Publication cutover was not found.",
            kind=ErrorKind.NOT_FOUND,
            details={"cutoverId": cutover_id},
        )


class PublicationCutoverConflict(ApplicationError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="publication.cutover_conflict",
            message=message,
            kind=ErrorKind.CONFLICT,
            details=details,
        )


class PublicationCutoverStepFailed(ApplicationError):
    def __init__(
        self,
        *,
        cutover_id: int,
        step: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code="publication.cutover_step_failed",
            message=message,
            kind=ErrorKind.UPSTREAM,
            details={"cutoverId": cutover_id, "step": step, **(details or {})},
        )
