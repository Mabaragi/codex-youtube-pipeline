from __future__ import annotations

from dataclasses import asdict

from codex_sdk_cli.domains.prompts.exceptions import PromptConflict
from codex_sdk_cli.domains.prompts.ports import PromptResolverPort
from codex_sdk_cli.domains.segments.models import POLICY_VERSION, TAXONOMY_VERSION

from .ports import SegmentInputPlannerPort, SegmentSourceReaderPort


class PrepareSegmentInputUseCase(SegmentInputPlannerPort):
    def __init__(self, source: SegmentSourceReaderPort, prompts: PromptResolverPort) -> None:
        self._source = source
        self._prompts = prompts

    async def prepare(
        self,
        *,
        video_id: int,
        timeline_work_item_id: int,
        model: str,
        reasoning_effort: str,
        prompt_version_id: int | None,
        taxonomy_version: str,
    ) -> dict[str, object]:
        if taxonomy_version != TAXONOMY_VERSION:
            raise ValueError("Unsupported segment taxonomy version.")
        source = await self._source.load(video_id, timeline_work_item_id)
        prompt = await self._prompts.resolve_prompt_for_request(
            "segment_classify", prompt_version_id
        )
        if prompt.source == "fallback" and not source.empty:
            raise PromptConflict(
                "Publish the approved segment taxonomy prompt before classification."
            )
        return {
            "videoId": video_id,
            "sourceTimelineWorkItemId": timeline_work_item_id,
            "compositionId": source.composition_id,
            "sourceFingerprint": source.fingerprint,
            "sourceInput": source.payload,
            "episodeRanges": [asdict(e) for e in source.episodes],
            "emptyTimeline": source.empty,
            "model": model,
            "reasoningEffort": reasoning_effort,
            "taxonomyVersion": taxonomy_version,
            "policyVersion": POLICY_VERSION,
            "promptVersionId": prompt.version_id,
            "promptBody": prompt.body,
            "promptBodySha256": prompt.body_sha256,
        }
