from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import EvaluationBase


class EvaluationExperimentModel(EvaluationBase):
    __tablename__ = "evaluation_experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    micro_rubric_version: Mapped[str] = mapped_column(
        String(32), default="micro-v2", server_default="micro-v2", nullable=False
    )
    timeline_rubric_version: Mapped[str] = mapped_column(
        String(32), default="timeline-v1", server_default="timeline-v1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EvaluationCaseModel(EvaluationBase):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("experiment_id", "video_id", name="uq_evaluation_cases_video"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    video_id: Mapped[int] = mapped_column(Integer, nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationCandidateModel(EvaluationBase):
    __tablename__ = "evaluation_candidates"
    __table_args__ = (
        CheckConstraint("stage IN ('micro', 'timeline')", name="evaluation_candidate_stage"),
        UniqueConstraint(
            "experiment_id", "stage", "candidate_key", name="uq_evaluation_candidates_key"
        ),
        UniqueConstraint(
            "experiment_id", "stage", "blind_alias", name="uq_evaluation_candidates_alias"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    blind_alias: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationRunModel(EvaluationBase):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("stage IN ('micro', 'timeline')", name="evaluation_run_stage"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'abandoned')",
            name="evaluation_run_status",
        ),
        UniqueConstraint(
            "experiment_id",
            "case_id",
            "candidate_id",
            "replicate",
            name="uq_evaluation_runs_candidate_replicate",
        ),
        UniqueConstraint("experiment_id", "blind_run_id", name="uq_evaluation_runs_blind"),
        Index("ix_evaluation_runs_stage_status", "experiment_id", "stage", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_no: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_candidates.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    replicate: Mapped[int] = mapped_column(Integer, nullable=False)
    blind_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_micro_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EvaluationRunAttemptModel(EvaluationBase):
    __tablename__ = "evaluation_run_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'abandoned')",
            name="evaluation_attempt_status",
        ),
        UniqueConstraint("run_id", "attempt_no", name="uq_evaluation_attempts_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationCheckpointModel(EvaluationBase):
    __tablename__ = "evaluation_run_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "checkpoint_key", name="uq_evaluation_checkpoints_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    checkpoint_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EvaluationUsageModel(EvaluationBase):
    __tablename__ = "evaluation_usage_records"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="evaluation_usage_status"),
        Index("ix_evaluation_usage_run", "run_id", "attempt_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_run_attempts.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(128), nullable=True)
    window_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationArtifactModel(EvaluationBase):
    __tablename__ = "evaluation_artifacts"
    __table_args__ = (UniqueConstraint("object_key", name="uq_evaluation_artifacts_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationReviewModel(EvaluationBase):
    __tablename__ = "evaluation_reviews"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "evaluator", "rubric_version", name="uq_evaluation_reviews_identity"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evaluator: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scores_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EvaluationMicroSelectionModel(EvaluationBase):
    __tablename__ = "evaluation_micro_selections"
    __table_args__ = (
        UniqueConstraint("experiment_id", "case_id", name="uq_evaluation_micro_selection_case"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False
    )
    micro_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
