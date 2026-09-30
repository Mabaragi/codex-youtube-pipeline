from __future__ import annotations

from copy import deepcopy

from .models import EpisodeRange, SegmentClassificationError
from .schemas import SegmentOutput


def normalize_segments(
    output: SegmentOutput, episodes: tuple[EpisodeRange, ...]
) -> list[dict[str, object]]:
    """Check episode coverage, then enforce the approved duration rules in milliseconds."""
    cursor = 1
    rows: list[dict[str, object]] = []
    for raw in output.segments:
        if raw.start_episode != cursor or not cursor <= raw.end_episode <= len(episodes):
            raise SegmentClassificationError("Segments must cover all episodes once, in order.")
        start, end = episodes[cursor - 1].start_ms, episodes[raw.end_episode - 1].end_ms
        if start < 0 or end <= start:
            raise SegmentClassificationError("A segment has an invalid time range.")
        if raw.phase == "opening" and cursor != 1:
            raise SegmentClassificationError("Opening must be at the start of the broadcast.")
        if raw.phase == "closing" and raw.end_episode != len(episodes):
            raise SegmentClassificationError("Closing must be at the end of the broadcast.")
        if not raw.collab and raw.partners:
            raise SegmentClassificationError("Solo segments cannot have collaboration partners.")
        rows.append(
            {
                **raw.model_dump(by_alias=True),
                "startMs": start,
                "endMs": end,
                "startEpisodeId": episodes[cursor - 1].episode_id,
                "endEpisodeId": episodes[raw.end_episode - 1].episode_id,
            }
        )
        cursor = raw.end_episode + 1
    if cursor != len(episodes) + 1:
        raise SegmentClassificationError("Some episodes were omitted.")
    rows = _continuous_times(rows)
    rows = _limit_edge_phases(rows)
    # Watch duration is measured over the entire corner, including collab/member boundaries.
    rows = _short_watch_corners(rows)
    rows = _absorb_short_chat(rows)
    rows = _absorb_short_segments(rows)
    rows = _merge_adjacent(rows)
    validate_time_coverage(rows, episodes)
    return rows


def validate_time_coverage(
    rows: list[dict[str, object]], episodes: tuple[EpisodeRange, ...]
) -> None:
    if not episodes:
        if rows:
            raise SegmentClassificationError("An empty timeline cannot contain segments.")
        return
    if not rows or rows[0]["startMs"] != episodes[0].start_ms:
        raise SegmentClassificationError("Segments do not start with the first episode.")
    frontier = episodes[0].start_ms
    for row in rows:
        start, end = _integer(row["startMs"]), _integer(row["endMs"])
        if start != frontier or end <= start:
            raise SegmentClassificationError("Segment time ranges have gaps or overlaps.")
        frontier = end
    if frontier != episodes[-1].end_ms:
        raise SegmentClassificationError("Segments do not end with the last episode.")


def public_segments(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        result.append(
            {
                "start": _integer(row["startMs"]) / 1000,
                "end": _integer(row["endMs"]) / 1000,
                **{
                    key: row[key]
                    for key in (
                        "category",
                        "phase",
                        "label",
                        "game",
                        "gameUncertain",
                        "content",
                        "collab",
                        "partners",
                    )
                },
            }
        )
    return result


def _continuous_times(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    for index in range(len(rows) - 1):
        boundary = _integer(rows[index + 1]["startMs"])
        if boundary <= _integer(rows[index]["startMs"]):
            raise SegmentClassificationError("Episode start times must increase.")
        rows[index]["endMs"] = boundary
    return rows


def _limit_edge_phases(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        duration = _integer(row["endMs"]) - _integer(row["startMs"])
        if row["phase"] == "main" or duration <= 900_000:
            result.append(row)
            continue
        opening = row["phase"] == "opening"
        edge = _integer(row["startMs"]) + 900_000 if opening else _integer(row["endMs"]) - 900_000
        first, second = deepcopy(row), deepcopy(row)
        first["endMs"], second["startMs"] = edge, edge
        (second if opening else first)["phase"] = "main"
        main = second if opening else first
        if main["category"] == "chat":
            main["label"] = "저스트 채팅"
        result.extend((first, second))
    return result


def _short_watch_corners(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    index = 0
    while index < len(rows):
        end = index + 1
        while end < len(rows) and rows[end]["category"] == rows[index]["category"]:
            end += 1
        if rows[index]["category"] == "watch":
            duration = _integer(rows[end - 1]["endMs"]) - _integer(rows[index]["startMs"])
            if duration < 1_200_000:
                for row in rows[index:end]:
                    row["category"] = "chat"
        index = end
    return rows


def _activity_key(row: dict[str, object]) -> tuple[object, ...]:
    return row["category"], row["game"], row["content"]


def _mergeable_with(row: dict[str, object], target: dict[str, object]) -> bool:
    return all(row[key] == target[key] for key in ("phase", "collab", "partners"))


def _absorb_into(row: dict[str, object], target: dict[str, object]) -> None:
    # Change activity only: preserve actual join/leave boundaries and partners.
    for key in ("category", "game", "gameUncertain", "content"):
        row[key] = target[key]
    # Borrow the label only when the row will merge into the target; otherwise the
    # target's label would describe a range it does not cover.
    if _mergeable_with(row, target):
        row["label"] = target["label"]


def _absorb_short_chat(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    for index in range(1, len(rows) - 1):
        row, before, after = rows[index], rows[index - 1], rows[index + 1]
        if (
            row["category"] == "chat"
            and row["phase"] == "main"
            and _integer(row["endMs"]) - _integer(row["startMs"]) < 600_000
            and _activity_key(before) == _activity_key(after)
        ):
            _absorb_into(row, before if _mergeable_with(row, before) else after)
    return rows


def _absorb_short_segments(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    index = 0
    while index < len(rows):
        row = rows[index]
        # Opening and closing are short by nature; they keep their own activity.
        if (
            len(rows) == 1
            or row["phase"] != "main"
            or _integer(row["endMs"]) - _integer(row["startMs"]) >= 300_000
        ):
            index += 1
            continue
        neighbor = index + 1 if index == 0 or row["category"] == "setup" else index - 1
        if neighbor >= len(rows):
            neighbor = index - 1
        _absorb_into(row, rows[neighbor])
        index += 1
    return rows


def _merge_adjacent(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    keys = (
        "category",
        "label",
        "phase",
        "game",
        "gameUncertain",
        "content",
        "collab",
        "partners",
    )
    for row in rows:
        if result and all(result[-1][key] == row[key] for key in keys):
            result[-1]["endMs"] = row["endMs"]
            result[-1]["endEpisode"] = row["endEpisode"]
            result[-1]["endEpisodeId"] = row["endEpisodeId"]
        else:
            result.append(row)
    return result


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SegmentClassificationError("Segment boundaries must be integer milliseconds.")
    return value
