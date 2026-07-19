from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.timelines.ports import CopyStyle

EvaluationStage = Literal["micro", "timeline"]


class MicroEvaluationCandidate(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice = Field(alias="reasoningEffort")
    prompt_version_id: int | None = Field(default=None, ge=1, alias="promptVersionId")
    window_minutes: int = Field(default=30, ge=1, le=240, alias="windowMinutes")
    overlap_minutes: int = Field(default=5, ge=0, le=239, alias="overlapMinutes")

    @model_validator(mode="after")
    def validate_overlap(self) -> MicroEvaluationCandidate:
        if self.overlap_minutes >= self.window_minutes:
            raise ValueError("overlapMinutes must be shorter than windowMinutes.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelineEvaluationCandidate(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice = Field(alias="reasoningEffort")
    prompt_version_id: int | None = Field(default=None, ge=1, alias="promptVersionId")
    copy_style: CopyStyle = Field(default="LIGHT_FANDOM_V1", alias="copyStyle")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluationPlan(BaseModel):
    version: Literal[1] = 1
    experiment_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
        alias="experimentKey",
    )
    video_ids: list[int] = Field(min_length=1, max_length=200, alias="videoIds")
    micro_candidates: list[MicroEvaluationCandidate] = Field(
        min_length=1,
        max_length=20,
        alias="microCandidates",
    )
    timeline_candidates: list[TimelineEvaluationCandidate] = Field(
        min_length=1,
        max_length=20,
        alias="timelineCandidates",
    )
    repetitions: int = Field(default=1, ge=1, le=5)
    run_concurrency: int = Field(default=1, ge=1, le=4, alias="runConcurrency")
    micro_window_concurrency: int = Field(
        default=1,
        ge=1,
        le=12,
        alias="microWindowConcurrency",
    )

    @model_validator(mode="after")
    def validate_unique_values(self) -> EvaluationPlan:
        if len(set(self.video_ids)) != len(self.video_ids):
            raise ValueError("videoIds must be unique.")
        micro_keys = [item.key for item in self.micro_candidates]
        timeline_keys = [item.key for item in self.timeline_candidates]
        if len(set(micro_keys)) != len(micro_keys):
            raise ValueError("microCandidates keys must be unique.")
        if len(set(timeline_keys)) != len(timeline_keys):
            raise ValueError("timelineCandidates keys must be unique.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluationScoreItem(BaseModel):
    blind_run_id: str = Field(min_length=1, max_length=64, alias="blindRunId")
    scores: dict[str, int]
    notes: str | None = Field(default=None, max_length=10_000)
    evidence: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_scores(self) -> EvaluationScoreItem:
        if not self.scores:
            raise ValueError("scores must not be empty.")
        if any(score < 1 or score > 5 for score in self.scores.values()):
            raise ValueError("Every score must be between 1 and 5.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluationScoreImport(BaseModel):
    version: Literal[1] = 1
    stage: EvaluationStage
    evaluator: str = Field(default="agent", min_length=1, max_length=100)
    rubric_version: Literal["micro-v1", "micro-v2", "timeline-v1"] = Field(
        alias="rubricVersion"
    )
    items: list[EvaluationScoreItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rubric_stage(self) -> EvaluationScoreImport:
        if not self.rubric_version.startswith(f"{self.stage}-"):
            raise ValueError("rubricVersion must match the selected stage.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MicroSelectionItem(BaseModel):
    video_id: int = Field(ge=1, alias="videoId")
    blind_run_id: str = Field(min_length=1, max_length=64, alias="blindRunId")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MicroSelectionImport(BaseModel):
    version: Literal[1] = 1
    selections: list[MicroSelectionItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_videos(self) -> MicroSelectionImport:
        video_ids = [item.video_id for item in self.selections]
        if len(set(video_ids)) != len(video_ids):
            raise ValueError("Selection videoIds must be unique.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


MICRO_RUBRIC_KEYS = frozenset(
    {
        "boundaryEvidenceAccuracy",
        "meaningfulCoverage",
        "semanticTopicAccuracy",
        "noiseDuplicationControl",
        "timelineInputUsefulness",
    }
)
MICRO_RUBRIC_V2_KEYS = frozenset(
    {
        *MICRO_RUBRIC_KEYS,
        "asrComprehensionAccuracy",
    }
)
TIMELINE_RUBRIC_KEYS = frozenset(
    {
        "coverageOrdering",
        "boundaryCoherence",
        "titleSummaryFactuality",
        "topicNavigationUsefulness",
        "concisionReadability",
    }
)

RUBRIC_KEYS_BY_VERSION = {
    "micro-v1": MICRO_RUBRIC_KEYS,
    "micro-v2": MICRO_RUBRIC_V2_KEYS,
    "timeline-v1": TIMELINE_RUBRIC_KEYS,
}
CURRENT_RUBRIC_VERSION = {
    "micro": "micro-v2",
    "timeline": "timeline-v1",
}
