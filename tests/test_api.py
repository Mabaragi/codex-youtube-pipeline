from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_codex_runtime, get_settings
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.codex.exceptions import CodexRuntimeError
from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
    CodexRuntimePort,
    CodexRunUsageContext,
)
from codex_sdk_cli.settings import CliSettings


class FakeCodexRuntime(CodexRuntimePort):
    def __init__(self) -> None:
        self.run_command: CodexRunCommand | None = None
        self.api_key: str | None = None
        self.refresh_token: bool | None = None
        self.logged_out = False
        self.fail_run = False
        self.device_login = CodexLoginResult(success=True)

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        if self.fail_run:
            raise CodexRuntimeError("runtime unavailable")
        self.run_command = command
        return CodexRunResult(
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            final_response="done",
            usage={"totalTokens": 3},
        )

    async def login_with_device_code(self) -> CodexLoginResult:
        return self.device_login

    async def login_api_key(self, api_key: str) -> None:
        self.api_key = api_key

    async def account(self, *, refresh_token: bool = False) -> object:
        self.refresh_token = refresh_token
        return {"account": {"email": "dev@example.test"}, "refreshToken": refresh_token}

    async def logout(self) -> None:
        self.logged_out = True


def test_health_endpoint() -> None:
    response = asyncio.run(_request("GET", "/health"))

    assert response == {"status": "ok"}


def test_s3_health_endpoint_returns_mount_diagnostics() -> None:
    response = asyncio.run(_request("GET", "/health/s3"))

    assert response["path"] == "/data/s3"
    assert isinstance(response["exists"], bool)
    assert isinstance(response["readable"], bool)
    assert isinstance(response["isMount"], bool)
    assert isinstance(response["s3Mounted"], bool)
    assert isinstance(response["reason"], str)


def test_run_endpoint_uses_defaults_and_returns_camel_case_response() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={"prompt": "  hello  "},
        )
    )

    assert response == {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "status": "completed",
        "finalResponse": "done",
        "model": "gpt-5.4",
        "reasoningEffort": "high",
        "usage": {"totalTokens": 3},
    }
    assert fake.run_command == CodexRunCommand(
        prompt="hello",
        thread_id=None,
        cwd=None,
        model="gpt-5.4",
        reasoning_effort="high",
        sandbox="read-only",
        approval="deny-all",
        persist=False,
        base_instructions=" ",
        developer_instructions=" ",
        usage_context=CodexRunUsageContext(source="codex_runs", operation="run_prompt"),
    )


def test_run_endpoint_normalizes_blank_instructions_to_single_spaces() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={
                "prompt": "hello",
                "baseInstructions": "",
                "developerInstructions": "   ",
            },
        )
    )

    assert response["status"] == "completed"
    assert fake.run_command is not None
    assert fake.run_command.base_instructions == " "
    assert fake.run_command.developer_instructions == " "


def test_run_endpoint_accepts_model_and_reasoning_effort_overrides() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={
                "prompt": "hello",
                "model": "gpt-5.4-mini",
                "reasoningEffort": "low",
            },
        )
    )

    assert response["model"] == "gpt-5.4-mini"
    assert response["reasoningEffort"] == "low"
    assert fake.run_command is not None
    assert fake.run_command.model == "gpt-5.4-mini"
    assert fake.run_command.reasoning_effort == "low"


def test_run_endpoint_passes_custom_instructions() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={
                "prompt": "hello",
                "baseInstructions": "  base rules  ",
                "developerInstructions": "  dev rules  ",
            },
        )
    )

    assert response["status"] == "completed"
    assert fake.run_command is not None
    assert fake.run_command.base_instructions == "base rules"
    assert fake.run_command.developer_instructions == "dev rules"


@pytest.mark.parametrize("removed_field", ["cwd", "threadId", "persist"])
def test_run_endpoint_rejects_removed_advanced_parameters(removed_field: str) -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={"prompt": "hello", removed_field: "ignored"},
            expected_status=422,
        )
    )

    assert fake.run_command is None
    assert response["detail"][0]["type"] == "extra_forbidden"
    assert response["detail"][0]["loc"] == ["body", removed_field]


def test_run_endpoint_maps_domain_errors() -> None:
    fake = FakeCodexRuntime()
    fake.fail_run = True

    response = asyncio.run(
        _request(
            "POST",
            "/codex/runs",
            runtime=fake,
            json={"prompt": "hello"},
            expected_status=502,
        )
    )

    assert response == {"detail": "runtime unavailable"}


def test_account_endpoint_returns_runtime_payload() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request("GET", "/codex/account?refreshToken=true", runtime=fake)
    )

    assert response == {"account": {"email": "dev@example.test"}, "refreshToken": True}
    assert fake.refresh_token is True


def test_login_device_code_endpoint() -> None:
    fake = FakeCodexRuntime()

    response = asyncio.run(
        _request(
            "POST",
            "/codex/login/device-code",
            runtime=fake,
        )
    )

    assert response == {"success": True, "error": None}


def test_login_device_code_endpoint_returns_login_failure() -> None:
    fake = FakeCodexRuntime()
    fake.device_login = CodexLoginResult(success=False, error="expired code")

    response = asyncio.run(
        _request(
            "POST",
            "/codex/login/device-code",
            runtime=fake,
        )
    )

    assert response == {"success": False, "error": "expired code"}


def test_login_api_key_and_logout_endpoints() -> None:
    fake = FakeCodexRuntime()

    login_response = asyncio.run(
        _request(
            "POST",
            "/codex/login/api-key",
            runtime=fake,
            json={"apiKey": "OPENAI_API_KEY_TEST"},
        )
    )
    logout_response = asyncio.run(_request("POST", "/codex/logout", runtime=fake))

    assert login_response == {"success": True, "error": None}
    assert fake.api_key == "OPENAI_API_KEY_TEST"
    assert logout_response == {"success": True}
    assert fake.logged_out is True


async def _request(
    method: str,
    path: str,
    *,
    runtime: FakeCodexRuntime | None = None,
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    fake = runtime or FakeCodexRuntime()
    app.dependency_overrides[get_codex_runtime] = lambda: fake
    app.dependency_overrides[get_settings] = lambda: CliSettings(
        model="gpt-5.4",
        reasoning_effort="high",
        sandbox="read-only",
        approval="deny-all",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path, json=json)

    assert response.status_code == expected_status, response.text
    return response.json()
