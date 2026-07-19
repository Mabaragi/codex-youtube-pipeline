from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, NoReturn, cast

import click
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from codex_sdk_cli.application.evaluation.service import (
    EvaluationConflict,
    EvaluationError,
    EvaluationService,
    write_bundle,
)
from codex_sdk_cli.domains.evaluation.ports import JsonObject
from codex_sdk_cli.domains.evaluation.schemas import (
    EvaluationPlan,
    EvaluationScoreImport,
    EvaluationStage,
    MicroSelectionImport,
)
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.evaluation.connections import EvaluationConnections
from codex_sdk_cli.infra.evaluation.generation import EvaluationGenerationService
from codex_sdk_cli.infra.evaluation.object_store import S3EvaluationObjectStore
from codex_sdk_cli.infra.evaluation.repository import SqlAlchemyEvaluationRepository
from codex_sdk_cli.infra.evaluation.session import (
    create_evaluation_engine,
    create_evaluation_session_factory,
)
from codex_sdk_cli.infra.evaluation.snapshot import ReadOnlyControlSnapshotter
from codex_sdk_cli.settings import CliSettings

_PRIVATE_EXPERIMENT_DIR = Path(".home-deploy/experiments")


@click.group()
def evaluation() -> None:
    """Run isolated, one-shot model evaluations."""


@evaluation.command("prepare")
def evaluation_prepare() -> None:
    """Validate private infrastructure and migrate only the evaluation schema."""
    settings = CliSettings()
    connections = _connections(settings)
    database_url = connections.database.validated_url()
    objects = _objects(connections)
    try:
        objects.ensure_available()
        configuration = Config("evaluation-alembic.ini")
        configuration.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(configuration, "head")
        result = asyncio.run(_prepared_state(database_url))
    except Exception as exc:
        _fail(exc)
    _echo_json(
        {
            "ok": True,
            "database": "codex_model_evaluations",
            "bucket": "model-evaluations",
            **result,
        }
    )


@evaluation.command("create")
@click.option(
    "--plan",
    "plan_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def evaluation_create(plan_path: Path) -> None:
    """Create an idempotent experiment and immutable source snapshots."""
    try:
        plan = EvaluationPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        result = asyncio.run(_invoke(lambda service: service.create(plan), control=True))
    except Exception as exc:
        _fail(exc)
    _echo_json(result)


@evaluation.command("run")
@click.option("--experiment-id", required=True)
@click.option("--stage", required=True, type=click.Choice(["micro", "timeline"]))
def evaluation_run(experiment_id: str, stage: str) -> None:
    """Run pending candidates for one evaluation stage."""
    _run_stage(experiment_id=experiment_id, stage=cast(EvaluationStage, stage), resume=False)


@evaluation.command("resume")
@click.option("--experiment-id", required=True)
@click.option("--stage", required=True, type=click.Choice(["micro", "timeline"]))
def evaluation_resume(experiment_id: str, stage: str) -> None:
    """Retry failed or abandoned candidates while reusing successful checkpoints."""
    _run_stage(experiment_id=experiment_id, stage=cast(EvaluationStage, stage), resume=True)


@evaluation.command("bundle")
@click.option("--experiment-id", required=True)
@click.option("--stage", required=True, type=click.Choice(["micro", "timeline"]))
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=_PRIVATE_EXPERIMENT_DIR / "bundles",
    show_default=True,
)
def evaluation_bundle(experiment_id: str, stage: str, output_dir: Path) -> None:
    """Write a blind review bundle without model or token identity."""
    try:
        bundle = asyncio.run(
            _invoke(
                lambda service: service.bundle(
                    experiment_id=experiment_id,
                    stage=cast(EvaluationStage, stage),
                )
            )
        )
        path = write_bundle(bundle, output_dir=output_dir)
    except Exception as exc:
        _fail(exc)
    _echo_json(
        {
            "ok": True,
            "experimentId": experiment_id,
            "stage": stage,
            "itemCount": len(cast(list[object], bundle["items"])),
            "bundlePath": str(path),
        }
    )


@evaluation.group("score")
def evaluation_score() -> None:
    """Manage blind evaluation scores."""


@evaluation_score.command("import")
@click.option("--experiment-id", required=True)
@click.option(
    "--file",
    "score_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def evaluation_score_import(experiment_id: str, score_path: Path) -> None:
    """Validate and import blind rubric scores."""
    try:
        scores = EvaluationScoreImport.model_validate_json(score_path.read_text(encoding="utf-8"))
        result = asyncio.run(
            _invoke(
                lambda service: service.import_scores(
                    experiment_id=experiment_id,
                    scores=scores,
                )
            )
        )
    except Exception as exc:
        _fail(exc)
    _echo_json({"ok": True, **result})


@evaluation.command("select-micro")
@click.option("--experiment-id", required=True)
@click.option(
    "--file",
    "selection_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def evaluation_select_micro(experiment_id: str, selection_path: Path) -> None:
    """Select one scored micro run per video as immutable timeline input."""
    try:
        selections = MicroSelectionImport.model_validate_json(
            selection_path.read_text(encoding="utf-8")
        )
        result = asyncio.run(
            _invoke(
                lambda service: service.select_micro(
                    experiment_id=experiment_id,
                    selections=selections,
                )
            )
        )
    except Exception as exc:
        _fail(exc)
    _echo_json({"ok": True, **result})


@evaluation.command("status")
@click.option("--experiment-id", required=True)
@click.option("--json", "json_output", is_flag=True, help="Emit structured JSON (default).")
def evaluation_status(experiment_id: str, json_output: bool) -> None:
    """Show stage, selection, and run state."""
    del json_output
    try:
        result = asyncio.run(_invoke(lambda service: service.status(experiment_id)))
    except Exception as exc:
        _fail(exc)
    _echo_json({"ok": True, **result})


@evaluation.command("report")
@click.option("--experiment-id", required=True)
@click.option("--format", "report_format", type=click.Choice(["json", "md"]), default="json")
@click.option("--unblind", is_flag=True)
def evaluation_report(experiment_id: str, report_format: str, unblind: bool) -> None:
    """Aggregate quality, failures, successful tokens, and actual retry tokens."""
    try:
        report = asyncio.run(
            _invoke(lambda service: service.report(experiment_id, unblind=unblind))
        )
        if report_format == "json":
            _echo_json({"ok": True, **report})
            return
        path = _write_markdown_report(report)
    except Exception as exc:
        _fail(exc)
    _echo_json(
        {
            "ok": True,
            "experimentId": experiment_id,
            "unblinded": unblind,
            "reportPath": str(path),
        }
    )


@evaluation.command("verify")
@click.option("--experiment-id", required=True)
def evaluation_verify(experiment_id: str) -> None:
    """Verify every evaluation object's key, SHA-256, and byte size."""
    try:
        result = asyncio.run(_invoke(lambda service: service.verify(experiment_id)))
    except Exception as exc:
        _fail(exc)
    _echo_json(result)
    if not result.get("ok"):
        raise click.exceptions.Exit(1)


def _run_stage(*, experiment_id: str, stage: EvaluationStage, resume: bool) -> None:
    click.echo(
        json.dumps({"event": "evaluation_started", "stage": stage}),
        err=True,
    )
    try:
        result = asyncio.run(
            _invoke(
                lambda service: service.run(
                    experiment_id=experiment_id,
                    stage=stage,
                    resume=resume,
                )
            )
        )
    except Exception as exc:
        _fail(exc)
    _echo_json(result)
    if not result.get("ok"):
        raise click.exceptions.Exit(1)


async def _prepared_state(database_url: str) -> JsonObject:
    engine = create_evaluation_engine(database_url)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        return {"migrationRevision": revision}
    finally:
        await engine.dispose()


async def _invoke(
    operation: Callable[[EvaluationService], Coroutine[Any, Any, JsonObject]],
    *,
    control: bool = False,
) -> JsonObject:
    async with _service(control=control) as service:
        return await operation(service)


@asynccontextmanager
async def _service(*, control: bool) -> AsyncGenerator[EvaluationService]:
    settings = CliSettings()
    connections = _connections(settings)
    evaluation_engine = create_evaluation_engine(
        connections.database.validated_url(),
        echo=connections.database.echo,
    )
    evaluation_sessions = create_evaluation_session_factory(evaluation_engine)
    control_engine = None
    objects = _objects(connections)
    try:
        async with evaluation_sessions() as evaluation_session:
            repository = SqlAlchemyEvaluationRepository(
                session=evaluation_session,
                engine=evaluation_engine,
            )
            if control:
                control_engine = create_database_engine(
                    settings.database_url,
                    echo=settings.database_echo,
                )
                control_sessions = create_session_factory(control_engine)
                yield EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=_ControlSnapshotter(control_sessions),
                    generator=_generator(
                        settings,
                        evaluation_sessions,
                        evaluation_engine,
                        objects,
                    ),
                )
            else:
                yield EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=_UnavailableSnapshotter(),
                    generator=_generator(
                        settings,
                        evaluation_sessions,
                        evaluation_engine,
                        objects,
                    ),
                )
    finally:
        if control_engine is not None:
            await control_engine.dispose()
        await evaluation_engine.dispose()


def _generator(
    settings: CliSettings,
    sessions: Any,
    engine: Any,
    objects: S3EvaluationObjectStore,
) -> EvaluationGenerationService:
    return EvaluationGenerationService(
        settings=settings,
        session_factory=sessions,
        engine=engine,
        objects=objects,
    )


class _UnavailableSnapshotter:
    async def snapshot_plan_inputs(
        self, *, experiment_id: str, plan: EvaluationPlan
    ) -> list[JsonObject]:
        del experiment_id, plan
        raise RuntimeError("Control snapshots are available only during evaluation create.")


class _ControlSnapshotter:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def snapshot_plan_inputs(
        self,
        *,
        experiment_id: str,
        plan: EvaluationPlan,
    ) -> list[JsonObject]:
        async with self._sessions() as session:
            return await ReadOnlyControlSnapshotter(session).snapshot_plan_inputs(
                experiment_id=experiment_id,
                plan=plan,
            )


def _connections(settings: CliSettings) -> EvaluationConnections:
    return EvaluationConnections.from_file(settings.evaluation_connections_file)


def _objects(connections: EvaluationConnections) -> S3EvaluationObjectStore:
    config = connections.object_store
    return S3EvaluationObjectStore.from_values(
        endpoint=config.endpoint,
        access_key=config.access_key.get_secret_value(),
        secret_key=config.secret_key.get_secret_value(),
        bucket=config.bucket,
        secure=config.secure,
        region=config.region,
    )


def _write_markdown_report(report: JsonObject) -> Path:
    directory = _PRIVATE_EXPERIMENT_DIR / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['experimentId']}-report.md"
    lines = [
        "# Model evaluation report",
        "",
        f"- Experiment: `{report['experimentId']}`",
        f"- Unblinded: `{str(report.get('unblinded', False)).lower()}`",
        "",
        "| Stage | Candidate | Failure rate | Quality | Actual tokens | Success tokens |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for candidate in cast(list[JsonObject], report.get("candidates") or []):
        quality = cast(JsonObject, candidate["quality"])
        tokens = cast(JsonObject, candidate["tokens"])
        lines.append(
            "| {stage} | {alias} | {failure:.2%} | {quality} | {actual} | {success} |".format(
                stage=candidate["stage"],
                alias=candidate.get("candidateKey") or candidate["candidateAlias"],
                failure=cast(float, candidate["failureRate"]),
                quality=quality.get("averageTotalScore") or "-",
                actual=tokens["actualTotalTokens"],
                success=tokens["successfulAttemptTokens"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return str(exc)
    if isinstance(exc, (EvaluationError, EvaluationConflict, ValueError)):
        return str(exc)
    return "Evaluation command failed; inspect private evaluation state."


def _fail(exc: Exception) -> NoReturn:
    _echo_json(
        {
            "ok": False,
            "errorType": type(exc).__name__,
            "errorMessage": _safe_error(exc),
        }
    )
    raise click.exceptions.Exit(1)


def _echo_json(payload: JsonObject) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
