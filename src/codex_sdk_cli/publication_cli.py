from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast

import click

from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.infra.publication.legacy_connections import (
    import_legacy_publication_connections,
)
from codex_sdk_cli.infra.publication.migration import (
    PublicationDataMigrator,
    PublicationMigrationMode,
    PublicationMigrationRequest,
    write_publication_migration_report,
)
from codex_sdk_cli.settings import CliSettings

PublicationMigrationRunner = Callable[
    [CliSettings, PublicationMigrationRequest],
    Coroutine[Any, Any, dict[str, object]],
]


@click.group()
def publication() -> None:
    """Manage publication routing migration and private connections."""


@publication.command("migrate")
@click.option(
    "--mode",
    required=True,
    type=click.Choice(["dry-run", "apply", "resume", "verify"]),
)
@click.option("--profile-revision-id", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--publish-mode", type=click.Choice(["prod", "dev"]), default="prod")
@click.option("--environment", default="prod", show_default=True)
@click.option("--schema-version", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--latest-limit", type=click.IntRange(min=1), default=180, show_default=True)
@click.option(
    "--expected-artifact-count",
    type=click.IntRange(min=0),
    default=802,
    show_default=True,
)
@click.option(
    "--expected-ready-count",
    type=click.IntRange(min=0),
    default=450,
    show_default=True,
)
@click.option(
    "--expected-unavailable-count",
    type=click.IntRange(min=0),
    default=352,
    show_default=True,
)
@click.option(
    "--expected-latest-count",
    type=click.IntRange(min=0),
    default=179,
    show_default=True,
)
@click.option(
    "--expected-history-count",
    type=click.IntRange(min=0),
    default=416,
    show_default=True,
)
@click.option("--source-manifest", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--report-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".home-deploy/migration-reports"),
    show_default=True,
)
@click.pass_context
def publication_migrate(
    ctx: click.Context,
    mode: str,
    profile_revision_id: int,
    publish_mode: str,
    environment: str,
    schema_version: int,
    latest_limit: int,
    expected_artifact_count: int,
    expected_ready_count: int,
    expected_unavailable_count: int,
    expected_latest_count: int,
    expected_history_count: int,
    source_manifest: Path | None,
    report_dir: Path,
) -> None:
    """Migrate, resume, or verify legacy publication data idempotently."""
    settings = CliSettings()
    request = PublicationMigrationRequest(
        mode=cast(PublicationMigrationMode, mode),
        profile_revision_id=profile_revision_id,
        publish_mode=publish_mode,
        environment=environment,
        schema_version=schema_version,
        latest_limit=latest_limit,
        expected_artifact_count=expected_artifact_count,
        expected_ready_count=expected_ready_count,
        expected_unavailable_count=expected_unavailable_count,
        expected_latest_count=expected_latest_count,
        expected_history_count=expected_history_count,
        source_manifest=source_manifest,
    )
    runner = _migration_runner(ctx)
    try:
        report = asyncio.run(runner(settings, request))
    except Exception as exc:
        failure_report: dict[str, object] = {
            "version": 1,
            "mode": mode,
            "mutated": request.mutates,
            "ok": False,
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
        }
        report_path = write_publication_migration_report(
            failure_report,
            report_dir=report_dir,
        )
        raise click.ClickException(f"Publication migration failed. Report: {report_path}") from exc
    report_path = write_publication_migration_report(report, report_dir=report_dir)
    report["reportPath"] = str(report_path)
    click.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("ok"):
        raise click.ClickException(
            f"Publication migration verification did not pass. Report: {report_path}"
        )


@publication.group("connections")
def publication_connections() -> None:
    """Manage the private publication connection registry."""


@publication_connections.command("import-legacy")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Write missing legacy connections; otherwise only preview them.",
)
@click.option(
    "--file",
    "registry_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Override CODEX_CLI_PUBLISH_CONNECTIONS_FILE.",
)
def publication_connections_import_legacy(
    apply_changes: bool,
    registry_path: Path | None,
) -> None:
    """One-time import of old object/catalog environment settings."""
    settings = CliSettings()
    path = registry_path or settings.publish_connections_file
    if path is None:
        raise click.ClickException("A publication connection registry path is required.")
    try:
        result = import_legacy_publication_connections(
            settings,
            path=path,
            apply=apply_changes,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


async def default_publication_migration_runner(
    settings: CliSettings,
    request: PublicationMigrationRequest,
) -> dict[str, object]:
    connections = PublicationConnectionFactory.from_settings(settings)
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            return await PublicationDataMigrator(
                session=session,
                connections=connections,
                artifact_store_ref=settings.publication_artifact_store_ref,
                staging_store_ref=settings.publication_staging_store_ref,
            ).run(request)
    finally:
        await connections.aclose()
        await engine.dispose()


def _migration_runner(ctx: click.Context) -> PublicationMigrationRunner:
    value = ctx.obj.get("publication_migration_runner") if isinstance(ctx.obj, dict) else None
    if value is None:
        return default_publication_migration_runner
    return cast(PublicationMigrationRunner, value)
