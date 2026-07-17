from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .exceptions import MicroEventExtractionOutputInvalid
from .ports import (
    ApplyScope,
    ContentKind,
    CorrectionType,
    ExcludedRangeReason,
    JsonObject,
    ProgramMode,
    RelationToPrevious,
    SupportLevel,
)


def _normalized_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    return token.upper().replace("-", "_").replace(" ", "_")


def _normalize_program_mode(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "OPENING",
        "JUST_CHATTING",
        "GAME_SETUP",
        "GAMEPLAY",
        "BREAK",
        "POST_GAME",
        "CLOSING",
        "UNKNOWN",
    }
    if token in allowed:
        return token
    aliases = {
        "CHAT": "JUST_CHATTING",
        "TALK": "JUST_CHATTING",
        "TALKING": "JUST_CHATTING",
        "FREE_TALK": "JUST_CHATTING",
        "GAME": "GAMEPLAY",
        "PLAYING_GAME": "GAMEPLAY",
        "ENDING": "CLOSING",
    }
    return aliases.get(token or "", "UNKNOWN")


def _normalize_content_kind(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "ANNOUNCEMENT",
        "PERSONAL_STORY",
        "OPINION",
        "QNA",
        "REACTION",
        "TECHNICAL_SETUP",
        "GAME_PROGRESS",
        "GAME_DISCUSSION",
        "COMMUNITY_REVIEW",
        "MEDIA_REVIEW",
        "META_CHAT",
        "OTHER",
    }
    if token in allowed:
        return token
    aliases = {
        "QUESTION_AND_ANSWER": "QNA",
        "QA": "QNA",
        "GAME_TALK": "GAME_DISCUSSION",
        "GAMEPLAY": "GAME_PROGRESS",
        "SETUP": "TECHNICAL_SETUP",
        "TECHNICAL": "TECHNICAL_SETUP",
        "CHAT": "META_CHAT",
        "JUST_CHATTING": "META_CHAT",
    }
    return aliases.get(token or "", "OTHER")


def _normalize_relation_to_previous(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"NEW_TOPIC", "CONTINUATION", "ASIDE", "RETURN"}
    if token in allowed:
        return token
    aliases = {
        "NEW": "NEW_TOPIC",
        "TOPIC_CHANGE": "NEW_TOPIC",
        "CONTINUE": "CONTINUATION",
        "FOLLOW_UP": "CONTINUATION",
        "SIDE_TOPIC": "ASIDE",
        "BACK": "RETURN",
        "RETURN_TO_TOPIC": "RETURN",
    }
    return aliases.get(token or "", "NEW_TOPIC")


def _normalize_support_level(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"DIRECT", "CONTEXTUAL", "AMBIGUOUS"}
    if token in allowed:
        return token
    aliases = {
        "EXPLICIT": "DIRECT",
        "CLEAR": "DIRECT",
        "INFERRED": "CONTEXTUAL",
        "INDIRECT": "CONTEXTUAL",
        "UNCERTAIN": "AMBIGUOUS",
        "UNKNOWN": "AMBIGUOUS",
    }
    return aliases.get(token or "", "AMBIGUOUS")


def _normalize_excluded_range_reason(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "MUSIC_ONLY",
        "SILENCE_OR_GAP",
        "UNINTELLIGIBLE",
        "LOW_INFORMATION",
        "TECHNICAL_NOISE",
    }
    if token in allowed:
        return token
    aliases = {
        "SILENCE": "SILENCE_OR_GAP",
        "GAP": "SILENCE_OR_GAP",
        "NO_SPEECH": "SILENCE_OR_GAP",
        "INAUDIBLE": "UNINTELLIGIBLE",
        "NOISE": "TECHNICAL_NOISE",
        "TECHNICAL": "TECHNICAL_NOISE",
        "LOW_INFO": "LOW_INFORMATION",
        "NO_INFORMATION": "LOW_INFORMATION",
    }
    return aliases.get(token or "", "LOW_INFORMATION")


def _normalize_correction_type(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "PROPER_NOUN",
        "GAME_TITLE",
        "CONTENT_TITLE",
        "COMMON_WORD",
        "FOOD",
        "PLACE",
        "STREAM_TERM",
        "CONTEXTUAL_TERM",
        "UNCERTAIN",
    }
    if token in allowed:
        return token
    aliases = {
        "PERSON_NAME": "PROPER_NOUN",
        "PERSON": "PROPER_NOUN",
        "PEOPLE": "PROPER_NOUN",
        "CHARACTER_NAME": "PROPER_NOUN",
        "NICKNAME": "PROPER_NOUN",
        "ORGANIZATION": "PROPER_NOUN",
        "ORG_NAME": "PROPER_NOUN",
        "TITLE": "CONTENT_TITLE",
        "VIDEO_TITLE": "CONTENT_TITLE",
        "MEDIA_TITLE": "CONTENT_TITLE",
        "GAME": "GAME_TITLE",
        "GAME_NAME": "GAME_TITLE",
        "LOCATION": "PLACE",
        "TERM": "CONTEXTUAL_TERM",
        "SLANG": "STREAM_TERM",
        "STREAMING_TERM": "STREAM_TERM",
        "UNKNOWN": "UNCERTAIN",
        "OTHER": "UNCERTAIN",
    }
    return aliases.get(token or "", "UNCERTAIN")


def _normalize_apply_scope(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"NONE", "SEARCH_ONLY", "SEARCH_AND_SUMMARY", "DISPLAY_ALLOWED"}
    if token in allowed:
        return token
    aliases = {
        "SEARCH": "SEARCH_ONLY",
        "SUMMARY": "SEARCH_AND_SUMMARY",
        "SEARCH_SUMMARY": "SEARCH_AND_SUMMARY",
        "BOTH": "SEARCH_AND_SUMMARY",
        "DISPLAY": "DISPLAY_ALLOWED",
        "VISIBLE": "DISPLAY_ALLOWED",
        "UNKNOWN": "NONE",
        "OTHER": "NONE",
    }
    return aliases.get(token or "", "NONE")


class _MicroEventOutput(BaseModel):
    start_cue_id: str
    end_cue_id: str
    event: str = Field(min_length=1)
    program_mode: ProgramMode
    content_kind: ContentKind
    topics: list[str] = Field(min_length=1)
    relation_to_previous: RelationToPrevious
    continues_to_next: bool
    evidence_cue_ids: list[str] = Field(min_length=1, max_length=6)
    support_level: SupportLevel

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "program_mode",
        "content_kind",
        "relation_to_previous",
        "support_level",
        mode="before",
    )
    @classmethod
    def _normalize_enum_fields(cls, value: object, info: object) -> object:
        field_name = getattr(info, "field_name", "")
        if field_name == "program_mode":
            return _normalize_program_mode(value)
        if field_name == "content_kind":
            return _normalize_content_kind(value)
        if field_name == "relation_to_previous":
            return _normalize_relation_to_previous(value)
        if field_name == "support_level":
            return _normalize_support_level(value)
        return value


class _ExcludedRangeOutput(BaseModel):
    start_cue_id: str
    end_cue_id: str
    reason: ExcludedRangeReason

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: object) -> object:
        return _normalize_excluded_range_reason(value)


class _AsrCorrectionOutput(BaseModel):
    original: str = Field(min_length=1)
    suggested: str = Field(min_length=1)
    correction_type: CorrectionType
    apply_scope: ApplyScope
    confidence: float = Field(ge=0, le=1)

    model_config = ConfigDict(extra="ignore")

    @field_validator("correction_type", mode="before")
    @classmethod
    def _normalize_correction_type(cls, value: object) -> object:
        return _normalize_correction_type(value)

    @field_validator("apply_scope", mode="before")
    @classmethod
    def _normalize_apply_scope(cls, value: object) -> object:
        return _normalize_apply_scope(value)


class _ExtractorOutput(BaseModel):
    events: list[_MicroEventOutput] = Field(default_factory=list)
    excluded_ranges: list[_ExcludedRangeOutput] = Field(default_factory=list)
    asr_correction_candidates: list[_AsrCorrectionOutput] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


MicroEventOutputWarning = JsonObject


@lru_cache(maxsize=1)
def micro_event_output_schema() -> JsonObject:
    """Return the strict JSON Schema supplied to Codex structured output."""
    schema = cast(JsonObject, _ExtractorOutput.model_json_schema())
    _make_json_schema_strict(schema)
    return schema


def _make_json_schema_strict(node: object) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if node.get("type") == "object" and isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            _make_json_schema_strict(value)
        return
    if isinstance(node, list):
        for value in node:
            _make_json_schema_strict(value)


def _warnings_json(warnings: list[MicroEventOutputWarning]) -> str | None:
    if not warnings:
        return None
    return json.dumps(warnings, ensure_ascii=False)


def _parse_extractor_output(raw_response: str) -> JsonObject:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise MicroEventExtractionOutputInvalid("Extractor returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise MicroEventExtractionOutputInvalid("Extractor output must be a JSON object.")
    return cast(JsonObject, parsed)


def _validate_extractor_output(
    parsed: JsonObject,
) -> tuple[_ExtractorOutput, list[MicroEventOutputWarning]]:
    normalized, warnings = _normalize_extractor_output(parsed)
    try:
        return _ExtractorOutput.model_validate(normalized), warnings
    except ValidationError as exc:
        message = json.dumps(exc.errors(include_url=False), ensure_ascii=False)
        raise MicroEventExtractionOutputInvalid(message) from exc


def _normalize_extractor_output(
    parsed: JsonObject,
) -> tuple[JsonObject, list[MicroEventOutputWarning]]:
    normalized: JsonObject = dict(parsed)
    warnings: list[MicroEventOutputWarning] = []
    _merge_continued_events(normalized, warnings)
    events = normalized.get("events")
    excluded_ranges = normalized.get("excluded_ranges")
    existing_excluded_ranges = excluded_ranges if isinstance(excluded_ranges, list) else []
    moved_excluded_ranges: list[object] = []
    if isinstance(events, list):
        normalized_events: list[object] = []
        for index, event in enumerate(events):
            if _is_misplaced_excluded_range_event(event):
                target_index = len(existing_excluded_ranges) + len(moved_excluded_ranges)
                moved_excluded_ranges.append(
                    _normalize_misplaced_excluded_range_event(
                        event,
                        from_index=index,
                        to_index=target_index,
                        warnings=warnings,
                    )
                )
                continue
            normalized_events.append(_normalize_event_output(event, index, warnings))
        normalized["events"] = normalized_events
    if isinstance(excluded_ranges, list):
        normalized["excluded_ranges"] = [
            _normalize_excluded_range_output(excluded_range, index, warnings)
            for index, excluded_range in enumerate(excluded_ranges)
        ]
    if moved_excluded_ranges:
        normalized["excluded_ranges"] = [
            *(
                normalized["excluded_ranges"]
                if isinstance(normalized.get("excluded_ranges"), list)
                else []
            ),
            *moved_excluded_ranges,
        ]
    term_annotations = normalized.pop("term_annotations", None)
    asr_candidates = normalized.get("asr_correction_candidates")
    if term_annotations is not None:
        moved_asr_candidates = _normalize_term_annotations(
            term_annotations,
            warnings,
        )
        if moved_asr_candidates:
            existing_asr_candidates = asr_candidates if isinstance(asr_candidates, list) else []
            normalized["asr_correction_candidates"] = [
                *existing_asr_candidates,
                *moved_asr_candidates,
            ]
            asr_candidates = normalized["asr_correction_candidates"]
    if isinstance(asr_candidates, list):
        normalized["asr_correction_candidates"] = [
            _normalize_asr_correction_output(candidate, index, warnings)
            for index, candidate in enumerate(asr_candidates)
        ]
    _drop_unknown_top_level_fields(normalized, warnings)
    return normalized, warnings


def _merge_continued_events(
    normalized: JsonObject,
    warnings: list[MicroEventOutputWarning],
) -> None:
    continued_events = normalized.pop("events_continued", None)
    if continued_events is None:
        return
    if not isinstance(continued_events, list):
        warnings.append(
            {
                "type": "ignored_events_continued",
                "path": "events_continued",
                "reason": "expected list",
            }
        )
        return
    events = normalized.get("events")
    if events is None:
        normalized["events"] = continued_events
    elif isinstance(events, list):
        normalized["events"] = [*events, *continued_events]
    else:
        warnings.append(
            {
                "type": "ignored_events_continued",
                "path": "events_continued",
                "reason": "events is not a list",
                "ignoredCount": len(continued_events),
            }
        )
        return
    warnings.append(
        {
            "type": "moved_events_continued_to_events",
            "fromPath": "events_continued",
            "toPath": "events",
            "movedCount": len(continued_events),
        }
    )


def _drop_unknown_top_level_fields(
    normalized: JsonObject,
    warnings: list[MicroEventOutputWarning],
) -> None:
    allowed_fields = {"events", "excluded_ranges", "asr_correction_candidates"}
    for key in sorted(set(normalized) - allowed_fields):
        normalized.pop(key, None)
        warnings.append(
            {
                "type": "ignored_unknown_top_level_field",
                "path": key,
            }
        )


def _normalize_term_annotations(
    annotations: object,
    warnings: list[MicroEventOutputWarning],
) -> list[JsonObject]:
    if not isinstance(annotations, list):
        warnings.append(
            {
                "type": "ignored_term_annotations",
                "path": "term_annotations",
                "reason": "expected list",
            }
        )
        return []

    moved: list[JsonObject] = []
    skipped = 0
    for index, annotation in enumerate(annotations):
        candidate = _term_annotation_to_asr_candidate(annotation)
        if candidate is None:
            skipped += 1
            warnings.append(
                {
                    "type": "ignored_term_annotation",
                    "path": f"term_annotations[{index}]",
                    "reason": "missing term/canonical text",
                }
            )
            continue
        moved.append(candidate)
    warnings.append(
        {
            "type": "moved_term_annotations_to_asr_correction_candidates",
            "fromPath": "term_annotations",
            "toPath": "asr_correction_candidates",
            "originalCount": len(annotations),
            "movedCount": len(moved),
            "skippedCount": skipped,
        }
    )
    return moved


def _term_annotation_to_asr_candidate(annotation: object) -> JsonObject | None:
    if not isinstance(annotation, dict):
        return None
    original = _first_non_empty_string(
        annotation.get("original"),
        annotation.get("surface"),
        annotation.get("term"),
    )
    suggested = _first_non_empty_string(
        annotation.get("suggested"),
        annotation.get("canonical"),
    )
    if original is None or suggested is None:
        return None
    annotation_type = _first_non_empty_string(
        annotation.get("correction_type"),
        annotation.get("annotation_type"),
        annotation.get("type"),
    )
    return {
        "original": original,
        "suggested": suggested,
        "correction_type": _term_annotation_correction_type(annotation_type),
        "apply_scope": _term_annotation_apply_scope(annotation_type),
        "confidence": _term_annotation_confidence(annotation.get("confidence")),
    }


def _first_non_empty_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _term_annotation_correction_type(annotation_type: str | None) -> CorrectionType:
    token = _normalized_token(annotation_type)
    if token in {"WORDPLAY_OR_NICKNAME", "SEARCH_ALIAS"}:
        return "STREAM_TERM"
    if token in {"ASR_ERROR", "SPEAKER_MISTAKE"}:
        return "UNCERTAIN"
    return cast(CorrectionType, _normalize_correction_type(annotation_type))


def _term_annotation_apply_scope(annotation_type: str | None) -> ApplyScope:
    token = _normalized_token(annotation_type)
    if token in {"WORDPLAY_OR_NICKNAME", "SEARCH_ALIAS"}:
        return "SEARCH_AND_SUMMARY"
    if token == "UNCERTAIN":
        return "NONE"
    return "SEARCH_ONLY"


def _term_annotation_confidence(value: object) -> float:
    if isinstance(value, int | float):
        return min(max(float(value), 0.0), 1.0)
    return 0.6


def _is_misplaced_excluded_range_event(event: object) -> bool:
    return (
        isinstance(event, dict)
        and "event" not in event
        and "start_cue_id" in event
        and "end_cue_id" in event
        and "reason" in event
    )


def _normalize_misplaced_excluded_range_event(
    event: object,
    *,
    from_index: int,
    to_index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(event, dict):
        return event
    misplaced_range: JsonObject = {
        "start_cue_id": event["start_cue_id"],
        "end_cue_id": event["end_cue_id"],
        "reason": event["reason"],
    }
    normalized = _normalize_excluded_range_output(
        misplaced_range,
        to_index,
        warnings,
    )
    warnings.append(
        {
            "type": "moved_event_to_excluded_range",
            "fromPath": f"events[{from_index}]",
            "toPath": f"excluded_ranges[{to_index}]",
            "reason": event["reason"],
        }
    )
    return normalized


def _normalize_event_output(
    event: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(event, dict):
        return event
    normalized: JsonObject = dict(event)
    if "event" in normalized and "reason" in normalized:
        normalized.pop("reason", None)
        warnings.append(
            {
                "type": "removed_event_reason_field",
                "path": f"events[{index}].reason",
            }
        )
    _normalize_enum_value(
        normalized,
        "program_mode",
        f"events[{index}].program_mode",
        _normalize_program_mode,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "content_kind",
        f"events[{index}].content_kind",
        _normalize_content_kind,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "relation_to_previous",
        f"events[{index}].relation_to_previous",
        _normalize_relation_to_previous,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "support_level",
        f"events[{index}].support_level",
        _normalize_support_level,
        warnings,
    )
    topics = normalized.get("topics")
    if isinstance(topics, list) and len(topics) > 6:
        normalized["topics"] = topics[:6]
        warnings.append(
            {
                "type": "truncated_topics",
                "path": f"events[{index}].topics",
                "originalCount": len(topics),
                "keptCount": 6,
            }
        )
    evidence_cue_ids = normalized.get("evidence_cue_ids")
    if isinstance(evidence_cue_ids, list) and len(evidence_cue_ids) > 6:
        normalized["evidence_cue_ids"] = evidence_cue_ids[:6]
        warnings.append(
            {
                "type": "truncated_evidence_cue_ids",
                "path": f"events[{index}].evidence_cue_ids",
                "originalCount": len(evidence_cue_ids),
                "keptCount": 6,
            }
        )
    return normalized


def _normalize_excluded_range_output(
    excluded_range: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(excluded_range, dict):
        return excluded_range
    normalized: JsonObject = dict(excluded_range)
    _normalize_enum_value(
        normalized,
        "reason",
        f"excluded_ranges[{index}].reason",
        _normalize_excluded_range_reason,
        warnings,
    )
    return normalized


def _normalize_asr_correction_output(
    candidate: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(candidate, dict):
        return candidate
    normalized: JsonObject = dict(candidate)
    if "evidence_cue_ids" in normalized:
        normalized.pop("evidence_cue_ids", None)
        warnings.append(
            {
                "type": "ignored_asr_evidence_cue_ids",
                "path": f"asr_correction_candidates[{index}].evidence_cue_ids",
            }
        )
    _normalize_enum_value(
        normalized,
        "correction_type",
        f"asr_correction_candidates[{index}].correction_type",
        _normalize_correction_type,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "apply_scope",
        f"asr_correction_candidates[{index}].apply_scope",
        _normalize_apply_scope,
        warnings,
    )
    return normalized


def _normalize_enum_value(
    values: JsonObject,
    key: str,
    path: str,
    normalize: Callable[[object], object],
    warnings: list[MicroEventOutputWarning],
) -> None:
    if key not in values:
        return
    original = values[key]
    normalized = normalize(original)
    values[key] = normalized
    if original != normalized:
        warnings.append(
            {
                "type": "normalized_enum",
                "path": path,
                "original": original,
                "normalized": normalized,
            }
        )


def _validate_event_cue_refs(
    event: _MicroEventOutput,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning],
    event_index: int,
) -> tuple[str, str, int, int, list[str]]:
    start_cue_id, end_cue_id, start_position, end_position = _validate_range_cue_refs(
        event.start_cue_id,
        event.end_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path_prefix=f"events[{event_index}]",
    )
    valid_evidence_cue_ids: list[str] = []
    removed_evidence_cue_ids: list[str] = []
    for cue_id in event.evidence_cue_ids:
        resolved_cue_id = _resolve_cue_id(
            cue_id,
            cue_id_to_position,
            warnings=warnings,
            path=f"events[{event_index}].evidence_cue_ids",
            min_position=start_position,
            max_position=end_position,
        )
        if start_position <= cue_id_to_position[resolved_cue_id] <= end_position:
            valid_evidence_cue_ids.append(resolved_cue_id)
        else:
            removed_evidence_cue_ids.append(resolved_cue_id)
    if removed_evidence_cue_ids:
        warnings.append(
            {
                "type": "removed_out_of_event_range_evidence_cue_ids",
                "path": f"events[{event_index}].evidence_cue_ids",
                "removedCueIds": removed_evidence_cue_ids,
            }
        )
    if not valid_evidence_cue_ids:
        raise MicroEventExtractionOutputInvalid(
            "event must have at least one evidence_cue_id inside its cue range."
        )
    return start_cue_id, end_cue_id, start_position, end_position, valid_evidence_cue_ids


def _validate_range_cue_refs(
    start_cue_id: str,
    end_cue_id: str,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning] | None = None,
    path_prefix: str | None = None,
) -> tuple[str, str, int, int]:
    resolved_start_cue_id = _resolve_cue_id(
        start_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path=f"{path_prefix}.start_cue_id" if path_prefix else None,
    )
    resolved_end_cue_id = _resolve_cue_id(
        end_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path=f"{path_prefix}.end_cue_id" if path_prefix else None,
    )
    start_position = cue_id_to_position[resolved_start_cue_id]
    end_position = cue_id_to_position[resolved_end_cue_id]
    if start_position > end_position:
        raise MicroEventExtractionOutputInvalid("start_cue_id must not come after end_cue_id.")
    return resolved_start_cue_id, resolved_end_cue_id, start_position, end_position


def _validate_evidence_cue_ids(
    evidence_cue_ids: list[str],
    cue_id_to_position: dict[str, int],
) -> list[str]:
    return [_resolve_cue_id(cue_id, cue_id_to_position) for cue_id in evidence_cue_ids]


def _resolve_cue_id(
    cue_id: str,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning] | None = None,
    path: str | None = None,
    min_position: int | None = None,
    max_position: int | None = None,
) -> str:
    if cue_id not in cue_id_to_position:
        resolved_cue_id = _unique_nearby_cue_id(
            cue_id,
            cue_id_to_position,
            min_position=min_position,
            max_position=max_position,
        )
        if resolved_cue_id is not None:
            if warnings is not None:
                warnings.append(
                    {
                        "type": "repaired_cue_id",
                        "path": path or "cue_id",
                        "originalCueId": cue_id,
                        "repairedCueId": resolved_cue_id,
                    }
                )
            return resolved_cue_id
        raise MicroEventExtractionOutputInvalid(
            f"Extractor referenced cue_id outside OWNED_RANGE: {cue_id}"
        )
    return cue_id


def _unique_nearby_cue_id(
    cue_id: str,
    cue_id_to_position: dict[str, int],
    *,
    min_position: int | None = None,
    max_position: int | None = None,
) -> str | None:
    split = cue_id.rsplit("-c", maxsplit=1)
    if len(split) != 2:
        return None
    prefix, suffix = split
    matches = [
        candidate
        for candidate, position in cue_id_to_position.items()
        if candidate.startswith(f"{prefix}-c")
        and (min_position is None or position >= min_position)
        and (max_position is None or position <= max_position)
        and _edit_distance_at_most_one(candidate.rsplit("-c", maxsplit=1)[1], suffix)
    ]
    return matches[0] if len(matches) == 1 else None


def _validate_low_information_coverage(
    ranges: list[tuple[ExcludedRangeReason, int, int]],
    *,
    owned_cue_count: int,
) -> None:
    if owned_cue_count <= 0:
        return
    for reason, start_position, end_position in ranges:
        cue_count = end_position - start_position + 1
        if (
            reason == "LOW_INFORMATION"
            and cue_count >= 100
            and cue_count / owned_cue_count >= 0.5
        ):
            raise MicroEventExtractionOutputInvalid(
                "Extractor classified an implausibly large LOW_INFORMATION range "
                f"({cue_count}/{owned_cue_count} owned cues)."
            )


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1
    if len(left) > len(right):
        left, right = right, left
    left_index = 0
    right_index = 0
    edits = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        edits += 1
        right_index += 1
        if edits > 1:
            return False
    return edits + (len(right) - right_index) == 1


def _validate_owned_range_coverage(
    ranges: list[tuple[str, int, int]],
    *,
    owned_cue_count: int,
) -> None:
    if not ranges:
        raise MicroEventExtractionOutputInvalid(
            "Extractor must cover OWNED_RANGE with events or excluded_ranges."
        )
    sorted_ranges = sorted(ranges, key=lambda item: item[1])
    previous_end = -1
    for kind, start_position, end_position in sorted_ranges:
        if start_position <= previous_end:
            raise MicroEventExtractionOutputInvalid(
                f"Extractor returned overlapping {kind} ranges."
            )
        if start_position != previous_end + 1:
            raise MicroEventExtractionOutputInvalid("Extractor left a gap in OWNED_RANGE coverage.")
        previous_end = end_position
    if previous_end != owned_cue_count - 1:
        raise MicroEventExtractionOutputInvalid(
            "Extractor did not cover every owned cue exactly once."
        )


def _support_level_confidence(support_level: SupportLevel) -> float:
    if support_level == "DIRECT":
        return 0.9
    if support_level == "CONTEXTUAL":
        return 0.7
    return 0.4


def _normalized_topics(topics: list[str]) -> list[str]:
    normalized: list[str] = []
    for topic in topics:
        stripped = topic.strip()
        if stripped:
            normalized.append(stripped)
        if len(normalized) == 6:
            break
    return normalized or ["UNKNOWN"]
