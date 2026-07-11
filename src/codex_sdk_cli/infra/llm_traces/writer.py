from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import structlog

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent, LlmTraceRecorderPort

_DATE_FORMAT = "%Y-%m-%d"
_LOGGER = structlog.get_logger(__name__)


class FileLlmTraceRecorder(LlmTraceRecorderPort):
    def __init__(
        self,
        *,
        base_dir: Path,
        raw_response_enabled: bool = True,
        retention_days: int = 14,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_dir = base_dir.resolve()
        self._raw_response_enabled = raw_response_enabled
        self._retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._pruned = False

    async def record_event(self, event: LlmTraceEvent) -> None:
        try:
            async with self._lock:
                await asyncio.to_thread(self._record_event_sync, event)
        except Exception as exc:  # pragma: no cover - tracing must not fail the job
            await _LOGGER.awarning(
                "llm_trace_write_failed",
                source=event.source,
                phase=event.phase,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )

    def _record_event_sync(self, event: LlmTraceEvent) -> None:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if not self._pruned:
            self._prune_old_trace_dirs(now)
            self._pruned = True
        date_dir = self._base_dir / now.strftime(_DATE_FORMAT)
        raw_dir = date_dir / "raw"
        date_dir.mkdir(parents=True, exist_ok=True)

        payload = _event_payload(event, now)
        if event.prompt_text is not None:
            prompt_bytes = event.prompt_text.encode("utf-8")
            payload["promptLength"] = len(prompt_bytes)
            payload["promptSha256"] = hashlib.sha256(prompt_bytes).hexdigest()
        else:
            payload["promptLength"] = None
            payload["promptSha256"] = None

        if event.raw_response_text is not None:
            raw_bytes = event.raw_response_text.encode("utf-8")
            payload["rawResponseLength"] = len(raw_bytes)
            raw_response_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            payload["rawResponseSha256"] = raw_response_sha256
            payload["rawResponsePath"] = None
            if self._raw_response_enabled:
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / _raw_response_filename(
                    event,
                    now,
                    raw_response_sha256,
                )
                raw_path.write_text(event.raw_response_text, encoding="utf-8")
                payload["rawResponsePath"] = str(raw_path)
        else:
            payload["rawResponsePath"] = None
            payload["rawResponseLength"] = None
            payload["rawResponseSha256"] = None

        if event.metadata:
            payload["metadata"] = event.metadata

        event_path = date_dir / f"{_safe_token(event.source)}.jsonl"
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        _LOGGER.debug(
            "llm_trace_recorded",
            source=event.source,
            phase=event.phase,
            event_path=str(event_path),
        )

    def _prune_old_trace_dirs(self, now: datetime) -> None:
        if self._retention_days < 1 or not self._base_dir.exists():
            return
        cutoff = now.date() - timedelta(days=self._retention_days)
        for child in self._base_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                child_date = datetime.strptime(child.name, _DATE_FORMAT).date()
            except ValueError:
                continue
            if child_date < cutoff:
                shutil.rmtree(child)


def _event_payload(event: LlmTraceEvent, now: datetime) -> dict[str, object]:
    return {
        "ts": now.isoformat(),
        "source": event.source,
        "operation": event.operation,
        "phase": event.phase,
        "videoTaskId": event.video_task_id,
        "workItemId": event.work_item_id,
        "workAttemptId": event.work_attempt_id,
        "videoId": event.video_id,
        "jobId": event.job_id,
        "jobAttemptId": event.job_attempt_id,
        "windowIndex": event.window_index,
        "windowCount": event.window_count,
        "repairIndex": event.repair_index,
        "targetEpisodeId": event.target_episode_id,
        "repairReason": event.repair_reason,
        "model": event.model,
        "reasoningEffort": event.reasoning_effort,
        "threadId": event.thread_id,
        "turnId": event.turn_id,
        "status": event.status,
        "elapsedMs": event.elapsed_ms,
        "rawResponsePath": None,
        "rawResponseLength": None,
        "rawResponseSha256": None,
        "errorType": event.error_type,
        "errorMessage": event.error_message,
    }


def _raw_response_filename(event: LlmTraceEvent, now: datetime, sha256: str) -> str:
    parts = [
        now.strftime("%H%M%S%f"),
        _safe_token(event.source),
        _safe_token(event.operation),
        _safe_token(event.phase),
    ]
    if event.video_task_id is not None:
        parts.append(f"task-{event.video_task_id}")
    if event.work_item_id is not None:
        parts.append(f"work-{event.work_item_id}")
    if event.work_attempt_id is not None:
        parts.append(f"work-attempt-{event.work_attempt_id}")
    if event.job_attempt_id is not None:
        parts.append(f"attempt-{event.job_attempt_id}")
    if event.window_index is not None:
        parts.append(f"window-{event.window_index}")
    if event.repair_index is not None:
        parts.append(f"repair-{event.repair_index}")
    if event.target_episode_id is not None:
        parts.append(_safe_token(event.target_episode_id))
    parts.extend([sha256[:12], uuid4().hex[:8]])
    return ".".join(parts) + ".response.txt"


def _safe_token(value: object) -> str:
    token = str(value or "none").strip().lower()
    token = re.sub(r"[^a-z0-9_-]+", "-", token)
    return token.strip("-") or "none"
