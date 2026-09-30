from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codex_sdk_cli.domains.micro_events.window_sizing import micro_window_count
from codex_sdk_cli.domains.micro_events.windowing import _cue_windows, _format_cue_block
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRecord

NOW = datetime(2026, 9, 30, tzinfo=UTC)
MINUTE_MS = 60_000


def _cue(index: int, start_ms: int, end_ms: int, text: str | None = None) -> TranscriptCueRecord:
    return TranscriptCueRecord(
        id=index,
        transcript_id=1,
        cue_id=f"tr1-c{index:06d}",
        cue_index=index,
        text=text or f"cue {index}",
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        source_segment_index=index - 1,
        source_job_id=None,
        source_job_attempt_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _overlapping_cues(*, total_minutes: int, step_ms: int = 3_000) -> list[TranscriptCueRecord]:
    """Auto-caption shaped cues: each cue ends after the next one starts."""
    return [
        _cue(index, start_ms, start_ms + step_ms + 2_000)
        for index, start_ms in enumerate(range(0, total_minutes * MINUTE_MS, step_ms), start=1)
    ]


@pytest.mark.parametrize(
    ("span_minutes", "expected"),
    [(0, 1), (31, 1), (37, 1), (38, 2), (44, 2), (62, 2), (95, 3), (120, 4), (433, 14)],
)
def test_micro_window_count_balances_short_remainders(span_minutes: int, expected: int) -> None:
    assert micro_window_count(span_minutes * MINUTE_MS, window_minutes=30) == expected


def test_cue_windows_assign_each_boundary_straddling_cue_once() -> None:
    cues = _overlapping_cues(total_minutes=120)

    windows = _cue_windows(cues, window_minutes=30, overlap_minutes=5)

    owned_ids = [cue.cue_id for window in windows for cue in window.owned_cues]
    assert owned_ids == [cue.cue_id for cue in cues]
    assert [window.window_index for window in windows] == [1, 2, 3, 4]


def test_cue_windows_do_not_create_window_for_last_cue_crossing_boundary() -> None:
    cues = [
        _cue(1, 0, 3_000),
        _cue(2, 60 * MINUTE_MS - 2_600, 60 * MINUTE_MS + 400),
    ]

    windows = _cue_windows(cues, window_minutes=30, overlap_minutes=5)

    assert [[cue.cue_id for cue in window.owned_cues] for window in windows] == [
        ["tr1-c000001"],
        ["tr1-c000002"],
    ]


def test_cue_windows_spread_short_tail_across_windows() -> None:
    cues = _overlapping_cues(total_minutes=95, step_ms=60_000)

    windows = _cue_windows(cues, window_minutes=30, overlap_minutes=5)

    assert len(windows) == 3
    owned_counts = [len(window.owned_cues) for window in windows]
    assert max(owned_counts) - min(owned_counts) <= 1


def test_cue_windows_context_uses_neighbor_cues_by_start_time() -> None:
    cues = [
        _cue(index, minute * MINUTE_MS, (minute + 1) * MINUTE_MS)
        for index, minute in enumerate(range(60), start=1)
    ]

    first, second = _cue_windows(cues, window_minutes=30, overlap_minutes=5)

    assert first.context_before == []
    assert second.context_after == []
    assert [cue.start_ms // MINUTE_MS for cue in first.context_after] == [30, 31, 32, 33, 34]
    assert [cue.start_ms // MINUTE_MS for cue in second.context_before] == [25, 26, 27, 28, 29]
    assert set(first.context_after) <= set(second.owned_cues)
    assert set(second.context_before) <= set(first.owned_cues)


def test_format_cue_block_marks_silent_gaps_and_flattens_line_breaks() -> None:
    cues = [
        _cue(1, 3_600_000, 3_602_000),
        _cue(2, 3_602_900, 3_605_000, text="first\nsecond"),
        _cue(3, 3_606_200, 3_608_000),
        _cue(4, 3_623_000, 3_624_000),
    ]

    assert _format_cue_block(cues, cues).splitlines() == [
        "tr1-c000001 1:00:00 | cue 1",
        "tr1-c000002 1:00:02 | first second",
        "tr1-c000003 1:00:06 +1s | cue 3",
        "tr1-c000004 1:00:23 +15s | cue 4",
    ]
    assert _format_cue_block([], cues) == "(none)"
