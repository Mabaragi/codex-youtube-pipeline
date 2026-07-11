from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner
from openai_codex import ApprovalMode, Sandbox
from openai_codex.generated.v2_all import ReasoningEffort
from sqlalchemy import create_engine, text

from codex_sdk_cli.cli import main
from codex_sdk_cli.runner import (
    BLANK_BASE_INSTRUCTIONS,
    BLANK_DEVELOPER_INSTRUCTIONS,
    CodexLike,
    ThreadLike,
)


@dataclass(slots=True)
class FakeTurnResult:
    id: str = "turn-1"
    status: object = "completed"
    final_response: str | None = "done"
    usage: object | None = None


class FakeThread(ThreadLike):
    id = "thread-1"

    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.efforts: list[ReasoningEffort | None] = []

    async def run(
        self,
        input: str,
        *,
        effort: ReasoningEffort | None = None,
    ) -> FakeTurnResult:
        self.inputs.append(input)
        self.efforts.append(effort)
        return FakeTurnResult()


@dataclass(slots=True)
class FakeLoginCompletion:
    success: bool
    error: str | None = None


class FakeBrowserLoginHandle:
    auth_url = "https://example.test/auth"

    async def wait(self) -> FakeLoginCompletion:
        return FakeLoginCompletion(success=True)


class FakeDeviceLoginHandle:
    verification_url = "https://example.test/device"
    user_code = "ABCD-EFGH"

    async def wait(self) -> FakeLoginCompletion:
        return FakeLoginCompletion(success=True)


class FakeCodexForCli(CodexLike):
    def __init__(self) -> None:
        self.thread = FakeThread()
        self.resumed_thread_id: str | None = None
        self.thread_kwargs: dict[str, object] = {}
        self.api_key: str | None = None
        self.logged_out = False

    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        base_instructions: str | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeThread:
        self.thread_kwargs = {
            "approval_mode": approval_mode,
            "base_instructions": base_instructions,
            "cwd": cwd,
            "developer_instructions": developer_instructions,
            "ephemeral": ephemeral,
            "model": model,
            "sandbox": sandbox,
        }
        return self.thread

    async def thread_resume(
        self,
        thread_id: str,
        *,
        approval_mode: ApprovalMode | None = None,
        base_instructions: str | None = None,
        cwd: str | None = None,
        developer_instructions: str | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeThread:
        self.resumed_thread_id = thread_id
        self.thread_kwargs = {
            "approval_mode": approval_mode,
            "base_instructions": base_instructions,
            "cwd": cwd,
            "developer_instructions": developer_instructions,
            "model": model,
            "sandbox": sandbox,
        }
        return self.thread

    async def login_chatgpt(self) -> FakeBrowserLoginHandle:
        return FakeBrowserLoginHandle()

    async def login_chatgpt_device_code(self) -> FakeDeviceLoginHandle:
        return FakeDeviceLoginHandle()

    async def login_api_key(self, api_key: str) -> None:
        self.api_key = api_key

    async def account(self, *, refresh_token: bool = False) -> object:
        return AccountPayload(refresh_token=refresh_token)

    async def logout(self) -> None:
        self.logged_out = True


@dataclass(frozen=True, slots=True)
class AccountPayload:
    refresh_token: bool

    def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> object:
        return {"mode": mode, "by_alias": by_alias, "refreshToken": self.refresh_token}


@asynccontextmanager
async def fake_factory(codex: FakeCodexForCli) -> AsyncGenerator[CodexLike, None]:
    yield codex


def invoke_with_fake(codex: FakeCodexForCli, args: list[str], input: str | None = None):
    runner = CliRunner()
    return runner.invoke(
        main,
        args,
        input=input,
        obj={"codex_factory": lambda _settings: fake_factory(codex)},
        env={"CODEX_CLI_MODEL": "", "CODEX_CLI_API_KEY": ""},
    )


def test_run_command_outputs_thread_metadata_and_response() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(
        codex,
        ["run", "--sandbox", "read-only", "--approval", "deny-all", "hello"],
    )

    assert result.exit_code == 0
    assert "thread_id: thread-1" in result.output
    assert "turn_id: turn-1" in result.output
    assert "done" in result.output
    assert codex.thread.inputs == ["hello"]
    assert codex.thread_kwargs["sandbox"] is Sandbox.read_only
    assert codex.thread_kwargs["approval_mode"] is ApprovalMode.deny_all
    assert codex.thread_kwargs["ephemeral"] is True
    assert codex.thread_kwargs["base_instructions"] is None
    assert codex.thread_kwargs["developer_instructions"] is None
    assert codex.thread_kwargs["model"] == "gpt-5.5"
    assert codex.thread.efforts == [ReasoningEffort.medium]


def test_run_command_accepts_model_and_reasoning_effort_overrides() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(
        codex,
        [
            "run",
            "--model",
            "gpt-5.4-mini",
            "--reasoning-effort",
            "xhigh",
            "hello",
        ],
    )

    assert result.exit_code == 0
    assert codex.thread_kwargs["model"] == "gpt-5.4-mini"
    assert codex.thread.efforts == [ReasoningEffort.xhigh]


def test_run_command_persists_new_thread_when_requested() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["run", "--persist", "hello"])

    assert result.exit_code == 0
    assert codex.resumed_thread_id is None
    assert codex.thread_kwargs["ephemeral"] is False


def test_run_command_can_empty_base_instructions() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["run", "--empty-base-instructions", "hello"])

    assert result.exit_code == 0
    assert codex.thread_kwargs["base_instructions"] == BLANK_BASE_INSTRUCTIONS


def test_run_command_can_empty_developer_instructions() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["run", "--empty-developer-instructions", "hello"])

    assert result.exit_code == 0
    assert codex.thread_kwargs["developer_instructions"] == BLANK_DEVELOPER_INSTRUCTIONS


def test_domain_entry_add_creates_type_entry_streamer_and_alias(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_file = migrated_database_path
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    _insert_streamer(database_file)

    result = CliRunner().invoke(
        main,
        [
            "domain",
            "entry",
            "add",
            "--type",
            "사람 이름",
            "--name",
            "테스트 인물",
            "--detail",
            "테스트 인물 설명",
            "--streamer-id",
            "1",
            "--alias",
            "테인",
        ],
        env={"CODEX_CLI_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonicalName"] == "테스트 인물"
    assert payload["typeLabel"] == "사람 이름"
    assert payload["streamers"][0]["streamerId"] == 1
    assert payload["aliases"][0]["surfaceForm"] == "테인"


def test_timeline_normalize_style_cli_dry_run_and_apply(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_file = migrated_database_path
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    _insert_timeline_style_fixture(database_file)

    dry_run = CliRunner().invoke(
        main,
        ["timeline", "normalize-style", "--dry-run"],
        env={"CODEX_CLI_DATABASE_URL": database_url},
    )

    assert dry_run.exit_code == 0, dry_run.output
    dry_payload = json.loads(dry_run.output)
    assert dry_payload["apply"] is False
    assert dry_payload["changedFields"] >= 5
    assert dry_payload["changedOutputJsonStrings"] >= 5
    assert dry_payload["unresolvedCount"] == 0
    assert _fetch_timeline_style_fixture(database_file)["composition_summary"] == (
        "\uac8c\uc784\uc774 \uc774\uc5b4\uc9d1\ub2c8\ub2e4."
    )

    applied = CliRunner().invoke(
        main,
        ["timeline", "normalize-style", "--apply"],
        env={"CODEX_CLI_DATABASE_URL": database_url},
    )

    assert applied.exit_code == 0, applied.output
    apply_payload = json.loads(applied.output)
    assert apply_payload["apply"] is True
    assert apply_payload["unresolvedCount"] == 0
    values = _fetch_timeline_style_fixture(database_file)
    assert values["composition_summary"] == "\uac8c\uc784\uc774 \uc774\uc5b4\uc9c4\ub2e4."
    assert values["block_summary"] == "\ub300\ud654\ub97c \ub098\ub208\ub2e4."
    assert values["episode_summary"] == "\uc2dc\uc791\ud55c\ub2e4."
    assert values["topic_summary"] == "\uad6c\uac04\uc774\ub2e4."
    assert values["flag_reason"] == "\uc790\ub8cc\uac00 \uc788\ub2e4."
    assert values["output_summary"] == "\uac8c\uc784\uc774 \uc774\uc5b4\uc9c4\ub2e4."
    assert values["raw_response_text"] == "\uc6d0\ubb38\uc740 \uc2dc\uc791\ud569\ub2c8\ub2e4."


def test_ops_detect_stuck_cli_reports_stale_running_tasks(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_file = migrated_database_path
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    _insert_stuck_task_fixture(database_file)

    result = CliRunner().invoke(
        main,
        ["ops", "detect-stuck", "--task", "micro_event_extract", "--minutes", "15"],
        env={"CODEX_CLI_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 1
    assert payload["items"][0]["videoTaskId"] == 1
    assert payload["items"][0]["workerPid"] == 9876
    assert payload["items"][0]["latestEvent"]["eventType"] == ("micro_event_extract.window_started")


def test_run_command_resumes_thread() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["run", "--thread-id", "thread-old", "continue"])

    assert result.exit_code == 0
    assert codex.resumed_thread_id == "thread-old"


def test_run_command_can_empty_base_instructions_when_resuming() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(
        codex,
        ["run", "--thread-id", "thread-old", "--empty-base-instructions", "continue"],
    )

    assert result.exit_code == 0
    assert codex.resumed_thread_id == "thread-old"
    assert codex.thread_kwargs["base_instructions"] == BLANK_BASE_INSTRUCTIONS


def test_run_command_can_empty_developer_instructions_when_resuming() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(
        codex,
        ["run", "--thread-id", "thread-old", "--empty-developer-instructions", "continue"],
    )

    assert result.exit_code == 0
    assert codex.resumed_thread_id == "thread-old"
    assert codex.thread_kwargs["developer_instructions"] == BLANK_DEVELOPER_INSTRUCTIONS


def test_run_command_ignores_persist_when_resuming_thread() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(
        codex,
        ["run", "--thread-id", "thread-old", "--persist", "continue"],
    )

    assert result.exit_code == 0
    assert codex.resumed_thread_id == "thread-old"
    assert "ephemeral" not in codex.thread_kwargs


def test_login_browser_command() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["login", "browser"])

    assert result.exit_code == 0
    assert "Open this URL: https://example.test/auth" in result.output
    assert "Login succeeded." in result.output


def test_login_device_command() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["login", "device"])

    assert result.exit_code == 0
    assert "Open this URL: https://example.test/device" in result.output
    assert "Enter code: ABCD-EFGH" in result.output


def test_login_api_key_command_uses_hidden_prompt() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["login", "api-key"], input="OPENAI_API_KEY_TEST\n")

    assert result.exit_code == 0
    assert codex.api_key == "OPENAI_API_KEY_TEST"
    assert "Login succeeded." in result.output


def test_account_command_outputs_json() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["account", "--refresh-token"])

    assert result.exit_code == 0
    assert '"refreshToken": true' in result.output
    assert '"mode": "json"' in result.output


def test_logout_command() -> None:
    codex = FakeCodexForCli()

    result = invoke_with_fake(codex, ["logout"])

    assert result.exit_code == 0
    assert codex.logged_out is True
    assert "Logged out." in result.output


def _insert_streamer(database_file: Path) -> None:
    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO streamers (name) VALUES ('Streamer')"))
    finally:
        engine.dispose()


def _insert_timeline_style_fixture(database_file: Path) -> None:
    polite_summary = "\uac8c\uc784\uc774 \uc774\uc5b4\uc9d1\ub2c8\ub2e4."
    polite_block = "\ub300\ud654\ub97c \ub098\ub215\ub2c8\ub2e4."
    polite_episode = "\uc2dc\uc791\ud569\ub2c8\ub2e4."
    polite_topic = "\uad6c\uac04\uc785\ub2c8\ub2e4."
    polite_flag = "\uc790\ub8cc\uac00 \uc788\uc2b5\ub2c8\ub2e4."
    output_json = {
        "video_summary": {
            "title": "test",
            "summary": polite_summary,
            "display_title": "test",
            "display_summary": polite_summary,
            "main_topics": ["topic"],
        },
        "blocks": [
            {
                "block_id": "block_001",
                "block_type": "JUST_CHATTING",
                "title": "block",
                "summary": polite_block,
                "display_title": "block",
                "display_summary": polite_block,
                "episode_ids": ["episode_001"],
            }
        ],
        "episodes": [
            {
                "episode_id": "episode_001",
                "parent_block_id": "block_001",
                "start_micro_event_id": "me_0001",
                "end_micro_event_id": "me_0002",
                "program_mode": "JUST_CHATTING",
                "primary_content_kind": "META_CHAT",
                "title": "episode",
                "summary": polite_episode,
                "display_title": "episode",
                "display_summary": polite_episode,
                "topics": ["topic"],
                "viewer_tags": ["META"],
                "highlight_micro_event_ids": ["me_0001"],
                "visibility": "DEFAULT",
            }
        ],
        "topic_clusters": [
            {
                "topic_id": "topic_001",
                "label": polite_topic,
                "summary": polite_topic,
                "display_label": polite_topic,
                "episode_ids": ["episode_001"],
            }
        ],
        "review_flags": [
            {
                "start_micro_event_id": "me_0001",
                "end_micro_event_id": "me_0002",
                "type": "BOUNDARY_AMBIGUOUS",
                "reason": polite_flag,
            }
        ],
    }
    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO streamers (id, name) VALUES (1, 'Streamer')"))
            connection.execute(
                text(
                    "INSERT INTO channels "
                    "(id, streamer_id, handle, name, youtube_channel_id) "
                    "VALUES (1, 1, 'handle', 'Channel', 'channel-1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO videos "
                    "(id, channel_id, youtube_video_id, title, description, published_at) "
                    "VALUES (1, 1, 'youtube-1', 'Video', '', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO work_items "
                    "(id, task_type, subject_type, subject_id, task_version, input_hash, "
                    "idempotency_key, execution_mode, status, priority, timeout_seconds, "
                    "input_json, output_json) VALUES "
                    "(1, 'micro_event_extract', 'video', 1, 'v1', 'hash-micro', "
                    "'fixture:micro', 'worker', 'succeeded', 0, 1200, '{}', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO work_items "
                    "(id, task_type, subject_type, subject_id, task_version, input_hash, "
                    "idempotency_key, execution_mode, status, priority, timeout_seconds, "
                    "input_json, output_json) VALUES "
                    "(2, 'timeline_compose', 'video', 1, 'v1', 'hash-timeline', "
                    "'fixture:timeline', 'worker', 'succeeded', 0, 1200, '{}', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO timeline_compositions "
                    "(id, video_task_id, video_id, source_micro_event_task_id, "
                    "source_micro_event_fingerprint, copy_style, model, reasoning_effort, "
                    "title, summary, display_title, display_summary, main_topics, "
                    "output_json, validation_warnings, raw_response_text) "
                    "VALUES (1, 2, 1, 1, :fingerprint, 'neutral', 'gpt-5.5', "
                    "'high', 'title', :summary, 'title', :summary, :topics, "
                    ":output_json, '[]', :raw_response_text)"
                ),
                {
                    "fingerprint": "f" * 64,
                    "summary": polite_summary,
                    "topics": json.dumps(["topic"]),
                    "output_json": json.dumps(output_json, ensure_ascii=False),
                    "raw_response_text": "\uc6d0\ubb38\uc740 \uc2dc\uc791\ud569\ub2c8\ub2e4.",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO timeline_blocks "
                    "(composition_id, block_id, block_index, block_type, title, summary, "
                    "display_title, display_summary, episode_ids) "
                    "VALUES (1, 'block_001', 1, 'JUST_CHATTING', 'block', :summary, "
                    "'block', :summary, :episode_ids)"
                ),
                {
                    "summary": polite_block,
                    "episode_ids": json.dumps(["episode_001"]),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO timeline_episodes "
                    "(composition_id, episode_id, episode_index, parent_block_id, "
                    "program_mode, primary_content_kind, title, summary, display_title, "
                    "display_summary, topics, viewer_tags, highlight_micro_event_candidate_ids, "
                    "visibility) "
                    "VALUES (1, 'episode_001', 1, 'block_001', 'JUST_CHATTING', "
                    "'META_CHAT', 'episode', :summary, 'episode', :summary, "
                    ":topics, :viewer_tags, :highlights, 'DEFAULT')"
                ),
                {
                    "summary": polite_episode,
                    "topics": json.dumps(["topic"]),
                    "viewer_tags": json.dumps(["META"]),
                    "highlights": json.dumps([1]),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO timeline_topic_clusters "
                    "(composition_id, topic_id, topic_index, label, summary, "
                    "display_label, episode_ids) "
                    "VALUES (1, 'topic_001', 1, :label, :summary, :label, :episode_ids)"
                ),
                {
                    "label": polite_topic,
                    "summary": polite_topic,
                    "episode_ids": json.dumps(["episode_001"]),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO timeline_review_flags "
                    "(composition_id, flag_index, type, reason) "
                    "VALUES (1, 1, 'BOUNDARY_AMBIGUOUS', :reason)"
                ),
                {"reason": polite_flag},
            )
    finally:
        engine.dispose()


def _insert_stuck_task_fixture(database_file: Path) -> None:
    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO streamers (id, name) VALUES (1, 'Streamer')"))
            connection.execute(
                text(
                    "INSERT INTO channels "
                    "(id, streamer_id, handle, name, youtube_channel_id) "
                    "VALUES (1, 1, 'handle', 'Channel', 'channel-1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO videos "
                    "(id, channel_id, youtube_video_id, title, description, published_at) "
                    "VALUES (1, 1, 'youtube-1', 'Video', '', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO work_items "
                    "(id, task_type, subject_type, subject_id, external_key, task_version, "
                    "input_hash, idempotency_key, execution_mode, status, priority, "
                    "timeout_seconds, input_json, lease_owner, started_at, updated_at) "
                    "VALUES (1, 'micro_event_extract', 'video', 1, 'youtube-1', 'v2', "
                    "'hash', 'fixture:stuck', 'worker', 'running', 0, 600, '{}', "
                    "'micro-event-worker:host:9876', '2026-01-01 00:00:00', "
                    "'2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO work_attempts "
                    "(id, work_item_id, attempt_no, status, worker_id) "
                    "VALUES (1, 1, 1, 'running', 'micro-event-worker:host:9876')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO operation_events "
                    "(id, occurred_at, event_type, severity, message, actor_type, "
                    "source, metadata_json, video_task_id, video_id) "
                    "VALUES (1, '2026-01-01 00:00:00', "
                    "'micro_event_extract.window_started', 'info', 'Started.', "
                    "'system', 'test', '{}', 1, 1)"
                )
            )
    finally:
        engine.dispose()


def _fetch_timeline_style_fixture(database_file: Path) -> dict[str, str]:
    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    try:
        with engine.begin() as connection:
            output_json = json.loads(
                connection.execute(
                    text("SELECT output_json FROM timeline_compositions WHERE id = 1")
                ).scalar_one()
            )
            return {
                "composition_summary": connection.execute(
                    text("SELECT summary FROM timeline_compositions WHERE id = 1")
                ).scalar_one(),
                "block_summary": connection.execute(
                    text("SELECT summary FROM timeline_blocks WHERE composition_id = 1")
                ).scalar_one(),
                "episode_summary": connection.execute(
                    text("SELECT summary FROM timeline_episodes WHERE composition_id = 1")
                ).scalar_one(),
                "topic_summary": connection.execute(
                    text("SELECT summary FROM timeline_topic_clusters WHERE composition_id = 1")
                ).scalar_one(),
                "flag_reason": connection.execute(
                    text("SELECT reason FROM timeline_review_flags WHERE composition_id = 1")
                ).scalar_one(),
                "output_summary": output_json["video_summary"]["summary"],
                "raw_response_text": connection.execute(
                    text("SELECT raw_response_text FROM timeline_compositions WHERE id = 1")
                ).scalar_one(),
            }
    finally:
        engine.dispose()
