from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import JsonObject

from .ports import WorkflowCandidateChannel, WorkflowCandidateSnapshot


@dataclass(frozen=True, slots=True)
class DailyQuotaWindow:
    quota_date: date
    timezone: str
    started_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowAllocationPlan:
    candidates: tuple[VideoRecord, ...]
    admitted_before_count: int
    admitted_after_count: int
    remaining_after_count: int
    floor_feasible: bool
    channel_allocations: tuple[tuple[int, int], ...]


def daily_quota_window(now: datetime, timezone: str) -> DailyQuotaWindow:
    zone = ZoneInfo(timezone)
    local_now = _aware(now).astimezone(zone)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=zone)
    local_end = local_start + timedelta(days=1)
    return DailyQuotaWindow(
        quota_date=local_now.date(),
        timezone=timezone,
        started_at=local_start.astimezone(UTC),
        ends_at=local_end.astimezone(UTC),
    )


def allocate_workflow_candidates(
    snapshot: WorkflowCandidateSnapshot,
    *,
    daily_limit: int,
    channel_minimum: int,
    tick_limit: int,
    quota_date: date,
) -> WorkflowAllocationPlan:
    daily_remaining = max(0, daily_limit - snapshot.admitted_today_count)
    tick_capacity = min(tick_limit, daily_remaining)
    channels = [item for item in snapshot.channels if item.candidates]
    queues = {item.channel_id: deque(item.candidates) for item in channels}
    admitted = {item.channel_id: item.admitted_today_count for item in channels}
    selected: list[VideoRecord] = []
    allocations = {item.channel_id: 0 for item in channels}
    ordered_ids = _rotated_channel_ids(channels, quota_date)
    required_floor_slots = sum(
        max(
            0,
            min(channel_minimum, item.admitted_today_count + len(item.candidates))
            - item.admitted_today_count,
        )
        for item in channels
    )
    floor_feasible = required_floor_slots <= daily_remaining

    for target_count in range(1, channel_minimum + 1):
        for channel_id in ordered_ids:
            if len(selected) >= tick_capacity:
                break
            queue = queues[channel_id]
            if admitted[channel_id] >= target_count or not queue:
                continue
            selected.append(queue.popleft())
            admitted[channel_id] += 1
            allocations[channel_id] += 1
        if len(selected) >= tick_capacity:
            break

    extra_capacity = tick_capacity - len(selected)
    if extra_capacity > 0:
        extras = _proportional_allocations(
            queues,
            capacity=extra_capacity,
            ordered_ids=ordered_ids,
        )
        for channel_id in ordered_ids:
            queue = queues[channel_id]
            for _ in range(extras[channel_id]):
                selected.append(queue.popleft())
                allocations[channel_id] += 1

    admitted_after = snapshot.admitted_today_count + len(selected)
    return WorkflowAllocationPlan(
        candidates=tuple(selected),
        admitted_before_count=snapshot.admitted_today_count,
        admitted_after_count=admitted_after,
        remaining_after_count=max(0, daily_limit - admitted_after),
        floor_feasible=floor_feasible,
        channel_allocations=tuple(
            (channel_id, allocations[channel_id])
            for channel_id in ordered_ids
            if allocations[channel_id] > 0
        ),
    )


def daily_quota_json(
    snapshot: WorkflowCandidateSnapshot,
    *,
    window: DailyQuotaWindow,
    daily_limit: int,
    channel_minimum: int,
) -> JsonObject:
    daily_remaining = max(0, daily_limit - snapshot.admitted_today_count)
    required_floor_slots = sum(
        max(
            0,
            min(channel_minimum, item.admitted_today_count + len(item.candidates))
            - item.admitted_today_count,
        )
        for item in snapshot.channels
    )
    return {
        "quotaDate": window.quota_date.isoformat(),
        "timezone": window.timezone,
        "limit": daily_limit,
        "admitted": snapshot.admitted_today_count,
        "remaining": daily_remaining,
        "minimumPerChannel": channel_minimum,
        "floorFeasible": required_floor_slots <= daily_remaining,
        "channels": [
            {
                "channelId": item.channel_id,
                "eligibleBacklogCount": len(item.candidates),
                "admittedTodayCount": item.admitted_today_count,
            }
            for item in snapshot.channels
        ],
    }


def _proportional_allocations(
    queues: dict[int, deque[VideoRecord]],
    *,
    capacity: int,
    ordered_ids: tuple[int, ...],
) -> dict[int, int]:
    counts = {channel_id: len(queues[channel_id]) for channel_id in ordered_ids}
    total = sum(counts.values())
    capacity = min(capacity, total)
    if capacity <= 0 or total <= 0:
        return dict.fromkeys(ordered_ids, 0)

    raw = {
        channel_id: capacity * counts[channel_id] / total
        for channel_id in ordered_ids
    }
    allocated = {
        channel_id: min(counts[channel_id], int(raw[channel_id]))
        for channel_id in ordered_ids
    }
    remaining = capacity - sum(allocated.values())
    rank = {channel_id: position for position, channel_id in enumerate(ordered_ids)}
    remainder_order = sorted(
        ordered_ids,
        key=lambda channel_id: (
            -(raw[channel_id] - int(raw[channel_id])),
            rank[channel_id],
        ),
    )
    while remaining > 0:
        progressed = False
        for channel_id in remainder_order:
            if remaining <= 0:
                break
            if allocated[channel_id] >= counts[channel_id]:
                continue
            allocated[channel_id] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            break
    return allocated


def _rotated_channel_ids(
    channels: list[WorkflowCandidateChannel],
    quota_date: date,
) -> tuple[int, ...]:
    channel_ids = sorted(item.channel_id for item in channels)
    if not channel_ids:
        return ()
    offset = quota_date.toordinal() % len(channel_ids)
    return tuple(channel_ids[offset:] + channel_ids[:offset])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
