from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from openai_codex import ApprovalMode, Sandbox

from codex_sdk_cli.runner import (
    ChatgptLoginHandleLike,
    CodexLike,
    DeviceCodeLoginHandleLike,
    RunRequest,
    ThreadLike,
    login_with_api_key,
    login_with_browser,
    login_with_device_code,
    parse_approval,
    parse_sandbox,
    run_prompt,
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

    async def run(self, input: str) -> FakeTurnResult:
        self.inputs.append(input)
        return FakeTurnResult()


@dataclass(slots=True)
class FakeLoginCompletion:
    success: bool
    error: str | None = None


class FakeBrowserLoginHandle(ChatgptLoginHandleLike):
    auth_url = "https://example.test/auth"

    async def wait(self) -> FakeLoginCompletion:
        return FakeLoginCompletion(success=True)


class FakeDeviceLoginHandle(DeviceCodeLoginHandleLike):
    verification_url = "https://example.test/device"
    user_code = "ABCD-EFGH"

    async def wait(self) -> FakeLoginCompletion:
        return FakeLoginCompletion(success=True)


class FakeCodex(CodexLike):
    def __init__(self) -> None:
        self.started = False
        self.resumed_thread_id: str | None = None
        self.thread = FakeThread()
        self.thread_kwargs: dict[str, object] = {}
        self.api_key: str | None = None

    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode = ApprovalMode.auto_review,
        cwd: str | None = None,
        ephemeral: bool | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeThread:
        self.started = True
        self.thread_kwargs = {
            "approval_mode": approval_mode,
            "cwd": cwd,
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
        cwd: str | None = None,
        model: str | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeThread:
        self.resumed_thread_id = thread_id
        self.thread_kwargs = {
            "approval_mode": approval_mode,
            "cwd": cwd,
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
        return {"refresh_token": refresh_token}

    async def logout(self) -> None:
        return None


def test_parse_sandbox_maps_cli_values_to_sdk_enum() -> None:
    assert parse_sandbox("read-only") is Sandbox.read_only
    assert parse_sandbox("workspace-write") is Sandbox.workspace_write
    assert parse_sandbox("full-access") is Sandbox.full_access


def test_parse_approval_maps_cli_values_to_sdk_enum() -> None:
    assert parse_approval("auto-review") is ApprovalMode.auto_review
    assert parse_approval("deny-all") is ApprovalMode.deny_all


def test_run_prompt_starts_new_thread() -> None:
    codex = FakeCodex()
    request = RunRequest(
        prompt="hello",
        thread_id=None,
        cwd=Path("C:/repo"),
        model="gpt-test",
        sandbox=Sandbox.read_only,
        approval_mode=ApprovalMode.deny_all,
        persist=False,
    )

    output = asyncio.run(run_prompt(codex, request))

    assert codex.started is True
    assert codex.resumed_thread_id is None
    assert codex.thread.inputs == ["hello"]
    assert codex.thread_kwargs == {
        "approval_mode": ApprovalMode.deny_all,
        "cwd": "C:\\repo",
        "ephemeral": True,
        "model": "gpt-test",
        "sandbox": Sandbox.read_only,
    }
    assert output.thread_id == "thread-1"
    assert output.turn_id == "turn-1"
    assert output.final_response == "done"


def test_run_prompt_can_persist_new_thread() -> None:
    codex = FakeCodex()
    request = RunRequest(
        prompt="hello",
        thread_id=None,
        cwd=None,
        model=None,
        sandbox=Sandbox.workspace_write,
        approval_mode=ApprovalMode.auto_review,
        persist=True,
    )

    asyncio.run(run_prompt(codex, request))

    assert codex.started is True
    assert codex.thread_kwargs["ephemeral"] is False


def test_run_prompt_resumes_existing_thread() -> None:
    codex = FakeCodex()
    request = RunRequest(
        prompt="continue",
        thread_id="thread-old",
        cwd=None,
        model=None,
        sandbox=Sandbox.workspace_write,
        approval_mode=ApprovalMode.auto_review,
        persist=True,
    )

    output = asyncio.run(run_prompt(codex, request))

    assert codex.started is False
    assert codex.resumed_thread_id == "thread-old"
    assert codex.thread.inputs == ["continue"]
    assert "ephemeral" not in codex.thread_kwargs
    assert output.thread_id == "thread-1"


def test_login_helpers_return_completion() -> None:
    codex = FakeCodex()
    urls: list[str] = []
    codes: list[tuple[str, str]] = []

    browser = asyncio.run(login_with_browser(codex, announce_url=urls.append))
    device = asyncio.run(
        login_with_device_code(
            codex,
            announce_code=lambda url, code: codes.append((url, code)),
        )
    )

    assert browser.success is True
    assert device.success is True
    assert urls == ["https://example.test/auth"]
    assert codes == [("https://example.test/device", "ABCD-EFGH")]


def test_login_with_api_key_rejects_blank_key() -> None:
    codex = FakeCodex()

    try:
        asyncio.run(login_with_api_key(codex, " "))
    except Exception as exc:
        assert "API key cannot be empty" in str(exc)
    else:
        raise AssertionError("blank API key should fail")
