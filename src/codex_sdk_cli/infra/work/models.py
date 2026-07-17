from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from codex_sdk_cli.domains.work.models import JsonObject
from codex_sdk_cli.infra.database.base import Base


class WorkItemModel(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'timed_out', "
            "'blocked', 'canceled')",
            name="work_items_status_allowed",
        ),
        CheckConstraint(
            "execution_mode IN ('inline', 'worker')",
            name="work_items_execution_mode_allowed",
        ),
        CheckConstraint("timeout_seconds >= 1", name="work_items_timeout_positive"),
        Index(
            "ix_work_items_pending_claim",
            "status",
            "execution_mode",
            "task_type",
            "available_at",
            "priority",
            "id",
        ),
        Index("ix_work_items_subject", "subject_type", "subject_id"),
        Index("ix_work_items_task_status", "task_type", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    input_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    output_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    output_transcript_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkAttemptModel(Base):
    __tablename__ = "work_attempts"
    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="work_attempts_attempt_no_positive"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'timed_out', 'canceled')",
            name="work_attempts_status_allowed",
        ),
        UniqueConstraint("work_item_id", "attempt_no", name="uq_work_attempts_item_no"),
        Index("ix_work_attempts_item_status", "work_item_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkItemDependencyModel(Base):
    __tablename__ = "work_item_dependencies"
    __table_args__ = (
        CheckConstraint(
            "work_item_id <> dependency_work_item_id",
            name="work_item_dependencies_not_self",
        ),
    )

    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    dependency_work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    requires_successful_output: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkBatchModel(Base):
    __tablename__ = "work_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'canceled')",
            name="work_batches_status_allowed",
        ),
        CheckConstraint("requested_count >= 0", name="work_batches_requested_non_negative"),
        Index("ix_work_batches_operation_status", "operation_type", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    options_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'succeeded', 'failed', "
            "'blocked', 'canceled')",
            name="workflow_runs_status_allowed",
        ),
        UniqueConstraint(
            "workflow_type",
            "workflow_version",
            "video_id",
            "input_hash",
            name="uq_workflow_runs_input",
        ),
        Index("ix_workflow_runs_claim", "status", "lease_expires_at", "id"),
        Index("ix_workflow_runs_video", "video_id", "workflow_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="RESTRICT"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    options_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    output_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStepModel(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "stage_name", name="uq_workflow_steps_stage"),
        UniqueConstraint("workflow_run_id", "position", name="uq_workflow_steps_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkBatchItemModel(Base):
    __tablename__ = "work_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "position", name="uq_work_batch_items_position"),
        Index("ix_work_batch_items_video", "batch_id", "video_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("work_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    selection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class LegacyWorkRefModel(Base):
    __tablename__ = "legacy_work_refs"
    __table_args__ = (
        UniqueConstraint("entity_kind", "legacy_id", name="uq_legacy_work_refs_entity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    legacy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    work_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    work_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_batches.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
