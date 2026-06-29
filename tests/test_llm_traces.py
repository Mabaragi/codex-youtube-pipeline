from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent, NoopLlmTraceRecorder
from codex_sdk_cli.infra.llm_traces.writer import FileLlmTraceRecorder


@pytest.mark.anyio
async def test_file_llm_trace_writer_creates_jsonl_and_raw_response(tmp_path) -> None:
    writer = FileLlmTraceRecorder(
        base_dir=tmp_path,
        clock=lambda: datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC),
    )
    raw_response = "응답 원문\nsecond line"
    prompt = "prompt body"

    await writer.record_event(
        LlmTraceEvent(
            source="micro_event_extract",
            operation="extract_window",
            phase="llm_response_received",
            video_task_id=186,
            video_id=91,
            job_id=301,
            job_attempt_id=401,
            window_index=2,
            window_count=3,
            model="gpt-5.1",
            reasoning_effort="high",
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            elapsed_ms=1234,
            prompt_text=prompt,
            raw_response_text=raw_response,
        )
    )

    event_path = tmp_path / "2026-06-29" / "micro_event_extract.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]

    assert len(events) == 1
    event = events[0]
    raw_path = event["rawResponsePath"]
    assert isinstance(raw_path, str)
    assert event["rawResponseLength"] == len(raw_response.encode("utf-8"))
    assert event["rawResponseSha256"] == hashlib.sha256(
        raw_response.encode("utf-8")
    ).hexdigest()
    assert event["promptLength"] == len(prompt.encode("utf-8"))
    assert event["promptSha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert "rawResponseText" not in event
    assert "promptText" not in event
    assert raw_response not in event_path.read_text(encoding="utf-8")
    assert Path(raw_path).read_text(encoding="utf-8") == raw_response


@pytest.mark.anyio
async def test_file_llm_trace_writer_can_disable_raw_response_files(tmp_path) -> None:
    writer = FileLlmTraceRecorder(
        base_dir=tmp_path,
        raw_response_enabled=False,
        clock=lambda: datetime(2026, 6, 29, 12, tzinfo=UTC),
    )

    await writer.record_event(
        LlmTraceEvent(
            source="timeline_compose",
            operation="compose_video",
            phase="compose_response_received",
            raw_response_text="raw",
        )
    )

    event_path = tmp_path / "2026-06-29" / "timeline_compose.jsonl"
    event = json.loads(event_path.read_text(encoding="utf-8"))

    assert event["rawResponsePath"] is None
    assert event["rawResponseLength"] == 3
    assert event["rawResponseSha256"] == hashlib.sha256(b"raw").hexdigest()
    assert not (tmp_path / "2026-06-29" / "raw").exists()


@pytest.mark.anyio
async def test_noop_llm_trace_writer_creates_no_files(tmp_path) -> None:
    writer = NoopLlmTraceRecorder()

    await writer.record_event(
        LlmTraceEvent(
            source="micro_event_extract",
            operation="extract_window",
            phase="window_started",
        )
    )

    assert list(tmp_path.iterdir()) == []
