from __future__ import annotations

# Windows may stretch to 5/4 of the target length before another window is added.
_WINDOW_STRETCH_NUMERATOR = 5
_WINDOW_STRETCH_DENOMINATOR = 4


def micro_window_count(span_ms: int, *, window_minutes: int) -> int:
    """Return the number of equal windows whose length is closest to the target.

    A remainder shorter than half a window is spread across the other windows instead of
    becoming its own short window, as long as no window exceeds 5/4 of the target.
    """
    target_ms = window_minutes * 60_000
    count = max(1, (span_ms + target_ms // 2) // target_ms)
    # Rounding can only overshoot the stretch limit when it collapses to one window.
    if span_ms * _WINDOW_STRETCH_DENOMINATOR > count * target_ms * _WINDOW_STRETCH_NUMERATOR:
        count += 1
    return count
