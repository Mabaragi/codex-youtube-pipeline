from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    exists,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.application.scheduler.ports import (
    AutomationScheduleState,
    AutomationScheduleStatePort,
)
from codex_sdk_cli.domains.automation.ports import (
    AutomationCandidateReaderPort,
    FailureCandidate,
    IncidentRecord,
    IncidentRepositoryPort,
    IncidentState,
    IncidentUpsert,
    OrphanVideoCandidate,
    QueueStallCandidate,
    RemediationAction,
    RuntimeAuditPort,
    RuntimeControlPort,
    RuntimeMode,
    RuntimeState,
    RuntimeTaskCount,
    RuntimeTransition,
    SafeRemediationPort,
    SlaBreachCandidate,
    StallCandidate,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.operation_events.recorder import BestEffortOperationEventRecorder
from codex_sdk_cli.domains.work.models import JsonObject
from codex_sdk_cli.infra.asr.checkpoints import AsrChunkCheckpointModel
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.micro_events.repository import MicroEventExtractionWindowModel
from codex_sdk_cli.infra.operation_events.repository import SQLAlchemyOperationEventRepository
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.work.models import (
    WorkAttemptModel,
    WorkflowRunModel,
    WorkflowStepModel,
    WorkItemModel,
)
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


class PipelineIncidentModel(Base):
    __tablename__ = "pipeline_incidents"
    __table_args__ = (
        CheckConstraint(
            "state IN ('open', 'acknowledged', 'resolved', 'suppressed')",
            name="pipeline_incidents_state_allowed",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error', 'critical')",
            name="pipeline_incidents_severity_allowed",
        ),
        Index("ix_pipeline_incidents_state_seen", "state", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineRemediationActionModel(Base):
    __tablename__ = "pipeline_remediation_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_pipeline_remediation_action_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parameters_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    result_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineRuntimeControlModel(Base):
    __tablename__ = "pipeline_runtime_controls"

    task_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PipelineAutomationStateModel(Base):
    __tablename__ = "pipeline_automation_state"
    __table_args__ = (
        CheckConstraint(
            "runtime_state IN ('active', 'draining', 'stopped')",
            name="pipeline_automation_runtime_state_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    backfill_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    steady_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    runtime_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    drain_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drain_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SqlAlchemyAutomationRepository(
    IncidentRepositoryPort,
    AutomationCandidateReaderPort,
    AutomationScheduleStatePort,
    RuntimeControlPort,
    RuntimeAuditPort,
):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def list_incidents(
        self, *, state: IncidentState | None, limit: int
    ) -> list[IncidentRecord]:
        async with self._session_factory() as session:
            statement = select(PipelineIncidentModel)
            if state is not None:
                statement = statement.where(PipelineIncidentModel.state == state)
            models = list(
                (
                    await session.scalars(
                        statement.order_by(PipelineIncidentModel.last_seen_at.desc()).limit(limit)
                    )
                ).all()
            )
        return [_incident(model) for model in models]

    @override
    async def get(self, incident_id: int) -> IncidentRecord | None:
        async with self._session_factory() as session:
            model = await session.get(PipelineIncidentModel, incident_id)
        return _incident(model) if model is not None else None

    @override
    async def upsert(self, incident: IncidentUpsert) -> IncidentRecord:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(PipelineIncidentModel).where(
                    PipelineIncidentModel.fingerprint == incident.fingerprint
                )
            )
            if model is None:
                model = PipelineIncidentModel(
                    fingerprint=incident.fingerprint,
                    incident_type=incident.incident_type,
                    severity=incident.severity,
                    state=incident.state,
                    work_item_id=incident.work_item_id,
                    workflow_run_id=incident.workflow_run_id,
                    task_type=incident.task_type,
                    error_type=incident.error_type,
                    error_message=incident.error_message,
                    metadata_json=incident.metadata_json,
                    occurrence_count=1,
                    first_seen_at=incident.seen_at,
                    last_seen_at=incident.seen_at,
                )
                session.add(model)
            else:
                model.severity = incident.severity
                if model.state not in {"resolved", "suppressed"}:
                    model.state = incident.state
                model.error_type = incident.error_type
                model.error_message = incident.error_message
                model.metadata_json = incident.metadata_json
                model.occurrence_count += 1
                model.last_seen_at = incident.seen_at
            await session.commit()
            await session.refresh(model)
            return _incident(model)

    @override
    async def set_state(
        self,
        incident_id: int,
        *,
        state: IncidentState,
        note: str | None,
        now: datetime,
    ) -> IncidentRecord | None:
        async with self._session_factory() as session:
            model = await session.get(PipelineIncidentModel, incident_id)
            if model is None:
                return None
            model.state = state
            model.note = note
            model.resolved_at = now if state == "resolved" else None
            await session.commit()
            await session.refresh(model)
            return _incident(model)

    @override
    async def record_action(
        self,
        *,
        incident_id: int,
        action: RemediationAction,
        idempotency_key: str,
        parameters: JsonObject,
        result: JsonObject,
        now: datetime,
    ) -> None:
        del now
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(PipelineRemediationActionModel.id).where(
                    PipelineRemediationActionModel.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return
            session.add(
                PipelineRemediationActionModel(
                    incident_id=incident_id,
                    action=action,
                    idempotency_key=idempotency_key,
                    parameters_json=parameters,
                    result_json=result,
                )
            )
            await session.commit()

    @override
    async def action_result(self, *, idempotency_key: str) -> JsonObject | None:
        async with self._session_factory() as session:
            result = await session.scalar(
                select(PipelineRemediationActionModel.result_json).where(
                    PipelineRemediationActionModel.idempotency_key == idempotency_key
                )
            )
        return result

    @override
    async def resolve_recovered(self, *, now: datetime) -> int:
        async with self._session_factory() as session:
            models = list(
                (
                    await session.scalars(
                        select(PipelineIncidentModel)
                        .join(
                            WorkItemModel,
                            WorkItemModel.id == PipelineIncidentModel.work_item_id,
                        )
                        .where(
                            PipelineIncidentModel.state.in_(("open", "acknowledged")),
                            WorkItemModel.status == "succeeded",
                        )
                    )
                ).all()
            )
            completed_workflows = list(
                (
                    await session.scalars(
                        select(PipelineIncidentModel)
                        .join(
                            WorkflowRunModel,
                            WorkflowRunModel.id == PipelineIncidentModel.workflow_run_id,
                        )
                        .where(
                            PipelineIncidentModel.state.in_(("open", "acknowledged")),
                            PipelineIncidentModel.incident_type == "sla_breach",
                            WorkflowRunModel.status == "succeeded",
                        )
                    )
                ).all()
            )
            models = list({model.id: model for model in [*models, *completed_workflows]}.values())
            for model in models:
                model.state = "resolved"
                model.resolved_at = now
            await session.commit()
        return len(models)

    @override
    async def resolve_backfill_sla(self, *, now: datetime) -> int:
        async with self._session_factory() as session:
            models = list(
                (
                    await session.scalars(
                        select(PipelineIncidentModel)
                        .join(
                            WorkflowRunModel,
                            WorkflowRunModel.id == PipelineIncidentModel.workflow_run_id,
                        )
                        .where(
                            PipelineIncidentModel.state.in_(("open", "acknowledged")),
                            PipelineIncidentModel.incident_type == "sla_breach",
                            WorkflowRunModel.options_json["automation_mode"].as_string()
                            == "backfill",
                        )
                    )
                ).all()
            )
            for model in models:
                model.state = "resolved"
                model.resolved_at = now
            await session.commit()
        return len(models)

    @override
    async def failures(self, *, limit: int) -> list[FailureCandidate]:
        async with self._session_factory() as session:
            attempt_count = (
                select(func.count(WorkAttemptModel.id))
                .where(WorkAttemptModel.work_item_id == WorkItemModel.id)
                .correlate(WorkItemModel)
                .scalar_subquery()
            )
            rows = (
                await session.execute(
                    select(WorkItemModel, attempt_count.label("attempt_count"))
                    .where(WorkItemModel.status.in_(("failed", "timed_out")))
                    .order_by(WorkItemModel.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            FailureCandidate(
                work_item_id=model.id,
                task_type=model.task_type,
                status=model.status,
                error_code=model.error_code,
                error_type=model.error_type,
                error_message=model.error_message,
                attempt_count=count,
                updated_at=model.updated_at,
            )
            for model, count in rows
        ]

    @override
    async def sla_breaches(self, *, now: datetime, limit: int) -> list[SlaBreachCandidate]:
        async with self._session_factory() as session:
            workflows = list(
                (
                    await session.scalars(
                        select(WorkflowRunModel)
                        .where(WorkflowRunModel.status.in_(("pending", "running", "waiting")))
                        .order_by(WorkflowRunModel.id.asc())
                        .limit(limit)
                    )
                ).all()
            )
            asr_workflow_ids = (
                set(
                    (
                        await session.scalars(
                            select(WorkflowStepModel.workflow_run_id).where(
                                WorkflowStepModel.stage_name == "asr_transcribe",
                                WorkflowStepModel.workflow_run_id.in_(
                                    [item.id for item in workflows]
                                ),
                            )
                        )
                    ).all()
                )
                if workflows
                else set()
            )
        result: list[SlaBreachCandidate] = []
        for workflow in workflows:
            if workflow.options_json.get("automation_mode") == "backfill":
                continue
            deadline_key = (
                "asrSlaDeadline" if workflow.id in asr_workflow_ids else "captionSlaDeadline"
            )
            deadline = _json_datetime(workflow.options_json.get(deadline_key))
            if deadline is not None and deadline < now:
                result.append(
                    SlaBreachCandidate(
                        workflow_run_id=workflow.id,
                        video_id=workflow.video_id,
                        current_stage=workflow.current_stage,
                        deadline=deadline,
                        observed_at=now,
                    )
                )
        return result

    @override
    async def stalls(self, *, now: datetime, limit: int) -> list[StallCandidate]:
        cutoff = now - timedelta(minutes=30)
        async with self._session_factory() as session:
            running = list(
                (
                    await session.scalars(
                        select(WorkItemModel).where(
                            WorkItemModel.status == "running",
                            WorkItemModel.task_type.in_(("asr_transcribe", "micro_event_extract")),
                        )
                    )
                ).all()
            )
            result: list[StallCandidate] = []
            for item in running[:limit]:
                if item.task_type == "asr_transcribe":
                    progress = await session.scalar(
                        select(func.max(AsrChunkCheckpointModel.updated_at)).where(
                            AsrChunkCheckpointModel.work_item_id == item.id
                        )
                    )
                else:
                    progress = await session.scalar(
                        select(func.max(MicroEventExtractionWindowModel.updated_at)).where(
                            MicroEventExtractionWindowModel.video_task_id == item.id
                        )
                    )
                last_progress = progress or item.started_at or item.updated_at
                aware_progress = _aware(last_progress)
                if aware_progress < cutoff:
                    result.append(
                        StallCandidate(
                            work_item_id=item.id,
                            task_type=item.task_type,
                            last_progress_at=aware_progress,
                            observed_at=now,
                        )
                    )
        return result

    @override
    async def queue_stalls(self, *, now: datetime, limit: int) -> list[QueueStallCandidate]:
        cutoff = now - timedelta(minutes=30)
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        WorkItemModel.task_type,
                        func.count(WorkItemModel.id),
                        func.min(WorkItemModel.available_at),
                    )
                    .where(
                        WorkItemModel.status == "pending",
                        WorkItemModel.available_at <= cutoff,
                    )
                    .group_by(WorkItemModel.task_type)
                    .limit(limit)
                )
            ).all()
        return [
            QueueStallCandidate(
                task_type=task_type,
                pending_count=count,
                oldest_available_at=_aware(oldest),
                observed_at=now,
            )
            for task_type, count, oldest in rows
            if oldest is not None
        ]

    @override
    async def orphan_videos(self, *, limit: int) -> list[OrphanVideoCandidate]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        VideoModel.id,
                        VideoModel.channel_id,
                        VideoModel.youtube_video_id,
                    )
                    .outerjoin(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                    .where(ChannelModel.id.is_(None))
                    .order_by(VideoModel.id)
                    .limit(limit)
                )
            ).all()
        return [
            OrphanVideoCandidate(
                video_id=video_id,
                channel_id=channel_id,
                youtube_video_id=youtube_video_id,
            )
            for video_id, channel_id, youtube_video_id in rows
        ]

    @override
    async def automation_status(self, *, now: datetime) -> JsonObject:
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(session, now=now)
            queue_rows = (
                await session.execute(
                    select(WorkItemModel.task_type, WorkItemModel.status, func.count()).group_by(
                        WorkItemModel.task_type, WorkItemModel.status
                    )
                )
            ).all()
            open_incidents = await session.scalar(
                select(func.count(PipelineIncidentModel.id)).where(
                    PipelineIncidentModel.state == "open"
                )
            )
            orphan_video_count = await session.scalar(
                select(func.count(VideoModel.id))
                .select_from(VideoModel)
                .outerjoin(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                .where(ChannelModel.id.is_(None))
            )
            runtime = await _runtime_snapshot(session, state)
            await session.commit()
        return {
            "mode": state.mode,
            "backfillStartedAt": (
                state.backfill_started_at.isoformat()
                if state.backfill_started_at is not None
                else None
            ),
            "steadyStartedAt": (
                state.steady_started_at.isoformat()
                if state.steady_started_at is not None
                else None
            ),
            "observedAt": now.isoformat(),
            "openIncidentCount": open_incidents or 0,
            "dataIntegrity": {"orphanVideoCount": orphan_video_count or 0},
            "runtime": _runtime_json(runtime),
            "queues": [
                {"taskType": task_type, "status": status, "count": count}
                for task_type, status, count in queue_rows
            ],
        }

    @override
    async def runtime_state(self, *, now: datetime) -> RuntimeState:
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(session, now=now)
            snapshot = await _runtime_snapshot(session, state)
            await session.commit()
            return snapshot

    @override
    async def request_drain(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition:
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(
                session,
                now=now,
                for_update=True,
            )
            previous_mode = cast(RuntimeMode, state.runtime_state)
            changed = previous_mode == "active"
            if changed:
                state.runtime_state = "draining"
                state.drain_requested_at = now
                state.drain_reason = reason
                await session.flush()
            snapshot = await _runtime_snapshot(session, state)
            await session.commit()
        return RuntimeTransition(
            previous_mode=previous_mode,
            state=snapshot,
            changed=changed,
        )

    @override
    async def mark_stopped(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition:
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(
                session,
                now=now,
                for_update=True,
            )
            previous_mode = cast(RuntimeMode, state.runtime_state)
            snapshot = await _runtime_snapshot(session, state)
            changed = previous_mode == "draining" and snapshot.ready_to_stop
            if changed:
                state.runtime_state = "stopped"
                state.drain_reason = reason or state.drain_reason
                await session.flush()
                snapshot = await _runtime_snapshot(session, state)
            await session.commit()
        return RuntimeTransition(
            previous_mode=previous_mode,
            state=snapshot,
            changed=changed,
        )

    @override
    async def resume(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition:
        del reason
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(
                session,
                now=now,
                for_update=True,
            )
            previous_mode = cast(RuntimeMode, state.runtime_state)
            changed = previous_mode != "active"
            if changed:
                state.runtime_state = "active"
                state.drain_requested_at = None
                state.drain_reason = None
                await session.flush()
            snapshot = await _runtime_snapshot(session, state)
            await session.commit()
        return RuntimeTransition(
            previous_mode=previous_mode,
            state=snapshot,
            changed=changed,
        )

    @override
    async def record_runtime_transition(
        self,
        transition: RuntimeTransition,
        *,
        reason: str | None,
        now: datetime,
    ) -> None:
        event_type, message = {
            "active": ("pipeline_runtime.resumed", "Pipeline runtime resumed."),
            "draining": (
                "pipeline_runtime.drain_requested",
                "Pipeline runtime drain requested.",
            ),
            "stopped": ("pipeline_runtime.stopped", "Pipeline runtime stopped."),
        }[transition.state.mode]
        async with self._session_factory() as session:
            recorder = BestEffortOperationEventRecorder(
                SQLAlchemyOperationEventRepository(session)
            )
            await recorder.record_event(
                OperationEventCreate(
                    event_type=event_type,
                    severity="info",
                    message=message,
                    actor_type="manual_api",
                    source="pipeline_runtime",
                    subject_type="pipeline_runtime",
                    subject_id=1,
                    metadata_json={
                        "previousState": transition.previous_mode,
                        "currentState": transition.state.mode,
                        "reason": reason,
                        "runningWorkItemCount": (
                            transition.state.running_work_item_count
                        ),
                        "runningWorkflowCount": (
                            transition.state.running_workflow_count
                        ),
                        "occurredAt": now.isoformat(),
                    },
                )
            )

    @override
    async def get_state(self, *, now: datetime) -> AutomationScheduleState:
        async with self._session_factory() as session:
            state = await _get_or_create_automation_state(session, now=now)
            await session.commit()
        return AutomationScheduleState(
            mode=state.mode,
            backfill_started_at=state.backfill_started_at or now,
            runtime_state=state.runtime_state,
        )

    @override
    async def mark_steady(self, *, now: datetime) -> None:
        async with self._session_factory() as session:
            state = await session.get(PipelineAutomationStateModel, 1)
            if state is None:
                state = PipelineAutomationStateModel(id=1, mode="steady")
                session.add(state)
            cutoff = state.backfill_started_at or now
            published = exists(
                select(WorkItemModel.id).where(
                    WorkItemModel.task_type == "archive_publish",
                    WorkItemModel.subject_type == "video",
                    WorkItemModel.subject_id == VideoModel.id,
                    WorkItemModel.status == "succeeded",
                    WorkItemModel.outcome_code.is_(None),
                )
            )
            terminal_backfill_workflow = exists(
                select(WorkflowRunModel.id).where(
                    WorkflowRunModel.video_id == VideoModel.id,
                    WorkflowRunModel.workflow_type == "process_to_publish",
                    WorkflowRunModel.workflow_version == "v2",
                    WorkflowRunModel.options_json["automation_mode"].as_string()
                    == "backfill",
                    WorkflowRunModel.status.in_(("failed", "blocked", "canceled")),
                )
            )
            remaining = await session.scalar(
                select(func.count(VideoModel.id))
                .select_from(VideoModel)
                .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                .where(
                    VideoModel.created_at <= cutoff,
                    VideoModel.is_embeddable.is_not(False),
                    ~published,
                    ~terminal_backfill_workflow,
                )
            )
            if remaining:
                return
            state.mode = "steady"
            state.steady_started_at = state.steady_started_at or now
            await session.commit()


class SqlAlchemySafeRemediator(SafeRemediationPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def execute(
        self,
        *,
        action: RemediationAction,
        work_item_id: int | None,
        parameters: JsonObject,
        now: datetime,
    ) -> JsonObject:
        if action == "retry":
            if work_item_id is None:
                raise ValueError("retry requires an incident work item.")
            delay = _bounded_int(parameters, "delaySeconds", default=0, minimum=0, maximum=7200)
            async with SqlAlchemyWorkUnitOfWork(self._session_factory) as unit_of_work:
                item = await unit_of_work.work_items.reset_for_retry(
                    work_item_id=work_item_id,
                    now=now,
                    allow_succeeded=False,
                    available_at=now + timedelta(seconds=delay),
                )
                workflow_ids = await unit_of_work.workflows.reset_linked_for_work_item_retry(
                    work_item_id=work_item_id,
                    now=now,
                )
                await unit_of_work.commit()
            return {
                "workItemId": item.id,
                "status": item.status.value,
                "delaySeconds": delay,
                "workflowRunIds": workflow_ids,
            }
        if action == "recover_lease":
            async with SqlAlchemyWorkUnitOfWork(self._session_factory) as unit_of_work:
                count = await unit_of_work.work_items.recover_expired_leases(now=now)
                workflow_count = await unit_of_work.workflows.recover_expired_leases(now=now)
                await unit_of_work.commit()
            return {
                "recoveredWorkItemCount": count,
                "recoveredWorkflowCount": workflow_count,
            }
        if action == "extend_timeout":
            if work_item_id is None:
                raise ValueError("extend_timeout requires an incident work item.")
            async with self._session_factory() as session:
                item = await session.get(WorkItemModel, work_item_id)
                if item is None:
                    raise ValueError("Work item was not found.")
                maximum = {
                    "asr_transcribe": 64800,
                    "micro_event_extract": 14400,
                    "timeline_compose": 7200,
                }.get(item.task_type, 3600)
                if "extensionSeconds" in parameters:
                    extension = _bounded_int(
                        parameters,
                        "extensionSeconds",
                        default=0,
                        minimum=60,
                        maximum=maximum,
                    )
                    timeout = min(item.timeout_seconds + extension, maximum)
                else:
                    timeout = _bounded_int(
                        parameters,
                        "timeoutSeconds",
                        default=min(item.timeout_seconds, maximum),
                        minimum=60,
                        maximum=maximum,
                    )
                item.timeout_seconds = timeout
                await session.commit()
            return {"workItemId": work_item_id, "timeoutSeconds": timeout}
        task_type = _required_str(parameters, "taskType")
        max_concurrency = _bounded_int(
            parameters, "maxConcurrency", default=1, minimum=0, maximum=32
        )
        duration = _bounded_int(
            parameters, "durationSeconds", default=1800, minimum=60, maximum=21600
        )
        async with self._session_factory() as session:
            control = await session.get(PipelineRuntimeControlModel, task_type)
            if control is None:
                control = PipelineRuntimeControlModel(
                    task_type=task_type,
                    max_concurrency=max_concurrency,
                    expires_at=now + timedelta(seconds=duration),
                    reason="incident remediation",
                )
                session.add(control)
            else:
                control.max_concurrency = max_concurrency
                control.expires_at = now + timedelta(seconds=duration)
                control.reason = "incident remediation"
            await session.commit()
        return {
            "taskType": task_type,
            "maxConcurrency": max_concurrency,
            "expiresAt": (now + timedelta(seconds=duration)).isoformat(),
        }


async def _get_or_create_automation_state(
    session: AsyncSession,
    *,
    now: datetime,
    for_update: bool = False,
) -> PipelineAutomationStateModel:
    statement = select(PipelineAutomationStateModel).where(
        PipelineAutomationStateModel.id == 1
    )
    if for_update:
        statement = statement.with_for_update()
    state = await session.scalar(statement)
    if state is not None:
        return state
    state = PipelineAutomationStateModel(
        id=1,
        mode="backfill",
        backfill_started_at=now,
        runtime_state="active",
    )
    session.add(state)
    await session.flush()
    return state


async def _runtime_snapshot(
    session: AsyncSession,
    state: PipelineAutomationStateModel,
) -> RuntimeState:
    running_rows = (
        await session.execute(
            select(WorkItemModel.task_type, func.count(WorkItemModel.id))
            .where(WorkItemModel.status == "running")
            .group_by(WorkItemModel.task_type)
            .order_by(WorkItemModel.task_type)
        )
    ).all()
    running_workflow_count = await session.scalar(
        select(func.count(WorkflowRunModel.id)).where(
            WorkflowRunModel.status == "running"
        )
    )
    by_task_type = tuple(
        RuntimeTaskCount(task_type=task_type, count=count)
        for task_type, count in running_rows
    )
    return RuntimeState(
        mode=cast(RuntimeMode, state.runtime_state),
        drain_requested_at=(
            _aware(state.drain_requested_at)
            if state.drain_requested_at is not None
            else None
        ),
        drain_reason=state.drain_reason,
        running_work_item_count=sum(item.count for item in by_task_type),
        running_workflow_count=running_workflow_count or 0,
        running_by_task_type=by_task_type,
    )


def _runtime_json(state: RuntimeState) -> JsonObject:
    return {
        "state": state.mode,
        "drainRequestedAt": (
            state.drain_requested_at.isoformat()
            if state.drain_requested_at is not None
            else None
        ),
        "drainReason": state.drain_reason,
        "runningWorkItemCount": state.running_work_item_count,
        "runningWorkflowCount": state.running_workflow_count,
        "runningByTaskType": [
            {"taskType": item.task_type, "count": item.count}
            for item in state.running_by_task_type
        ],
        "readyToStop": state.ready_to_stop,
    }


def _incident(model: PipelineIncidentModel) -> IncidentRecord:
    return IncidentRecord(
        id=model.id,
        fingerprint=model.fingerprint,
        incident_type=model.incident_type,
        severity=model.severity,  # type: ignore[arg-type]
        state=model.state,  # type: ignore[arg-type]
        work_item_id=model.work_item_id,
        workflow_run_id=model.workflow_run_id,
        task_type=model.task_type,
        error_type=model.error_type,
        error_message=model.error_message,
        metadata_json=model.metadata_json,
        occurrence_count=model.occurrence_count,
        first_seen_at=model.first_seen_at,
        last_seen_at=model.last_seen_at,
        resolved_at=model.resolved_at,
    )


def _json_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _bounded_int(
    values: JsonObject,
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = values.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _required_str(values: JsonObject, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string.")
    return value
