from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass

from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventActorType
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptMetadataRecord

from .ports import JsonObject
from .window_sizing import micro_window_count

DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT = 80
_CUE_GAP_MARK_MS = 1_000
_CUE_FORMAT_NOTE = (
    "각 줄은 cue 하나다: `<cue_id> <시작 시각 H:MM:SS> [+Ns] | <자막>`. "
    "`+Ns`는 앞 cue가 끝난 뒤 자막이 없던 초 수이며 1초 이상일 때만 붙는다. "
    "출력에는 줄 맨 앞의 cue_id를 그대로 쓴다."
)


@dataclass(frozen=True, slots=True)
class _CueWindow:
    window_index: int
    context_before: list[TranscriptCueRecord]
    owned_cues: list[TranscriptCueRecord]
    context_after: list[TranscriptCueRecord]


@dataclass(frozen=True, slots=True)
class _ExtractionExecutionInput:
    video: VideoRecord
    metadata: YouTubeTranscriptMetadataRecord
    cues: list[TranscriptCueRecord]
    window_minutes: int
    overlap_minutes: int
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    actor_type: OperationEventActorType
    domain_knowledge_entries: list[DomainKnowledgePromptEntryRecord]
    domain_knowledge_fingerprint: str
    streamer_name: str | None
    prompt: ResolvedPrompt


def _cue_windows(
    cues: list[TranscriptCueRecord],
    *,
    window_minutes: int,
    overlap_minutes: int,
) -> list[_CueWindow]:
    context_ms = overlap_minutes * 60_000
    first_start_ms = cues[0].start_ms
    span_ms = max(0, cues[-1].end_ms - first_start_ms)
    window_count = micro_window_count(span_ms, window_minutes=window_minutes)
    boundaries = [
        first_start_ms + span_ms * position // window_count for position in range(window_count + 1)
    ]
    # Each cue belongs to exactly one window, chosen by its start time.
    owned_by_position: list[list[TranscriptCueRecord]] = [[] for _ in range(window_count)]
    for cue in cues:
        owned_by_position[bisect_right(boundaries, cue.start_ms, 1, window_count) - 1].append(cue)
    windows: list[_CueWindow] = []
    for position, owned_cues in enumerate(owned_by_position):
        if not owned_cues:
            continue
        window_start_ms = boundaries[position]
        window_end_ms = boundaries[position + 1]
        context_before = (
            [cue for cue in cues if window_start_ms - context_ms <= cue.start_ms < window_start_ms]
            if position > 0
            else []
        )
        context_after = (
            [cue for cue in cues if window_end_ms <= cue.start_ms < window_end_ms + context_ms]
            if position < window_count - 1
            else []
        )
        windows.append(
            _CueWindow(
                window_index=len(windows) + 1,
                context_before=context_before,
                owned_cues=owned_cues,
                context_after=context_after,
            )
        )
    return windows


def _window_prompt(
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
) -> str:
    term_annotations = _window_term_annotations(execution_input, cue_window)
    video_metadata: JsonObject = {
        "videoTitle": execution_input.video.title,
        "videoDescription": _compact_prompt_text(execution_input.video.description),
        "publishedAt": execution_input.video.published_at.isoformat(),
        "streamerName": execution_input.streamer_name,
        "transcriptLanguage": execution_input.metadata.language,
        "transcriptLanguageCode": execution_input.metadata.language_code,
        "transcriptSource": ("generated" if execution_input.metadata.is_generated else "manual"),
        "windowIndex": cue_window.window_index,
    }
    return "\n\n".join(
        [
            execution_input.prompt.body,
            "# INPUT_METADATA",
            json.dumps(video_metadata, ensure_ascii=False),
            "# DOMAIN_KNOWLEDGE",
            json.dumps(term_annotations, ensure_ascii=False),
            "# OWNED_RANGE_BOUNDS",
            "\n".join(
                [
                    f"OWNED_START_CUE_ID: {cue_window.owned_cues[0].cue_id}",
                    f"OWNED_END_CUE_ID: {cue_window.owned_cues[-1].cue_id}",
                ]
            ),
            "# CUE_FORMAT",
            _CUE_FORMAT_NOTE,
            "# CONTEXT_BEFORE",
            _format_cue_block(cue_window.context_before, execution_input.cues),
            "# OWNED_RANGE",
            _format_cue_block(cue_window.owned_cues, execution_input.cues),
            "# CONTEXT_AFTER",
            _format_cue_block(cue_window.context_after, execution_input.cues),
        ]
    )


def _repair_window_prompt(
    *,
    original_prompt: str,
    original_response: str,
    validation_error: str,
    cue_window: _CueWindow,
) -> str:
    return "\n\n".join(
        [
            "# 역할",
            "너는 micro-event extractor가 만든 JSON을 고치는 repair step이다.",
            (
                "새 사건을 만들지 말고, 원본 응답의 의미와 분류를 가능한 한 "
                "유지하면서 cue 범위와 coverage 정합성만 고친다."
            ),
            "# 실패 원인",
            validation_error,
            "# 반드시 지킬 규칙",
            "\n".join(
                [
                    "1. 반드시 JSON 객체만 출력한다.",
                    (
                        "2. 출력 schema는 events, excluded_ranges, "
                        "asr_correction_candidates만 사용한다."
                    ),
                    "3. OWNED_RANGE 밖 cue_id는 절대 사용하지 않는다.",
                    "4. 모든 OWNED_RANGE cue를 event 또는 excluded_range로 정확히 한 번 덮는다.",
                    (
                        "5. event 문장, program_mode, content_kind, topics는 "
                        "원본 의미를 가능한 한 유지한다."
                    ),
                    (
                        "6. cue 범위를 고치기 어렵거나 정보가 낮은 구간은 "
                        "excluded_range reason=LOW_INFORMATION으로 덮는다."
                    ),
                    "7. asr_correction_candidates에는 evidence_cue_ids를 출력하지 않는다.",
                ]
            ),
            "# OWNED_RANGE",
            json.dumps(
                {
                    "ownedStartCueId": cue_window.owned_cues[0].cue_id,
                    "ownedEndCueId": cue_window.owned_cues[-1].cue_id,
                    "ownedCueIds": [cue.cue_id for cue in cue_window.owned_cues],
                },
                ensure_ascii=False,
            ),
            "# 원본 window prompt",
            original_prompt,
            "# 고쳐야 할 원본 응답",
            original_response,
            "# REPAIR_QUALITY_GUARD",
            (
                "Re-read the uncovered OWNED_RANGE cues. Do not turn a long uncovered span "
                "into LOW_INFORMATION merely to satisfy coverage. Reconstruct evidence-backed "
                "events when those cues contain meaningful discussion, topic changes, or reactions."
            ),
        ]
    )


def _window_term_annotations(
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
) -> list[JsonObject]:
    cue_text = " ".join(
        cue.text
        for cue in [
            *cue_window.context_before,
            *cue_window.owned_cues,
            *cue_window.context_after,
        ]
    ).casefold()
    selected: list[DomainKnowledgePromptEntryRecord] = []
    for entry in execution_input.domain_knowledge_entries:
        if entry.prompt_policy == "ALWAYS_FOR_SCOPED_STREAMER":
            selected.append(entry)
            continue
        if entry.prompt_policy == "AUTO_ON_MATCH" and _domain_entry_matches_text(
            entry,
            cue_text,
        ):
            selected.append(entry)
    selected.sort(key=lambda entry: (-entry.priority, entry.entry_id))
    return [
        _domain_prompt_entry_json(entry) for entry in selected[:DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT]
    ]


def _domain_entry_matches_text(
    entry: DomainKnowledgePromptEntryRecord,
    cue_text: str,
) -> bool:
    values = [entry.canonical_name, entry.display_name]
    values.extend(alias.surface_form for alias in entry.aliases)
    return any(value.strip().casefold() in cue_text for value in values if value)


def _domain_prompt_entry_json(
    entry: DomainKnowledgePromptEntryRecord,
) -> JsonObject:
    return {
        "entryId": entry.entry_id,
        "typeKey": entry.type_key,
        "typeLabel": entry.type_label,
        "canonicalForm": entry.canonical_name,
        "displayName": entry.display_name,
        "disambiguation": entry.disambiguation,
        "detail": entry.detail,
        "promptPolicy": entry.prompt_policy,
        "priority": entry.priority,
        "aliases": [_domain_prompt_alias_json(alias) for alias in entry.aliases],
    }


def _domain_prompt_alias_json(
    alias: DomainKnowledgePromptAliasRecord,
) -> JsonObject:
    return {
        "surfaceForm": alias.surface_form,
        "relation": alias.alias_kind,
        "certainty": alias.certainty,
        "applyScope": alias.apply_scope,
        "languageCode": alias.language_code,
        "note": alias.note,
    }


def _compact_prompt_text(text: str, *, limit: int = 1500) -> str | None:
    compacted = " ".join(text.split())
    if not compacted:
        return None
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _format_cue_block(
    cues: list[TranscriptCueRecord],
    all_cues: list[TranscriptCueRecord],
) -> str:
    if not cues:
        return "(none)"
    gaps = _gaps_from_previous(all_cues)
    return "\n".join(_format_cue_line(cue, gaps.get(cue.cue_id)) for cue in cues)


def _format_cue_line(cue: TranscriptCueRecord, gap_from_previous_ms: int | None) -> str:
    gap = ""
    if gap_from_previous_ms is not None and gap_from_previous_ms >= _CUE_GAP_MARK_MS:
        gap = f" +{(gap_from_previous_ms + 500) // 1000}s"
    text = " ".join(cue.text.splitlines())
    return f"{cue.cue_id} {_clock(cue.start_ms)}{gap} | {text}"


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _gaps_from_previous(cues: list[TranscriptCueRecord]) -> dict[str, int | None]:
    return {
        cue.cue_id: max(0, cue.start_ms - cues[index - 1].end_ms) if index > 0 else None
        for index, cue in enumerate(cues)
    }
