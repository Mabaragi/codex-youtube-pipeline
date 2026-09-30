from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from codex_sdk_cli.application.errors import ApplicationError
from codex_sdk_cli.application.segments.executors import SegmentClassificationExecutor
from codex_sdk_cli.application.segments.ports import SegmentResultStorePort, SegmentSourceReaderPort
from codex_sdk_cli.application.work.execution import WorkExecutionContext
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.domains.codex.ports import CodexRunCommand, CodexRunResult, CodexRuntimePort
from codex_sdk_cli.domains.segments.models import (
    EpisodeRange,
    SegmentClassificationError,
    SegmentSource,
)
from codex_sdk_cli.domains.segments.policy import normalize_segments, public_segments
from codex_sdk_cli.domains.segments.schemas import SegmentOutput
from codex_sdk_cli.domains.work.models import WorkExecutionMode
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.segments import run_worker


def raw(start=1, end=1, category="chat", **extra):
    return {
        "startEpisode": start,
        "endEpisode": end,
        "category": category,
        "label": category,
        "phase": "main",
        "game": None,
        "gameUncertain": False,
        "content": None,
        "collab": False,
        "partners": [],
        **extra,
    }


def output(*rows):
    return SegmentOutput.model_validate({"segments": list(rows)})


@pytest.mark.parametrize(
    "rows",
    [
        [raw(1, 1)],
        [raw(2, 2)],
        [raw(1, 2), raw(2, 2)],
        [raw(1, 2, collab=False, partners=["Guest"])],
        [raw(1, 1), raw(2, 2, phase="opening")],
    ],
)
def test_rejects_omission_overlap_and_false_collab(rows):
    episodes = (EpisodeRange("e1", 0, 600_000), EpisodeRange("e2", 600_000, 1_200_000))
    with pytest.raises(SegmentClassificationError):
        normalize_segments(output(*rows), episodes)


def test_watch_duration_spans_member_changes_and_keeps_join_boundary():
    episodes = (EpisodeRange("e1", 0, 600_000), EpisodeRange("e2", 600_000, 1_800_000))
    rows = normalize_segments(
        output(
            raw(1, 1, "watch"),
            raw(2, 2, "watch", collab=True, partners=["Guest"]),
        ),
        episodes,
    )
    assert [row["category"] for row in rows] == ["watch", "watch"]
    assert [row["collab"] for row in rows] == [False, True]
    assert public_segments(rows)[1]["start"] == 600


def test_short_chat_is_absorbed_without_spreading_collaboration():
    episodes = (
        EpisodeRange("e1", 0, 1_200_000),
        EpisodeRange("e2", 1_200_000, 1_320_000),
        EpisodeRange("e3", 1_320_000, 2_400_000),
    )
    rows = normalize_segments(
        output(
            raw(1, 1, "game", game="Test"),
            raw(2, 2, collab=True, partners=["Guest"]),
            raw(3, 3, "game", game="Test", collab=True, partners=["Guest"]),
        ),
        episodes,
    )
    assert len(rows) == 2
    assert rows[1]["startMs"] == 1_200_000
    assert rows[0]["collab"] is False
    assert rows[1]["category"] == "game"


def test_short_closing_keeps_its_own_activity_and_label():
    episodes = (EpisodeRange("e1", 0, 3_600_000), EpisodeRange("e2", 3_600_000, 3_780_000))
    rows = normalize_segments(
        output(
            raw(1, 1, "game", game="Test", label="Boss fight"),
            raw(2, 2, phase="closing", label="Goodbye"),
        ),
        episodes,
    )
    assert [(r["category"], r["phase"], r["label"]) for r in rows] == [
        ("game", "main", "Boss fight"),
        ("chat", "closing", "Goodbye"),
    ]


def test_adjacent_segments_with_different_labels_stay_apart():
    episodes = (EpisodeRange("e1", 0, 1_200_000), EpisodeRange("e2", 1_200_000, 2_400_000))
    rows = normalize_segments(
        output(
            raw(1, 1, "game", game="Test", label="Island survival"),
            raw(2, 2, "game", game="Test", label="Loot check"),
        ),
        episodes,
    )
    assert [r["label"] for r in rows] == ["Island survival", "Loot check"]


def test_absorbed_segment_keeps_its_label_when_members_differ():
    episodes = (EpisodeRange("e1", 0, 1_200_000), EpisodeRange("e2", 1_200_000, 1_380_000))
    rows = normalize_segments(
        output(
            raw(1, 1, "game", game="Test", label="Ranked", collab=True, partners=["Guest"]),
            raw(2, 2, label="Wrap-up"),
        ),
        episodes,
    )
    assert [(r["category"], r["collab"], r["label"]) for r in rows] == [
        ("game", True, "Ranked"),
        ("game", False, "Wrap-up"),
    ]


def test_short_watch_becomes_chat_and_edge_phase_is_limited():
    episodes = (EpisodeRange("e1", 0, 1_800_000),)
    rows = normalize_segments(output(raw(1, 1, phase="opening")), episodes)
    assert [(r["phase"], r["startMs"], r["endMs"]) for r in rows] == [
        ("opening", 0, 900_000),
        ("main", 900_000, 1_800_000),
    ]
    short = normalize_segments(output(raw(1, 1, "watch")), (EpisodeRange("e1", 0, 900_000),))
    assert short[0]["category"] == "chat"


class Source(SegmentSourceReaderPort):
    def __init__(self, source):
        self.source = source

    async def load(self, video_id, timeline_work_item_id):
        assert (video_id, timeline_work_item_id) == (1, 10)
        return self.source


class Results(SegmentResultStorePort):
    def __init__(self):
        self.saved = []

    async def save(self, **kwargs):
        self.saved.append(kwargs)
        return 42


class Runtime(CodexRuntimePort):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        self.calls.append(command)
        return CodexRunResult(
            thread_id="test",
            turn_id="test",
            status="completed",
            final_response=next(self.responses),
        )

    async def login_with_device_code(self):
        raise AssertionError("No authentication in tests")

    async def login_api_key(self, api_key):
        raise AssertionError("No authentication in tests")

    async def account(self, *, refresh_token=False):
        raise AssertionError("No authentication in tests")

    async def logout(self):
        raise AssertionError("No authentication in tests")


@pytest.mark.parametrize("empty,invalid", [(False, False), (False, True), (True, False)])
def test_executor_repairs_bounded_output_and_skips_runtime_for_empty(
    migrated_database_path: Path,
    empty: bool,
    invalid: bool,
):
    asyncio.run(exercise_executor(migrated_database_path, empty, invalid))


async def exercise_executor(path, empty, invalid):
    engine = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(engine)
    source = SegmentSource(
        1, 10, 20, {"summary": "test"}, () if empty else (EpisodeRange("e1", 0, 1_200_000),), empty
    )
    values: dict[str, object] = {
        "videoId": 1,
        "sourceTimelineWorkItemId": 10,
        "sourceFingerprint": source.fingerprint,
        "promptBody": "sample",
        "promptBodySha256": hashlib.sha256(b"sample").hexdigest(),
        "taxonomyVersion": "v1.6",
        "policyVersion": "v1",
        "model": "gpt-6-luna",
        "reasoningEffort": "high",
    }
    try:
        from datetime import UTC, datetime

        async with SqlAlchemyWorkUnitOfWork(sessions) as uow:
            item, _ = await uow.work_items.get_or_create(
                CreateWorkItem(
                    task_type="segment_classify",
                    subject_type="test",
                    subject_id=None,
                    external_key=None,
                    task_version="v1",
                    input_hash="test",
                    idempotency_key="test",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=600,
                    input_json=values,
                    available_at=datetime.now(UTC),
                )
            )
            await uow.commit()
        good = json.dumps({"segments": [raw()]})
        runtime = Runtime(["{}"] * (3 if invalid else 1) + [good])
        results = Results()
        executor = SegmentClassificationExecutor(
            source=Source(source), results=results, runtime=runtime
        )
        context = WorkExecutionContext(work_item=item, attempt_id=1, worker_id="test")
        if invalid:
            with pytest.raises(ApplicationError) as exc:
                await executor.execute(context)
            assert exc.value.descriptor.code == "segments.invalid_output"
            assert len(runtime.calls) == 3 and not results.saved
            return
        result = await executor.execute(context)
        assert result.output_json["classificationId"] == 42
        assert len(runtime.calls) == (0 if empty else 2)
        assert len(results.saved) == 1
        assert result.output_json["segmentCount"] == (0 if empty else 1)
        stale = replace(item, input_json={**values, "sourceFingerprint": "old"})
        with pytest.raises(ApplicationError) as exc:
            await executor.execute(replace(context, work_item=stale))
        assert exc.value.descriptor.code == "segments.source_changed"
    finally:
        await engine.dispose()


def test_disabled_worker_does_not_initialize_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled worker must not claim work")

    monkeypatch.setattr("codex_sdk_cli.workers.segments.WorkRuntime", forbidden)
    assert CliSettings().segment_classify_enabled is True
    monkeypatch.setenv("CODEX_CLI_SEGMENT_CLASSIFY_ENABLED", "false")
    asyncio.run(run_worker(settings=CliSettings(), stop_after_one=True))
