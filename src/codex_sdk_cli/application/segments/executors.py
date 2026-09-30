from __future__ import annotations

import hashlib
import json
from typing import cast

from pydantic import ValidationError

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)
from codex_sdk_cli.domains.codex.choices import ReasoningEffortChoice
from codex_sdk_cli.domains.codex.ports import (
    CodexRunCommand,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.domains.segments.models import (
    POLICY_VERSION,
    TAXONOMY_VERSION,
    SegmentClassificationError,
    SegmentSource,
    SegmentSourceChangedError,
)
from codex_sdk_cli.domains.segments.policy import normalize_segments
from codex_sdk_cli.domains.segments.schemas import SegmentOutput

from .ports import SegmentResultStorePort, SegmentSourceReaderPort


class SegmentClassificationExecutor(WorkExecutorPort):
    def __init__(
        self,
        *,
        source: SegmentSourceReaderPort,
        results: SegmentResultStorePort,
        runtime: CodexRuntimePort,
        max_calls: int = 3,
    ) -> None:
        if not 1 <= max_calls <= 3:
            raise ValueError("Segment generation allows one to three calls per attempt.")
        self._source = source
        self._results = results
        self._runtime = runtime
        self._max_calls = max_calls

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        try:
            return await self._execute(context)
        except SegmentClassificationError as exc:
            raise ApplicationError(
                code=exc.error_code,
                message=str(exc),
                kind=ErrorKind.CONFLICT,
            ) from exc

    async def _execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        video_id = required_int(values, "videoId")
        source = await self._source.load(video_id, required_int(values, "sourceTimelineWorkItemId"))
        if source.fingerprint != values["sourceFingerprint"]:
            raise SegmentSourceChangedError("Timeline input changed; enqueue classification again.")
        if (
            values["taxonomyVersion"] != TAXONOMY_VERSION
            or values["policyVersion"] != POLICY_VERSION
        ):
            raise SegmentClassificationError("Classification policy version is unsupported.")
        prompt_body = required_str(values, "promptBody")
        if hashlib.sha256(prompt_body.encode()).hexdigest() != values["promptBodySha256"]:
            raise SegmentClassificationError("Frozen prompt checksum does not match.")
        segments, raw = (
            ([], "") if source.empty else await self._generate(context, prompt_body, source)
        )
        result_id = await self._results.save(
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
            input_json=values,
            segments=segments,
            raw_response=raw,
        )
        return WorkExecutionResult(
            output_json={
                "videoId": video_id,
                "classificationId": result_id,
                "sourceTimelineWorkItemId": source.timeline_work_item_id,
                "sourceFingerprint": source.fingerprint,
                "inputFingerprint": context.work_item.input_hash,
                "taxonomyVersion": TAXONOMY_VERSION,
                "segmentCount": len(segments),
            }
        )

    async def _generate(
        self,
        context: WorkExecutionContext,
        body: str,
        source: SegmentSource,
    ) -> tuple[list[dict[str, object]], str]:
        error: str | None = None
        values = context.work_item.input_json
        reasoning = required_str(values, "reasoningEffort")
        if reasoning not in {"low", "medium", "high", "xhigh"}:
            raise SegmentClassificationError("Unsupported reasoning effort.")
        for call_index in range(self._max_calls):
            repair = (
                f"\nPrevious output was invalid: {error}. Return a complete replacement."
                if error
                else ""
            )
            response = await self._runtime.run_prompt(
                CodexRunCommand(
                    prompt=body
                    + "\nINPUT_JSON\n"
                    + json.dumps(source.payload, ensure_ascii=False)
                    + repair,
                    thread_id=None,
                    cwd=None,
                    model=required_str(values, "model"),
                    reasoning_effort=cast(ReasoningEffortChoice, reasoning),
                    sandbox="read-only",
                    approval="deny-all",
                    persist=False,
                    base_instructions=None,
                    developer_instructions=None,
                    output_schema=SegmentOutput.model_json_schema(by_alias=True),
                    usage_context=CodexRunUsageContext(
                        source="segments",
                        operation="classify" if call_index == 0 else "repair",
                        video_id=source.video_id,
                        work_item_id=context.work_item.id,
                        work_attempt_id=context.attempt_id,
                    ),
                )
            )
            try:
                if response.status != "completed":
                    raise SegmentClassificationError("Codex did not complete classification.")
                output = SegmentOutput.model_validate_json(response.final_response)
                return normalize_segments(output, source.episodes), response.final_response
            except (ValidationError, SegmentClassificationError) as exc:
                error = str(exc)[:1500]
        raise SegmentClassificationError(
            f"Classification validation failed after {self._max_calls} calls: {error}"
        )


def required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise SegmentClassificationError(f"{key} must be an integer.")


def required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    raise SegmentClassificationError(f"{key} must be a nonempty string.")
