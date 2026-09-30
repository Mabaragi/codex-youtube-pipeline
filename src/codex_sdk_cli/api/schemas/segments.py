from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.api.schemas.operations import VideoSelectionRequest
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice


class SegmentOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    model: CodexModelChoice = "gpt-6-luna"
    reasoning_effort: ReasoningEffortChoice = Field(default="high", alias="reasoningEffort")
    taxonomy_version: Literal["v1.6"] = Field(default="v1.6", alias="taxonomyVersion")
    prompt_version_id: int | None = Field(default=None, alias="promptVersionId", ge=1)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class BackfillSegmentsOperationRequest(SegmentOperationRequest):
    publish_mode: Literal["prod", "dev"] = Field(default="prod", alias="publishMode")
    environment: str = "prod"
    variant: str = "control"
    schema_version: int = Field(default=1, alias="schemaVersion", ge=1)

    @model_validator(mode="after")
    def validate_publish_mode(self) -> BackfillSegmentsOperationRequest:
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        if self.rerun_succeeded:
            raise ValueError("Use segment-classify with rerunSucceeded, then archive-publish.")
        return self
