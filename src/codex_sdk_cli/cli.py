from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import TypeVar

import click
from pydantic import ValidationError

from .runner import (
    CodexCliError,
    CodexLike,
    LoginOutput,
    RunOutput,
    RunRequest,
    account_json,
    login_with_api_key,
    login_with_browser,
    login_with_device_code,
    logout_codex,
    open_codex,
    parse_approval,
    parse_sandbox,
    run_prompt,
)
from .settings import ApprovalChoice, CliSettings, SandboxChoice

CodexFactory = Callable[[CliSettings], AbstractAsyncContextManager[CodexLike]]
T = TypeVar("T")


def default_codex_factory(settings: CliSettings) -> AbstractAsyncContextManager[CodexLike]:
    return open_codex(settings.codex_config())


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    """Run Codex SDK workflows from a small Python CLI."""
    ctx.ensure_object(dict)


@main.command()
@click.option("--thread-id", help="Existing Codex thread id to resume.")
@click.option(
    "--cwd",
    type=click.Path(file_okay=False, path_type=Path),
    help="Workspace directory for the Codex thread.",
)
@click.option("--model", help="Model override for this thread.")
@click.option(
    "--sandbox",
    type=click.Choice(["read-only", "workspace-write", "full-access"]),
    help="Filesystem sandbox mode.",
)
@click.option(
    "--approval",
    type=click.Choice(["auto-review", "deny-all"]),
    help="Approval behavior for escalated requests.",
)
@click.option(
    "--persist",
    is_flag=True,
    help="Persist a newly created thread to local Codex state.",
)
@click.option(
    "--empty-base-instructions",
    is_flag=True,
    help="Send empty base_instructions to Codex instead of SDK defaults.",
)
@click.option(
    "--empty-developer-instructions",
    is_flag=True,
    help="Send empty developer_instructions to Codex instead of SDK defaults.",
)
@click.argument("prompt")
@click.pass_context
def run(
    ctx: click.Context,
    thread_id: str | None,
    cwd: Path | None,
    model: str | None,
    sandbox: SandboxChoice | None,
    approval: ApprovalChoice | None,
    persist: bool,
    empty_base_instructions: bool,
    empty_developer_instructions: bool,
    prompt: str,
) -> None:
    """Start or resume a Codex thread and run PROMPT."""
    output = _handle_errors(
        lambda: asyncio.run(
            _run_async(
                ctx,
                thread_id,
                cwd,
                model,
                sandbox,
                approval,
                persist,
                empty_base_instructions,
                empty_developer_instructions,
                prompt,
            )
        )
    )

    click.echo(f"thread_id: {output.thread_id}")
    click.echo(f"turn_id: {output.turn_id}")
    click.echo(f"status: {output.status}")
    click.echo()
    click.echo(output.final_response)


async def _run_async(
    ctx: click.Context,
    thread_id: str | None,
    cwd: Path | None,
    model: str | None,
    sandbox: SandboxChoice | None,
    approval: ApprovalChoice | None,
    persist: bool,
    empty_base_instructions: bool,
    empty_developer_instructions: bool,
    prompt: str,
) -> RunOutput:
    settings = _settings()
    request = RunRequest(
        prompt=prompt,
        thread_id=thread_id,
        cwd=cwd,
        model=model or settings.model,
        sandbox=parse_sandbox(sandbox or settings.sandbox),
        approval_mode=parse_approval(approval or settings.approval),
        persist=persist,
        empty_base_instructions=empty_base_instructions,
        empty_developer_instructions=empty_developer_instructions,
    )

    async with _codex(ctx, settings) as codex:
        return await run_prompt(codex, request)


@main.group()
def login() -> None:
    """Authenticate the local Codex runtime."""


@login.command("browser")
@click.pass_context
def login_browser(ctx: click.Context) -> None:
    """Start browser-based ChatGPT login."""
    output = _handle_errors(
        lambda: asyncio.run(
            _login_browser_async(
                ctx,
                announce_url=lambda url: click.echo(f"Open this URL: {url}"),
            )
        )
    )

    _echo_login_result(output.success, output.error)


async def _login_browser_async(
    ctx: click.Context,
    *,
    announce_url: Callable[[str], None],
) -> LoginOutput:
    settings = _settings()
    async with _codex(ctx, settings) as codex:
        return await login_with_browser(
            codex,
            announce_url=announce_url,
        )


@login.command("device")
@click.pass_context
def login_device(ctx: click.Context) -> None:
    """Start device-code ChatGPT login."""
    output = _handle_errors(
        lambda: asyncio.run(
            _login_device_async(
                ctx,
                announce_code=lambda url, code: click.echo(
                    f"Open this URL: {url}\nEnter code: {code}"
                ),
            )
        )
    )

    _echo_login_result(output.success, output.error)


async def _login_device_async(
    ctx: click.Context,
    *,
    announce_code: Callable[[str, str], None],
) -> LoginOutput:
    settings = _settings()
    async with _codex(ctx, settings) as codex:
        return await login_with_device_code(
            codex,
            announce_code=announce_code,
        )


@login.command("api-key")
@click.option("--api-key", help="OpenAI API key. If omitted, env and hidden prompt are used.")
@click.pass_context
def login_api_key(ctx: click.Context, api_key: str | None) -> None:
    """Authenticate with an OpenAI API key."""
    settings = _settings()
    resolved_key = api_key or settings.api_key_value()
    if resolved_key is None:
        resolved_key = click.prompt("API key", hide_input=True)

    output = _handle_errors(lambda: asyncio.run(_login_api_key_async(ctx, settings, resolved_key)))

    _echo_login_result(output.success, output.error)


async def _login_api_key_async(
    ctx: click.Context,
    settings: CliSettings,
    api_key: str,
) -> LoginOutput:
    async with _codex(ctx, settings) as codex:
        return await login_with_api_key(codex, api_key)


@main.command()
@click.option("--refresh-token", is_flag=True, help="Ask Codex to refresh account token state.")
@click.pass_context
def account(ctx: click.Context, refresh_token: bool) -> None:
    """Print current Codex account state as JSON."""
    payload = _handle_errors(lambda: asyncio.run(_account_async(ctx, refresh_token)))

    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _account_async(ctx: click.Context, refresh_token: bool) -> object:
    settings = _settings()
    async with _codex(ctx, settings) as codex:
        return await account_json(codex, refresh_token=refresh_token)


@main.command()
@click.pass_context
def logout(ctx: click.Context) -> None:
    """Clear the current Codex account session."""
    _handle_errors(lambda: asyncio.run(_logout_async(ctx)))

    click.echo("Logged out.")


async def _logout_async(ctx: click.Context) -> None:
    settings = _settings()
    async with _codex(ctx, settings) as codex:
        await logout_codex(codex)


def _settings() -> CliSettings:
    try:
        return CliSettings()
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc


def _codex(ctx: click.Context, settings: CliSettings) -> AbstractAsyncContextManager[CodexLike]:
    factory = ctx.obj.get("codex_factory") if isinstance(ctx.obj, dict) else None
    if factory is None:
        return default_codex_factory(settings)
    return factory(settings)


def _handle_errors(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except CodexCliError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def _echo_login_result(success: bool, error: str | None) -> None:
    if success:
        click.echo("Login succeeded.")
        return

    message = "Login failed."
    if error:
        message = f"{message} {error}"
    raise click.ClickException(message)
