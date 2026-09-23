from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, NoReturn

import click
import httpx

from codex_sdk_cli.application.one_shot.ports import RunOptions
from codex_sdk_cli.application.one_shot.service import OneShotError, OneShotTimelineService
from codex_sdk_cli.domains.asr.exceptions import AudioToolNotConfigured
from codex_sdk_cli.domains.codex.choices import (
    CODEX_MODEL_CHOICES,
    CODEX_REASONING_EFFORT_CHOICES,
    DEFAULT_MICRO_EVENT_MODEL,
    DEFAULT_MICRO_EVENT_REASONING_EFFORT,
    DEFAULT_TIMELINE_MODEL,
    DEFAULT_TIMELINE_REASONING_EFFORT,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptUpstreamError
from codex_sdk_cli.infra.local_generation.asr import LocalAsrRunner
from codex_sdk_cli.infra.local_generation.generation import LocalGenerationRunner
from codex_sdk_cli.infra.local_generation.prompts import ReadOnlyActivePrompts
from codex_sdk_cli.infra.local_generation.store import LocalRunStore
from codex_sdk_cli.infra.local_generation.youtube import (
    YouTubeCaptionLookup,
    YouTubeSingleVideoLookup,
)
from codex_sdk_cli.settings import CliSettings


class JsonOnceGroup(click.Group):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as exc:
            _usage_error(exc, operation="timeline.once")

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except click.UsageError as exc:
            _usage_error(exc, operation=f"timeline.once.{ctx.invoked_subcommand or 'unknown'}")


def _usage_error(exc: click.UsageError, *, operation: str) -> NoReturn:
    click.echo(
        json.dumps(
            {
                "schemaVersion": "1",
                "ok": False,
                "operation": operation,
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": exc.format_message(),
                    "stateChanged": False,
                },
            },
            ensure_ascii=False,
        ),
        err=True,
    )
    raise click.exceptions.Exit(2)


@click.group("once", cls=JsonOnceGroup)
@click.option("--env-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "output_mode", type=click.Choice(["json", "human"]), default="json")
@click.pass_context
def once(ctx: click.Context, env_file: Path | None, output_mode: str) -> None:
    """Generate one local-only timeline from a YouTube video ID."""
    ctx.ensure_object(dict)
    ctx.obj["once_env_file"] = env_file
    ctx.obj["once_output_mode"] = output_mode


@once.command("plan")
@click.option("--video-id", required=True)
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".home-deploy/one-shot"),
    show_default=True,
)
@click.option("--transcript-mode", type=click.Choice(["auto", "youtube", "asr"]), default="auto")
@click.option("--language", "languages", multiple=True, default=("ko", "en"))
@click.option("--streamer-name")
@click.option("--window-minutes", type=click.IntRange(1, 240), default=30)
@click.option("--overlap-minutes", type=click.IntRange(0, 239), default=5)
@click.option(
    "--micro-model", type=click.Choice(CODEX_MODEL_CHOICES), default=DEFAULT_MICRO_EVENT_MODEL
)
@click.option(
    "--micro-reasoning-effort",
    type=click.Choice(CODEX_REASONING_EFFORT_CHOICES),
    default=DEFAULT_MICRO_EVENT_REASONING_EFFORT,
)
@click.option(
    "--timeline-model", type=click.Choice(CODEX_MODEL_CHOICES), default=DEFAULT_TIMELINE_MODEL
)
@click.option(
    "--timeline-reasoning-effort",
    type=click.Choice(CODEX_REASONING_EFFORT_CHOICES),
    default=DEFAULT_TIMELINE_REASONING_EFFORT,
)
@click.option("--micro-window-concurrency", type=click.IntRange(1, 12), default=1)
@click.option("--asr-model", default="turbo")
@click.option("--asr-language", default="ko")
@click.option("--asr-device", type=click.Choice(["cuda", "cpu"]), default="cuda")
@click.option("--asr-compute-type", default="auto")
@click.option("--asr-chunk-minutes", type=click.IntRange(1, 60), default=15)
@click.option("--asr-overlap-seconds", type=click.IntRange(0, 30), default=3)
@click.option("--asr-beam-size", type=click.IntRange(1, 20), default=5)
@click.option("--asr-vad-filter/--no-asr-vad-filter", default=True)
@click.pass_context
def once_plan(ctx: click.Context, **kwargs: Any) -> None:
    """Fetch metadata, captions, and current active prompts; pin a local plan."""
    video_id = kwargs.pop("video_id")
    output_root = kwargs.pop("output_root")
    kwargs["languages"] = tuple(kwargs["languages"])
    options = RunOptions(**kwargs)
    _execute(
        ctx,
        "timeline.once.plan",
        lambda service: service.plan(video_id=video_id, output_root=output_root, options=options),
    )


@once.command("run")
@click.option(
    "--plan",
    "plan_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--confirm-plan-hash", required=True)
@click.pass_context
def once_run(ctx: click.Context, plan_path: Path, confirm_plan_hash: str) -> None:
    """Generate a timeline from a pinned plan."""
    _execute(
        ctx,
        "timeline.once.run",
        lambda service: service.run(plan_path=plan_path, confirm_plan_hash=confirm_plan_hash),
    )


@once.command("resume")
@click.option(
    "--run-dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.pass_context
def once_resume(ctx: click.Context, run_dir: Path) -> None:
    """Resume failed or interrupted ASR, micro, or timeline work."""
    _execute(ctx, "timeline.once.resume", lambda service: service.resume(run_dir=run_dir))


@once.command("status")
@click.option(
    "--run-dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.pass_context
def once_status(ctx: click.Context, run_dir: Path) -> None:
    """Read local stage and checkpoint status."""
    _execute(ctx, "timeline.once.status", lambda service: service.status(run_dir=run_dir))


@once.command("verify")
@click.option(
    "--run-dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.pass_context
def once_verify(ctx: click.Context, run_dir: Path) -> None:
    """Verify the completed local timeline file."""
    _execute(ctx, "timeline.once.verify", lambda service: service.verify(run_dir=run_dir))


@once.command("version")
@click.pass_context
def once_version(ctx: click.Context) -> None:
    _show(ctx, "timeline.once.version", {"cliVersion": "1", "schemaVersion": "1"})


@once.command("capabilities")
@click.pass_context
def once_capabilities(ctx: click.Context) -> None:
    _show(
        ctx,
        "timeline.once.capabilities",
        {
            "commands": list(once.commands),
            "persistence": "local-files",
            "publication": False,
            "asrFallback": True,
        },
    )


@once.command("schema")
@click.argument("command", type=click.Choice(["plan", "run", "resume", "status", "verify"]))
@click.pass_context
def once_schema(ctx: click.Context, command: str) -> None:
    """Show the registered Click parameters for one command."""
    item = once.commands[command]
    _show(
        ctx,
        "timeline.once.schema",
        {
            "command": command,
            "parameters": [
                {"name": parameter.name, "required": parameter.required}
                for parameter in item.params
            ],
        },
    )


def _service(ctx: click.Context) -> OneShotTimelineService:
    injected = ctx.obj.get("once_service") if isinstance(ctx.obj, dict) else None
    if injected is not None:
        return injected
    env_file = ctx.obj.get("once_env_file") if isinstance(ctx.obj, dict) else None
    settings = CliSettings(_env_file=env_file)
    return OneShotTimelineService(
        videos=YouTubeSingleVideoLookup(settings),
        captions=YouTubeCaptionLookup(settings),
        prompts=ReadOnlyActivePrompts(settings),
        asr=LocalAsrRunner(settings),
        generation=LocalGenerationRunner(settings),
        store=LocalRunStore(),
    )


def _execute(ctx: click.Context, operation: str, action: Any) -> None:
    try:
        result = action(_service(ctx))
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
    except Exception as exc:
        _fail(operation, exc)
    _show(ctx, operation, result)


def _show(ctx: click.Context, operation: str, result: object) -> None:
    payload = {"schemaVersion": "1", "ok": True, "operation": operation, "result": result}
    if ctx.obj.get("once_output_mode") == "human":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(json.dumps(payload, ensure_ascii=False))


def _fail(operation: str, exc: Exception) -> NoReturn:
    if isinstance(exc, OneShotError):
        code, message, exit_code = exc.code, str(exc), exc.exit_code
    elif isinstance(exc, (FileNotFoundError, LookupError)):
        code, message, exit_code = "NOT_FOUND", str(exc), 3
    elif isinstance(exc, (AudioToolNotConfigured, YouTubeTranscriptUpstreamError, httpx.HTTPError)):
        code, message, exit_code = (
            "DEPENDENCY_UNAVAILABLE",
            "A required upstream service or tool is unavailable.",
            6,
        )
    elif isinstance(exc, ValueError):
        code, message, exit_code = "INVALID_STATE", str(exc), 4
    else:
        code, message, exit_code = (
            "INTERNAL_ERROR",
            "One-shot command failed; inspect private run files.",
            70,
        )
    payload = {
        "schemaVersion": "1",
        "ok": False,
        "operation": operation,
        "error": {
            "code": code,
            "message": message,
            "stateChanged": operation in {"timeline.once.run", "timeline.once.resume"},
        },
    }
    click.echo(json.dumps(payload, ensure_ascii=False), err=True)
    raise click.exceptions.Exit(exit_code)
