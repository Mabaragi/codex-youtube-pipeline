from __future__ import annotations

import hashlib
import json
from typing import cast

from codex_sdk_cli.domains.codex.choices import (
    CODEX_MODEL_CHOICES,
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptEntryRecord,
)
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.video_tasks.constants import TIMELINE_COMPOSE_TASK_VERSION
from codex_sdk_cli.domains.video_tasks.exceptions import VideoTaskRetryNotAllowed
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord

from .models import _ComposerInput
from .ports import CopyStyle

TIMELINE_DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT = 80


def _timeline_prompt(composer_input: _ComposerInput) -> str:
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "duration_sec": _duration_seconds(composer_input.video.duration),
            "copy_style": composer_input.copy_style,
            "target_episode_count_hint": _episode_count_hint(len(composer_input.micro_events)),
        },
        "domain_entries": [
            _domain_entry_json(entry) for entry in _timeline_domain_entries(composer_input)
        ],
        "micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(composer_input.micro_events, start=1)
        ],
    }
    return "\n\n".join(
        [
            composer_input.compose_prompt.body,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


def _micro_event_input(
    candidate: MicroEventCandidateRecord,
    composer_input: _ComposerInput,
    *,
    seq: int,
) -> JsonObject:
    return {
        "micro_event_id": composer_input.synthetic_id_by_candidate_id[candidate.id],
        "seq": seq,
        "start_cue_id": candidate.start_cue_id,
        "end_cue_id": candidate.end_cue_id,
        "event": candidate.event,
        "program_mode": candidate.program_mode,
        "content_kind": candidate.content_kind,
        "topics": candidate.topics or [],
    }


def _domain_entry_json(entry: DomainKnowledgePromptEntryRecord) -> JsonObject:
    return {
        "type": entry.type_key,
        "canonicalName": entry.canonical_name,
        "displayName": entry.display_name,
        "detail": entry.detail,
        "aliases": [
            {
                "surfaceForm": alias.surface_form,
                "aliasKind": alias.alias_kind,
                "certainty": alias.certainty,
            }
            for alias in entry.aliases
        ],
    }


def _timeline_domain_entries(
    composer_input: _ComposerInput,
) -> list[DomainKnowledgePromptEntryRecord]:
    text = _timeline_domain_match_text(composer_input)
    selected: list[DomainKnowledgePromptEntryRecord] = []
    for entry in composer_input.domain_entries:
        if entry.prompt_policy == "ALWAYS_FOR_SCOPED_STREAMER":
            selected.append(entry)
            continue
        if entry.prompt_policy == "AUTO_ON_MATCH" and _domain_entry_matches_text(
            entry,
            text,
        ):
            selected.append(entry)
    selected.sort(key=lambda entry: (-entry.priority, entry.entry_id))
    return selected[:TIMELINE_DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT]


def _timeline_domain_match_text(composer_input: _ComposerInput) -> str:
    values = [composer_input.video.title, composer_input.streamer_name or ""]
    for candidate in composer_input.micro_events:
        values.append(candidate.event)
        values.extend(candidate.topics or [])
    return " ".join(value for value in values if value).casefold()


def _domain_entry_matches_text(
    entry: DomainKnowledgePromptEntryRecord,
    text: str,
) -> bool:
    values = [entry.canonical_name, entry.display_name]
    values.extend(alias.surface_form for alias in entry.aliases)
    return any(value.strip().casefold() in text for value in values if value)


def _flatten_micro_events(
    detail: MicroEventExtractionDetailRecord,
) -> list[MicroEventCandidateRecord]:
    return [
        candidate
        for window in sorted(detail.windows, key=lambda item: item.window_index)
        for candidate in sorted(
            window.micro_events,
            key=lambda item: item.candidate_index,
        )
    ]


def _micro_event_count(detail: MicroEventExtractionDetailRecord) -> int:
    return sum(len(window.micro_events) for window in detail.windows)


def _source_micro_event_fingerprint(detail: MicroEventExtractionDetailRecord) -> str:
    payload = [
        {
            "id": candidate.id,
            "event": candidate.event,
            "startCueId": candidate.start_cue_id,
            "endCueId": candidate.end_cue_id,
            "programMode": candidate.program_mode,
            "contentKind": candidate.content_kind,
            "topics": candidate.topics,
        }
        for candidate in _flatten_micro_events(detail)
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


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
    source_task: VideoTaskRecord,
    source_fingerprint: str,
    copy_style: CopyStyle,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    prompt: ResolvedPrompt,
) -> str:
    payload = {
        "copyStyle": copy_style,
        "model": model,
        **_prompt_metadata_json(prompt),
        "reasoningEffort": reasoning_effort,
        "sourceMicroEventFingerprint": source_fingerprint,
        "sourceMicroEventTaskId": source_task.id,
        "taskVersion": TIMELINE_COMPOSE_TASK_VERSION,
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    *,
    video: VideoRecord,
    source_task: VideoTaskRecord,
    source_fingerprint: str,
    input_hash: str,
    copy_style: CopyStyle,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    timeout_seconds: int,
    prompt: ResolvedPrompt,
) -> JsonObject:
    return {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceMicroEventTaskId": source_task.id,
        "sourceMicroEventFingerprint": source_fingerprint,
        "taskVersion": TIMELINE_COMPOSE_TASK_VERSION,
        **_prompt_metadata_json(prompt),
        "inputHash": input_hash,
        "copyStyle": copy_style,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "timeoutSeconds": timeout_seconds,
    }


def _duration_seconds(duration: str | None) -> int | None:
    if not duration or not duration.startswith("PT"):
        return None
    total = 0
    number = ""
    for char in duration[2:]:
        if char.isdigit():
            number += char
            continue
        if not number:
            continue
        value = int(number)
        number = ""
        if char == "H":
            total += value * 3600
        elif char == "M":
            total += value * 60
        elif char == "S":
            total += value
    return total or None


def _episode_count_hint(micro_event_count: int) -> JsonObject:
    if micro_event_count <= 20:
        return {"min": 3, "max": max(5, micro_event_count)}
    if micro_event_count <= 80:
        return {"min": 10, "max": 30}
    return {"min": 30, "max": 60}


def _model_output(input_json: JsonObject) -> CodexModelChoice | None:
    value = input_json.get("model")
    if value in CODEX_MODEL_CHOICES:
        return value
    return None


def _reasoning_effort_output(input_json: JsonObject) -> ReasoningEffortChoice | None:
    value = input_json.get("reasoningEffort")
    if value in {"low", "medium", "high", "xhigh"}:
        return cast(ReasoningEffortChoice, value)
    return None


def _str_output(input_json: JsonObject, key: str) -> str | None:
    value = input_json.get(key)
    return value if isinstance(value, str) else None


def _int_output(input_json: JsonObject, key: str) -> int | None:
    value = input_json.get(key)
    return value if isinstance(value, int) else None


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Task input is missing integer '{key}'.")
    return value


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str) or not value:
        raise VideoTaskRetryNotAllowed(f"Task input is missing string '{key}'.")
    return value
