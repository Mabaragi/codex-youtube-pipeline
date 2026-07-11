from __future__ import annotations

import hashlib
import json

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.domain_knowledge.ports import DomainKnowledgePromptEntryRecord
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptMetadataRecord

from .constants import MICRO_EVENT_EXTRACT_TASK_VERSION
from .ports import JsonObject
from .schemas import (
    MicroEventBatchExtractRequest,
    MicroEventExtractRequest,
)
from .windowing import _domain_prompt_entry_json, _ExtractionExecutionInput


def _domain_knowledge_fingerprint(
    entries: list[DomainKnowledgePromptEntryRecord],
) -> str:
    payload = [
        _domain_prompt_entry_json(entry)
        for entry in sorted(entries, key=lambda item: item.entry_id)
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _single_extract_request(
    request: MicroEventBatchExtractRequest,
) -> MicroEventExtractRequest:
    return MicroEventExtractRequest(
        retryFailed=request.retry_failed,
        regenerateSucceeded=request.regenerate_succeeded,
        windowMinutes=request.window_minutes,
        overlapMinutes=request.overlap_minutes,
        model=request.model,
        reasoningEffort=request.reasoning_effort,
        promptVersionId=request.prompt_version_id,
    )


def _prompt_metadata_json(prompt: ResolvedPrompt) -> JsonObject:
    return {
        "promptVersionId": prompt.version_id,
        "promptVersion": prompt.version_label,
        "promptSha256": prompt.body_sha256,
        "promptSource": prompt.source,
    }


def _task_input_hash(
    *,
    video: VideoRecord,
    metadata: YouTubeTranscriptMetadataRecord,
    window_minutes: int,
    overlap_minutes: int,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    domain_knowledge_fingerprint: str,
    prompt: ResolvedPrompt,
) -> str:
    payload = {
        "domainKnowledgeFingerprint": domain_knowledge_fingerprint,
        "model": model,
        "overlapMinutes": overlap_minutes,
        **_prompt_metadata_json(prompt),
        "reasoningEffort": reasoning_effort,
        "responseSha256": metadata.response_sha256,
        "taskVersion": MICRO_EVENT_EXTRACT_TASK_VERSION,
        "transcriptId": metadata.id,
        "videoId": video.id,
        "windowMinutes": window_minutes,
        "youtubeVideoId": video.youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    execution_input: _ExtractionExecutionInput,
    *,
    input_hash: str,
    timeout_seconds: int,
) -> JsonObject:
    return {
        "videoId": execution_input.video.id,
        "youtubeVideoId": execution_input.video.youtube_video_id,
        "transcriptId": execution_input.metadata.id,
        "responseSha256": execution_input.metadata.response_sha256,
        "taskVersion": MICRO_EVENT_EXTRACT_TASK_VERSION,
        **_prompt_metadata_json(execution_input.prompt),
        "inputHash": input_hash,
        "windowMinutes": execution_input.window_minutes,
        "overlapMinutes": execution_input.overlap_minutes,
        "model": execution_input.model,
        "reasoningEffort": execution_input.reasoning_effort,
        "domainKnowledgeEntryCount": len(execution_input.domain_knowledge_entries),
        "domainKnowledgeFingerprint": execution_input.domain_knowledge_fingerprint,
        "timeoutSeconds": timeout_seconds,
    }
