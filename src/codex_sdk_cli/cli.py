from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import TypeVar, cast

import click
from pydantic import ValidationError

from .domains.asr.use_cases import (
    FasterWhisperTranscribeRequest,
    FasterWhisperTranscribeResult,
    TranscribeYouTubeAudioUseCase,
)
from .domains.domain_knowledge.ports import (
    DomainKnowledgeRepositoryPort,
    PromptPolicy,
)
from .domains.domain_knowledge.schemas import (
    DomainEntryAliasCreateRequest,
    DomainEntryCreateRequest,
)
from .domains.domain_knowledge.use_cases import (
    CreateDomainEntryUseCase,
    ListDomainEntriesUseCase,
    ListDomainEntryTypesUseCase,
)
from .domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from .domains.ops.use_cases import DetectOpsStuckTasksUseCase
from .domains.video_tasks.constants import TIMELINE_COMPOSE_TASK_NAME
from .evaluation_cli import evaluation as evaluation_command
from .infra.asr.faster_whisper import FasterWhisperTranscriber
from .infra.asr.local_audio import FfmpegAudioChunker, YtDlpAudioDownloader
from .infra.database.session import create_database_engine, create_session_factory
from .infra.domain_knowledge.repository import SqlAlchemyDomainKnowledgeRepository
from .infra.ops.repository import SqlAlchemyOpsRepository
from .infra.timelines.style_backfill import normalize_timeline_style_backfill
from .infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from .infra.youtube_transcripts.repository import SqlAlchemyYouTubeTranscriptRepository
from .infra.youtube_transcripts.storage import MinioTranscriptStorage
from .publication_cli import publication as publication_command
from .runner import (
    BLANK_BASE_INSTRUCTIONS,
    BLANK_DEVELOPER_INSTRUCTIONS,
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
    parse_reasoning_effort,
    parse_sandbox,
    run_prompt,
)
from .settings import ApprovalChoice, CliSettings, ReasoningEffortChoice, SandboxChoice

CodexFactory = Callable[[CliSettings], AbstractAsyncContextManager[CodexLike]]
AsrTranscribeRunner = Callable[
    [FasterWhisperTranscribeRequest],
    Awaitable[FasterWhisperTranscribeResult],
]
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
    "--reasoning-effort",
    type=click.Choice(["low", "medium", "high", "xhigh"]),
    help="Reasoning effort override for this turn.",
)
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
    reasoning_effort: ReasoningEffortChoice | None,
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
                reasoning_effort,
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
    reasoning_effort: ReasoningEffortChoice | None,
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
        reasoning_effort=parse_reasoning_effort(reasoning_effort or settings.reasoning_effort),
        sandbox=parse_sandbox(sandbox or settings.sandbox),
        approval_mode=parse_approval(approval or settings.approval),
        persist=persist,
        base_instructions=BLANK_BASE_INSTRUCTIONS if empty_base_instructions else None,
        developer_instructions=(
            BLANK_DEVELOPER_INSTRUCTIONS if empty_developer_instructions else None
        ),
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


@main.group()
def asr() -> None:
    """Run local audio transcription experiments."""


@asr.command("transcribe")
@click.option("--model-size", default="turbo", show_default=True)
@click.option("--language", default="ko", show_default=True)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "cuda"], case_sensitive=True),
    default="auto",
    show_default=True,
)
@click.option("--compute-type", default="auto", show_default=True)
@click.option("--chunk-minutes", type=click.IntRange(min=1), default=15, show_default=True)
@click.option("--overlap-seconds", type=click.IntRange(min=0), default=3, show_default=True)
@click.option("--beam-size", type=click.IntRange(min=1), default=5, show_default=True)
@click.option("--vad-filter/--no-vad-filter", default=True, show_default=True)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional path for the stored transcript JSON payload.",
)
@click.option("--keep-temp", is_flag=True, help="Keep downloaded/chunked audio files.")
@click.argument("video")
@click.pass_context
def asr_transcribe(
    ctx: click.Context,
    model_size: str,
    language: str,
    device: str,
    compute_type: str,
    chunk_minutes: int,
    overlap_seconds: int,
    beam_size: int,
    vad_filter: bool,
    output: Path | None,
    keep_temp: bool,
    video: str,
) -> None:
    """Transcribe YouTube VIDEO with faster-whisper and store transcript/cues."""
    request = FasterWhisperTranscribeRequest(
        video=video,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
        chunk_minutes=chunk_minutes,
        overlap_seconds=overlap_seconds,
        beam_size=beam_size,
        vad_filter=vad_filter,
        keep_temp=keep_temp,
    )
    result = _handle_errors(lambda: asyncio.run(_asr_transcribe_async(ctx, request)))
    if output is not None:
        output.write_text(
            result.transcript.model_dump_json(by_alias=True, indent=2),
            encoding="utf-8",
        )
    click.echo(json.dumps(result.summary_json(), indent=2, ensure_ascii=False))


async def _asr_transcribe_async(
    ctx: click.Context,
    request: FasterWhisperTranscribeRequest,
) -> FasterWhisperTranscribeResult:
    injected = _asr_transcribe_runner(ctx)
    if injected is not None:
        return await injected(request)

    settings = _settings()
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            use_case = TranscribeYouTubeAudioUseCase(
                downloader=YtDlpAudioDownloader(settings.ytdlp_bin),
                chunker=FfmpegAudioChunker(
                    ffmpeg_bin=settings.ffmpeg_bin,
                    ffprobe_bin=settings.ffprobe_bin,
                ),
                transcriber=FasterWhisperTranscriber(),
                storage=MinioTranscriptStorage.from_settings(settings),
                transcripts=SqlAlchemyYouTubeTranscriptRepository(session),
                cues=SqlAlchemyTranscriptCueRepository(session),
                storage_prefix=settings.transcript_minio_prefix,
            )
            return await use_case.execute(request)
    finally:
        await engine.dispose()


def _asr_transcribe_runner(ctx: click.Context) -> AsrTranscribeRunner | None:
    runner = ctx.obj.get("asr_transcribe_runner") if isinstance(ctx.obj, dict) else None
    return cast(AsrTranscribeRunner | None, runner)


@main.group()
def domain() -> None:
    """Manage streamer-scoped domain knowledge."""


@domain.group("type")
def domain_type() -> None:
    """Manage domain entry types."""


@domain_type.command("list")
def domain_type_list() -> None:
    """List domain entry types as JSON."""
    payload = _handle_errors(lambda: asyncio.run(_domain_type_list_async()))
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _domain_type_list_async() -> object:
    return await _with_domain_repository(
        lambda repository: _domain_type_list_with_repository(repository)
    )


async def _domain_type_list_with_repository(
    repository: DomainKnowledgeRepositoryPort,
) -> object:
    response = await ListDomainEntryTypesUseCase(repository).execute()
    return [item.model_dump(by_alias=True, mode="json") for item in response]


@domain.group("entry")
def domain_entry() -> None:
    """Manage domain knowledge entries."""


@domain_entry.command("list")
@click.option("--streamer-id", type=int, help="Only entries relevant to this streamer.")
@click.option("--type", "entry_type", help="Type key or label to filter.")
@click.option("--q", help="Search canonical names, details, and aliases.")
@click.option(
    "--include-inactive",
    is_flag=True,
    help="Include inactive archived entries.",
)
def domain_entry_list(
    streamer_id: int | None,
    entry_type: str | None,
    q: str | None,
    include_inactive: bool,
) -> None:
    """List domain entries as JSON."""
    payload = _handle_errors(
        lambda: asyncio.run(
            _domain_entry_list_async(
                streamer_id=streamer_id,
                entry_type=entry_type,
                q=q,
                active=None if include_inactive else True,
            )
        )
    )
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _domain_entry_list_async(
    *,
    streamer_id: int | None,
    entry_type: str | None,
    q: str | None,
    active: bool | None,
) -> object:
    return await _with_domain_repository(
        lambda repository: _domain_entry_list_with_repository(
            repository,
            streamer_id=streamer_id,
            entry_type=entry_type,
            q=q,
            active=active,
        )
    )


async def _domain_entry_list_with_repository(
    repository: DomainKnowledgeRepositoryPort,
    *,
    streamer_id: int | None,
    entry_type: str | None,
    q: str | None,
    active: bool | None,
) -> object:
    type_id = await _resolve_domain_entry_type_filter(repository, entry_type)
    response = await ListDomainEntriesUseCase(repository).execute(
        streamer_id=streamer_id,
        type_id=type_id,
        q=q,
        active=active,
        limit=500,
    )
    return response.model_dump(by_alias=True, mode="json")


@domain_entry.command("add")
@click.option("--type", "entry_type", required=True, help="Existing or new type label.")
@click.option("--name", required=True, help="Canonical entry name.")
@click.option("--detail", required=True, help="LLM-facing detail text.")
@click.option("--streamer-id", type=int, multiple=True, help="Related streamer ID.")
@click.option("--alias", multiple=True, help="Alias surface form.")
@click.option(
    "--prompt-policy",
    type=click.Choice(
        ["AUTO_ON_MATCH", "ALWAYS_FOR_SCOPED_STREAMER", "DISABLED"],
        case_sensitive=True,
    ),
    default="AUTO_ON_MATCH",
    show_default=True,
)
@click.option("--priority", type=int, default=50, show_default=True)
@click.option("--source-note", help="Optional source note.")
def domain_entry_add(
    entry_type: str,
    name: str,
    detail: str,
    streamer_id: tuple[int, ...],
    alias: tuple[str, ...],
    prompt_policy: str,
    priority: int,
    source_note: str | None,
) -> None:
    """Create a domain entry, creating the type when needed."""
    payload = _handle_errors(
        lambda: asyncio.run(
            _domain_entry_add_async(
                entry_type=entry_type,
                name=name,
                detail=detail,
                streamer_ids=list(streamer_id),
                aliases=list(alias),
                prompt_policy=prompt_policy,
                priority=priority,
                source_note=source_note,
            )
        )
    )
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _domain_entry_add_async(
    *,
    entry_type: str,
    name: str,
    detail: str,
    streamer_ids: list[int],
    aliases: list[str],
    prompt_policy: str,
    priority: int,
    source_note: str | None,
) -> object:
    request = DomainEntryCreateRequest(
        typeLabel=entry_type,
        canonicalName=name,
        detail=detail,
        promptPolicy=cast(PromptPolicy, prompt_policy),
        priority=priority,
        sourceNote=source_note,
        streamerIds=streamer_ids,
        aliases=[
            DomainEntryAliasCreateRequest(surfaceForm=surface_form) for surface_form in aliases
        ],
    )
    return await _with_domain_repository(
        lambda repository: _domain_entry_create_with_repository(repository, request)
    )


async def _domain_entry_create_with_repository(
    repository: DomainKnowledgeRepositoryPort,
    request: DomainEntryCreateRequest,
) -> object:
    response = await CreateDomainEntryUseCase(repository).execute(request)
    return response.model_dump(by_alias=True, mode="json")


@domain_entry.command("import")
@click.argument("file", type=click.Path(dir_okay=False, path_type=Path))
def domain_entry_import(file: Path) -> None:
    """Import domain entries from a JSONL file."""
    payload = _handle_errors(lambda: asyncio.run(_domain_entry_import_async(file)))
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _domain_entry_import_async(file: Path) -> object:
    requests = [
        DomainEntryCreateRequest.model_validate(json.loads(line))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return await _with_domain_repository(
        lambda repository: _domain_entry_import_with_repository(repository, requests)
    )


async def _domain_entry_import_with_repository(
    repository: DomainKnowledgeRepositoryPort,
    requests: list[DomainEntryCreateRequest],
) -> object:
    use_case = CreateDomainEntryUseCase(repository)
    items = []
    for request in requests:
        response = await use_case.execute(request)
        items.append(response.model_dump(by_alias=True, mode="json"))
    return {"items": items, "count": len(items)}


@main.group()
def timeline() -> None:
    """Manage timeline maintenance operations."""


@timeline.command("normalize-style")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Persist timeline style normalization changes.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview timeline style normalization changes without writing.",
)
def timeline_normalize_style(apply_changes: bool, dry_run: bool) -> None:
    """Normalize stored timeline prose from polite style to plain declarative style."""
    if apply_changes and dry_run:
        raise click.ClickException("Use either --apply or --dry-run, not both.")
    payload = _handle_errors(
        lambda: asyncio.run(_timeline_normalize_style_async(apply_changes=apply_changes))
    )
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _timeline_normalize_style_async(*, apply_changes: bool) -> object:
    settings = _settings()
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            return await normalize_timeline_style_backfill(
                session,
                apply=apply_changes,
            )
    finally:
        await engine.dispose()


@main.group()
def ops() -> None:
    """Run local operational read models."""


@ops.command("detect-stuck")
@click.option(
    "--task",
    "task_name",
    required=True,
    type=click.Choice(
        [MICRO_EVENT_EXTRACT_TASK_NAME, TIMELINE_COMPOSE_TASK_NAME],
        case_sensitive=True,
    ),
    help="Task name to inspect.",
)
@click.option(
    "--minutes",
    type=click.IntRange(min=1),
    default=15,
    show_default=True,
    help="Report running tasks with no task/event movement for this many minutes.",
)
def ops_detect_stuck(task_name: str, minutes: int) -> None:
    """Print stale running video tasks as JSON."""
    payload = _handle_errors(
        lambda: asyncio.run(
            _ops_detect_stuck_async(task_name=task_name, minutes=minutes)
        )
    )
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


async def _ops_detect_stuck_async(*, task_name: str, minutes: int) -> object:
    settings = _settings()
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            response = await DetectOpsStuckTasksUseCase(
                SqlAlchemyOpsRepository(session)
            ).execute(task_name=task_name, minutes=minutes)
            return response.model_dump(by_alias=True, mode="json")
    finally:
        await engine.dispose()


async def _resolve_domain_entry_type_filter(
    repository: DomainKnowledgeRepositoryPort,
    entry_type: str | None,
) -> int | None:
    if entry_type is None:
        return None
    normalized = entry_type.strip().casefold()
    normalized_key = _normalized_domain_entry_type_key(entry_type)
    for record in await repository.list_types():
        if (
            record.key.casefold() in {normalized, normalized_key}
            or record.label.casefold() == normalized
        ):
            return record.id
    raise click.ClickException(f"Domain entry type not found: {entry_type}")


def _normalized_domain_entry_type_key(value: str) -> str:
    lowered = value.strip().lower()
    key = re.sub(r"[^\w-]+", "-", lowered, flags=re.UNICODE)
    key = re.sub(r"_+", "-", key).strip("-")
    return key or "type"


async def _with_domain_repository(
    operation: Callable[[DomainKnowledgeRepositoryPort], Awaitable[T]],
) -> T:
    settings = _settings()
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            repository = SqlAlchemyDomainKnowledgeRepository(session)
            return await operation(repository)
    finally:
        await engine.dispose()


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


main.add_command(publication_command)
main.add_command(evaluation_command)
