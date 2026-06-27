from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.timelines.style import normalize_timeline_style_text
from codex_sdk_cli.infra.micro_events.repository import MicroEventCandidateModel
from codex_sdk_cli.infra.pipeline_jobs.repository import (
    PipelineJobAttemptModel,
    PipelineJobModel,
)
from codex_sdk_cli.infra.timelines.repository import (
    TimelineBlockModel,
    TimelineCompositionModel,
    TimelineEpisodeModel,
    TimelineReviewFlagModel,
    TimelineTopicClusterModel,
)

_FOREIGN_KEY_MODELS = (
    MicroEventCandidateModel,
    PipelineJobAttemptModel,
    PipelineJobModel,
)

_EXAMPLE_LIMIT = 20
_TEXT_KEYS = {
    "title",
    "summary",
    "display_title",
    "display_summary",
    "displayTitle",
    "displaySummary",
    "label",
    "display_label",
    "displayLabel",
    "reason",
}


async def normalize_timeline_style_backfill(
    session: AsyncSession,
    *,
    apply: bool,
    example_limit: int = _EXAMPLE_LIMIT,
) -> JsonObject:
    result: JsonObject = {
        "apply": apply,
        "scannedCompositions": 0,
        "changedFields": 0,
        "changedOutputJsonStrings": 0,
        "unresolvedCount": 0,
        "examples": [],
        "unresolved": [],
    }
    try:
        compositions = list((await session.scalars(select(TimelineCompositionModel))).all())
        result["scannedCompositions"] = len(compositions)
        await _normalize_models(
            session,
            result=result,
            apply=apply,
            model=TimelineCompositionModel,
            table_name="timeline_compositions",
            fields=("title", "summary", "display_title", "display_summary"),
            example_limit=example_limit,
        )
        await _normalize_models(
            session,
            result=result,
            apply=apply,
            model=TimelineBlockModel,
            table_name="timeline_blocks",
            fields=("title", "summary", "display_title", "display_summary"),
            example_limit=example_limit,
        )
        await _normalize_models(
            session,
            result=result,
            apply=apply,
            model=TimelineEpisodeModel,
            table_name="timeline_episodes",
            fields=("title", "summary", "display_title", "display_summary"),
            example_limit=example_limit,
        )
        await _normalize_models(
            session,
            result=result,
            apply=apply,
            model=TimelineTopicClusterModel,
            table_name="timeline_topic_clusters",
            fields=("label", "summary", "display_label"),
            example_limit=example_limit,
        )
        await _normalize_models(
            session,
            result=result,
            apply=apply,
            model=TimelineReviewFlagModel,
            table_name="timeline_review_flags",
            fields=("reason",),
            example_limit=example_limit,
        )
        for composition in compositions:
            output_json = deepcopy(composition.output_json)
            changed_json, changed_count, unresolved = _normalize_json_value(
                output_json,
                path=f"timeline_compositions.output_json#{composition.id}",
                normalize_text=False,
                result=result,
                example_limit=example_limit,
            )
            if changed_count:
                result["changedOutputJsonStrings"] = (
                    int(result["changedOutputJsonStrings"]) + changed_count
                )
                if apply:
                    composition.output_json = changed_json
            if unresolved:
                _append_unresolved(result, unresolved, example_limit=example_limit)
        if apply:
            await session.commit()
        else:
            await session.rollback()
        return result
    except SQLAlchemyError:
        await session.rollback()
        raise


async def _normalize_models(
    session: AsyncSession,
    *,
    result: JsonObject,
    apply: bool,
    model: type[Any],
    table_name: str,
    fields: tuple[str, ...],
    example_limit: int,
) -> None:
    items = list((await session.scalars(select(model))).all())
    for item in items:
        for field in fields:
            original = getattr(item, field)
            if not isinstance(original, str):
                continue
            normalized = normalize_timeline_style_text(original)
            if normalized.changed:
                result["changedFields"] = int(result["changedFields"]) + 1
                _append_example(
                    result,
                    table=table_name,
                    column=field,
                    row_id=item.id,
                    before=original,
                    after=normalized.text,
                    example_limit=example_limit,
                )
                if apply:
                    setattr(item, field, normalized.text)
            if normalized.unresolved_endings:
                _append_unresolved(
                    result,
                    [
                        {
                            "path": f"{table_name}.{field}#{item.id}",
                            "endings": normalized.unresolved_endings,
                        }
                    ],
                    example_limit=example_limit,
                )


def _normalize_json_value(
    value: Any,
    *,
    path: str,
    normalize_text: bool,
    result: JsonObject,
    example_limit: int,
) -> tuple[Any, int, list[JsonObject]]:
    if isinstance(value, dict):
        changed_count = 0
        unresolved: list[JsonObject] = []
        changed: dict[str, Any] = {}
        for key, child in value.items():
            normalized_child, child_count, child_unresolved = _normalize_json_value(
                child,
                path=f"{path}.{key}",
                normalize_text=normalize_text or key in _TEXT_KEYS,
                result=result,
                example_limit=example_limit,
            )
            changed[key] = normalized_child
            changed_count += child_count
            unresolved.extend(child_unresolved)
        return changed, changed_count, unresolved
    if isinstance(value, list):
        changed_items = []
        changed_count = 0
        unresolved: list[JsonObject] = []
        for index, child in enumerate(value):
            normalized_child, child_count, child_unresolved = _normalize_json_value(
                child,
                path=f"{path}[{index}]",
                normalize_text=normalize_text,
                result=result,
                example_limit=example_limit,
            )
            changed_items.append(normalized_child)
            changed_count += child_count
            unresolved.extend(child_unresolved)
        return changed_items, changed_count, unresolved
    if isinstance(value, str) and normalize_text:
        normalized = normalize_timeline_style_text(value)
        if normalized.changed:
            _append_example(
                result,
                table="timeline_compositions",
                column="output_json",
                row_id=None,
                before=value,
                after=normalized.text,
                example_limit=example_limit,
            )
        unresolved = (
            [{"path": path, "endings": normalized.unresolved_endings}]
            if normalized.unresolved_endings
            else []
        )
        return normalized.text, int(normalized.changed), unresolved
    return value, 0, []


def _append_example(
    result: JsonObject,
    *,
    table: str,
    column: str,
    row_id: int | None,
    before: str,
    after: str,
    example_limit: int,
) -> None:
    examples = result["examples"]
    if not isinstance(examples, list) or len(examples) >= example_limit:
        return
    examples.append(
        {
            "table": table,
            "column": column,
            "rowId": row_id,
            "before": before,
            "after": after,
        }
    )


def _append_unresolved(
    result: JsonObject,
    unresolved_items: list[JsonObject],
    *,
    example_limit: int,
) -> None:
    result["unresolvedCount"] = int(result["unresolvedCount"]) + len(unresolved_items)
    unresolved = result["unresolved"]
    if not isinstance(unresolved, list):
        return
    remaining = example_limit - len(unresolved)
    if remaining <= 0:
        return
    unresolved.extend(unresolved_items[:remaining])
