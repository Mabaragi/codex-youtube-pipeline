from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from click.testing import CliRunner
from openai_codex import ApprovalMode, Sandbox
from openai_codex.generated.v2_all import ReasoningEffort

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

    result = invoke_with_fake(codex, ["login", "api-key"], input="sk-test\n")

    assert result.exit_code == 0
    assert codex.api_key == "sk-test"
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
