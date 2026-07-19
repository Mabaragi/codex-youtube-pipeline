from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from alembic.config import Config
from click.testing import CliRunner
from sqlalchemy import func, inspect, select

from alembic import command
from codex_sdk_cli.application.evaluation.service import (
    EvaluationConflict,
    EvaluationService,
)
from codex_sdk_cli.domains.codex.ports import (
    CodexLoginResult,
    CodexRunCommand,
    CodexRunResult,
)
from codex_sdk_cli.domains.evaluation.ports import (
    EvaluationGenerationResult,
    EvaluationStoredObject,
    JsonObject,
)
from codex_sdk_cli.domains.evaluation.schemas import (
    EvaluationPlan,
    EvaluationScoreImport,
    MicroSelectionImport,
)
from codex_sdk_cli.evaluation_cli import evaluation
from codex_sdk_cli.infra.evaluation.connections import EvaluationDatabaseConnection
from codex_sdk_cli.infra.evaluation.generation import EvaluationGenerationService
from codex_sdk_cli.infra.evaluation.models import (
    EvaluationRunAttemptModel,
    EvaluationUsageModel,
)
from codex_sdk_cli.infra.evaluation.object_store import S3EvaluationObjectStore
from codex_sdk_cli.infra.evaluation.repository import SqlAlchemyEvaluationRepository
from codex_sdk_cli.infra.evaluation.session import (
    create_evaluation_engine,
    create_evaluation_session_factory,
)
from codex_sdk_cli.infra.evaluation.snapshot import ReadOnlyControlSnapshotter
from codex_sdk_cli.settings import CliSettings


class MemoryEvaluationObjects:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[JsonObject, EvaluationStoredObject]] = {}
        self.fail_results = False

    async def put_json(self, *, key: str, payload: JsonObject) -> EvaluationStoredObject:
        if self.fail_results and key.endswith("/result.json"):
            raise OSError("required object write failed")
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        stored = EvaluationStoredObject(
            key=key,
            sha256=hashlib.sha256(body).hexdigest(),
            byte_size=len(body),
        )
        self.objects[key] = (payload, stored)
        return stored

    async def get_json(self, *, key: str) -> JsonObject:
        return self.objects[key][0]

    async def stat(self, *, key: str) -> EvaluationStoredObject | None:
        item = self.objects.get(key)
        return item[1] if item else None


class StaticSnapshotter:
    def __init__(self, video_ids: list[int]) -> None:
        self.video_ids = video_ids
        self.calls = 0

    async def snapshot_plan_inputs(
        self, *, experiment_id: str, plan: EvaluationPlan
    ) -> list[JsonObject]:
        self.calls += 1
        prompt = {
            "versionId": 101,
            "versionLabel": "active-evaluation-v101",
            "body": "Private prompt snapshot.",
            "bodySha256": "a" * 64,
            "source": "database",
        }
        return [
            {
                "version": 1,
                "experimentId": experiment_id,
                "videoId": video_id,
                "youtubeVideoId": f"video-{video_id}",
                "video": {"id": video_id, "title": f"Video {video_id}"},
                "channel": {"id": 1, "name": "Channel"},
                "streamer": {"id": 1, "name": "Streamer"},
                "transcript": {"id": 10},
                "cues": [{"cueId": "c1", "text": "source cue"}],
                "domainKnowledge": [],
                "prompts": {
                    "micro": {
                        candidate.key: {"key": "micro_event_extract", **prompt}
                        for candidate in plan.micro_candidates
                    },
                    "timeline": {
                        candidate.key: {"key": "timeline_compose", **prompt}
                        for candidate in plan.timeline_candidates
                    },
                    "timelineRepair": {
                        "key": "timeline_episode_repair",
                        **prompt,
                    },
                },
            }
            for video_id in self.video_ids
        ]


class StaticGenerator:
    def __init__(self) -> None:
        self.failed_candidate: str | None = None
        self.calls: list[str] = []

    async def generate(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
        resume: bool,
    ) -> EvaluationGenerationResult:
        del experiment_id, snapshot, resume
        candidate = cast(str, run["candidateKey"])
        self.calls.append(candidate)
        if candidate == self.failed_candidate:
            raise RuntimeError("candidate failed independently")
        return EvaluationGenerationResult(
            output={
                "stage": run["stage"],
                "model": cast(JsonObject, run["candidateConfig"])["model"],
                "reasoningEffort": "high",
                "tokens": 999,
                "rawResponseText": "private raw response",
                "response": {"validationWarnings": [], "title": candidate},
            },
            artifacts=[],
        )


class ConcurrentGenerator(StaticGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def generate(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
        resume: bool,
    ) -> EvaluationGenerationResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().generate(
                experiment_id=experiment_id,
                run=run,
                snapshot=snapshot,
                resume=resume,
            )
        finally:
            self.active -= 1


class FakeCodexRuntime:
    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        context = command.usage_context
        assert context is not None
        if context.operation == "extract_window":
            start_index = ((context.window_index or 1) - 1) * 2 + 1
            output: JsonObject = {
                "events": [
                    {
                        "start_cue_id": f"cue-{start_index}",
                        "end_cue_id": f"cue-{start_index + 1}",
                        "event": "The streamer explains the test topic.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["test topic"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": [
                            f"cue-{start_index}",
                            f"cue-{start_index + 1}",
                        ],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
            }
        elif context.operation == "compose_video":
            output = {
                "video_summary": {
                    "title": "Test timeline",
                    "summary": "The test topic is discussed.",
                    "display_title": "Test timeline",
                    "display_summary": "The test topic is discussed.",
                    "main_topics": ["test topic"],
                },
                "blocks": [
                    {
                        "block_id": "block_001",
                        "block_type": "JUST_CHATTING",
                        "title": "Test block",
                        "summary": "The test topic is discussed.",
                        "display_title": "Test block",
                        "display_summary": "The test topic is discussed.",
                        "episode_ids": ["episode_001"],
                    }
                ],
                "episodes": [
                    {
                        "episode_id": "episode_001",
                        "parent_block_id": "block_001",
                        "start_micro_event_id": "me_0001",
                        "end_micro_event_id": "me_0001",
                        "program_mode": "JUST_CHATTING",
                        "primary_content_kind": "META_CHAT",
                        "title": "Test episode",
                        "summary": "The test topic is discussed.",
                        "display_title": "Test episode",
                        "display_summary": "The test topic is discussed.",
                        "topics": ["test topic"],
                        "viewer_tags": ["META"],
                        "highlight_micro_event_ids": ["me_0001"],
                        "visibility": "DEFAULT",
                    }
                ],
                "topic_clusters": [],
                "review_flags": [],
            }
        else:
            raise AssertionError(f"Unexpected fake Codex operation: {context.operation}")
        return CodexRunResult(
            thread_id=f"thread-{context.operation}",
            turn_id=f"turn-{context.operation}",
            status="completed",
            final_response=json.dumps(output),
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "cached_input_tokens": 2,
                "reasoning_output_tokens": 1,
            },
        )

    async def login_with_device_code(self) -> CodexLoginResult:
        return CodexLoginResult(success=True)

    async def login_api_key(self, api_key: str) -> None:
        del api_key

    async def account(self, *, refresh_token: bool = False) -> object:
        del refresh_token
        return {}

    async def logout(self) -> None:
        return None


class RetryCodexRuntime(FakeCodexRuntime):
    def __init__(self) -> None:
        self.fail_second_window = True
        self.window_calls: list[int | None] = []

    async def run_prompt(self, command: CodexRunCommand) -> CodexRunResult:
        context = command.usage_context
        assert context is not None
        if context.operation == "extract_window":
            self.window_calls.append(context.window_index)
            if self.fail_second_window and context.window_index == 2:
                raise RuntimeError("interrupted second window")
        return await super().run_prompt(command)


def test_plan_validation_and_defaults() -> None:
    plan = _plan("valid-plan")
    assert plan.repetitions == 1
    assert plan.run_concurrency == 1
    assert plan.micro_window_concurrency == 1
    with pytest.raises(ValueError, match="videoIds must be unique"):
        EvaluationPlan.model_validate(
            {**plan.model_dump(mode="json", by_alias=True), "videoIds": [1, 1]}
        )


def test_cli_validation_failure_is_structured_json(tmp_path: Path) -> None:
    plan_path = tmp_path / "invalid-plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(evaluation, ["create", "--plan", str(plan_path)])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["errorType"] == "ValidationError"


def test_evaluation_object_store_requires_versioning() -> None:
    class Versioning:
        def __init__(self, status: str | None) -> None:
            self.status = status

    class Client:
        def __init__(self, status: str | None) -> None:
            self.status = status

        def bucket_exists(self, bucket_name: str) -> bool:
            return bucket_name == "model-evaluations"

        def get_bucket_versioning(self, bucket_name: str) -> Versioning:
            assert bucket_name == "model-evaluations"
            return Versioning(self.status)

    S3EvaluationObjectStore(
        client=cast(Any, Client("Enabled")),
        bucket="model-evaluations",
    ).ensure_available()
    with pytest.raises(ValueError, match="versioning enabled"):
        S3EvaluationObjectStore(
            client=cast(Any, Client(None)),
            bucket="model-evaluations",
        ).ensure_available()


def test_evaluation_database_connection_requires_postgresql() -> None:
    connection = EvaluationDatabaseConnection.model_validate(
        {
            "kind": "sql_database",
            "databaseUrl": "sqlite+aiosqlite:///codex_model_evaluations",
        }
    )

    with pytest.raises(ValueError, match="PostgreSQL"):
        connection.validated_url()


def test_evaluation_repository_service_and_blinding(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "service")

    async def scenario() -> None:
        engine = create_evaluation_engine(database_url)
        sessions = create_evaluation_session_factory(engine)
        objects = MemoryEvaluationObjects()
        snapshots = StaticSnapshotter([1])
        generator = StaticGenerator()
        try:
            async with sessions() as session:
                repository = SqlAlchemyEvaluationRepository(session=session, engine=engine)
                service = EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=snapshots,
                    generator=generator,
                )
                plan = _plan("service-plan")
                created = await service.create(plan)
                experiment_id = cast(str, created["experimentId"])
                assert created["created"] is True
                resolved_plan = cast(JsonObject, created["plan"])
                resolved_micro = cast(list[JsonObject], resolved_plan["microCandidates"])
                resolved_timeline = cast(list[JsonObject], resolved_plan["timelineCandidates"])
                assert {item["promptVersionId"] for item in resolved_micro} == {101}
                assert {item["promptVersionId"] for item in resolved_timeline} == {101}
                assert (await service.create(plan))["created"] is False
                assert snapshots.calls == 1
                changed = plan.model_copy(update={"repetitions": 2})
                with pytest.raises(EvaluationConflict):
                    await service.create(changed)

                micro_result = await service.run(
                    experiment_id=experiment_id, stage="micro", resume=False
                )
                assert micro_result["ok"] is True
                bundle = await service.bundle(experiment_id=experiment_id, stage="micro")
                assert bundle["rubricVersion"] == "micro-v2"
                assert "asrComprehensionAccuracy" in cast(list[str], bundle["rubricKeys"])
                serialized = json.dumps(bundle)
                assert "gpt-5.5" not in serialized
                assert "reasoningEffort" not in serialized
                assert "private raw response" not in serialized
                assert '"tokens"' not in serialized
                assert '"prompts"' not in serialized

                micro_runs = await repository.list_stage_runs(experiment_id, "micro")
                assert str(UUID(cast(str, micro_runs[0]["runId"]))) == micro_runs[0]["runId"]
                legacy_scores = EvaluationScoreImport.model_validate(
                    {
                        "version": 1,
                        "stage": "micro",
                        "rubricVersion": "micro-v1",
                        "items": [
                            {
                                "blindRunId": run["blindRunId"],
                                "scores": {
                                    "boundaryEvidenceAccuracy": 4,
                                    "meaningfulCoverage": 4,
                                    "semanticTopicAccuracy": 4,
                                    "noiseDuplicationControl": 4,
                                    "timelineInputUsefulness": 4,
                                },
                            }
                            for run in micro_runs
                        ],
                    }
                )
                with pytest.raises(EvaluationConflict, match="rubricVersion"):
                    await service.import_scores(
                        experiment_id=experiment_id,
                        scores=legacy_scores,
                    )
                scores = EvaluationScoreImport.model_validate(
                    {
                        "version": 1,
                        "stage": "micro",
                        "rubricVersion": "micro-v2",
                        "items": [
                            {
                                "blindRunId": run["blindRunId"],
                                "scores": {
                                    "asrComprehensionAccuracy": 4,
                                    "boundaryEvidenceAccuracy": 4,
                                    "meaningfulCoverage": 4,
                                    "semanticTopicAccuracy": 4,
                                    "noiseDuplicationControl": 4,
                                    "timelineInputUsefulness": 4,
                                },
                            }
                            for run in micro_runs
                        ],
                    }
                )
                await service.import_scores(experiment_id=experiment_id, scores=scores)
                selection = MicroSelectionImport.model_validate(
                    {
                        "version": 1,
                        "selections": [
                            {
                                "videoId": 1,
                                "blindRunId": micro_runs[0]["blindRunId"],
                            }
                        ],
                    }
                )
                await service.select_micro(
                    experiment_id=experiment_id,
                    selections=selection,
                )
                timeline_runs = await repository.list_stage_runs(experiment_id, "timeline")
                assert {run["sourceMicroRunId"] for run in timeline_runs} == {
                    micro_runs[0]["runId"]
                }
                assert {run["sourceMicroResultObjectKey"] for run in timeline_runs} == {
                    micro_runs[0]["resultObjectKey"]
                }

                timeline_result = await service.run(
                    experiment_id=experiment_id,
                    stage="timeline",
                    resume=False,
                )
                assert timeline_result["ok"] is True
                with pytest.raises(ValueError, match="all successful scores"):
                    await service.report(experiment_id, unblind=True)
                timeline_scores = EvaluationScoreImport.model_validate(
                    {
                        "version": 1,
                        "stage": "timeline",
                        "rubricVersion": "timeline-v1",
                        "items": [
                            {
                                "blindRunId": run["blindRunId"],
                                "scores": {
                                    "coverageOrdering": 5,
                                    "boundaryCoherence": 5,
                                    "titleSummaryFactuality": 5,
                                    "topicNavigationUsefulness": 5,
                                    "concisionReadability": 5,
                                },
                            }
                            for run in timeline_runs
                        ],
                    }
                )
                await service.import_scores(
                    experiment_id=experiment_id,
                    scores=timeline_scores,
                )
                report = await service.report(experiment_id, unblind=True)
                assert report["unblinded"] is True
                report_candidates = cast(list[JsonObject], report["candidates"])
                assert all("config" in item for item in report_candidates)
                assert (await service.verify(experiment_id))["ok"] is True
                artifact_key = cast(
                    str, (await repository.artifacts(experiment_id))[0]["objectKey"]
                )
                artifact_payload, artifact = objects.objects[artifact_key]
                objects.objects[artifact_key] = (
                    artifact_payload,
                    EvaluationStoredObject(
                        key=artifact.key,
                        sha256="0" * 64,
                        byte_size=artifact.byte_size,
                    ),
                )
                assert (await service.verify(experiment_id))["ok"] is False
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_failed_run_isolated_and_required_object_failure_resumes(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "resume")

    async def scenario() -> None:
        engine = create_evaluation_engine(database_url)
        sessions = create_evaluation_session_factory(engine)
        objects = MemoryEvaluationObjects()
        generator = StaticGenerator()
        try:
            async with sessions() as session:
                repository = SqlAlchemyEvaluationRepository(session=session, engine=engine)
                service = EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=StaticSnapshotter([1]),
                    generator=generator,
                )
                created = await service.create(_plan("resume-plan"))
                experiment_id = cast(str, created["experimentId"])
                generator.failed_candidate = "micro-b"
                first = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=False,
                )
                assert first["ok"] is False
                first_items = cast(list[JsonObject], first["items"])
                assert [item["status"] for item in first_items].count("succeeded") == 1
                assert [item["status"] for item in first_items].count("failed") == 1

                generator.failed_candidate = None
                objects.fail_results = True
                second = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=True,
                )
                assert second["ok"] is False
                runs = await repository.list_stage_runs(experiment_id, "micro")
                succeeded = [run for run in runs if run["status"] == "succeeded"]
                failed = [run for run in runs if run["status"] == "failed"]
                assert len(succeeded) == 1
                assert len(failed) == 1

                objects.fail_results = False
                third = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=True,
                )
                assert third["ok"] is True
                final_runs = await repository.list_stage_runs(experiment_id, "micro")
                assert {run["status"] for run in final_runs} == {"succeeded"}
                assert sorted(cast(int, run["attemptCount"]) for run in final_runs) == [1, 3]

                interrupted_run_id = cast(str, final_runs[0]["runId"])
                await repository.prepare_run_attempt(interrupted_run_id, resume=False)
                await repository.commit()
                resumed_interruption = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=True,
                )
                assert resumed_interruption["ok"] is True
                interrupted_attempts = (
                    await session.scalars(
                        select(EvaluationRunAttemptModel)
                        .where(EvaluationRunAttemptModel.run_id == interrupted_run_id)
                        .order_by(EvaluationRunAttemptModel.attempt_no)
                    )
                ).all()
                assert [attempt.status for attempt in interrupted_attempts][-2:] == [
                    "abandoned",
                    "succeeded",
                ]

                assert await repository.acquire_experiment_lock(experiment_id) is True
                assert await repository.acquire_experiment_lock(experiment_id) is False
                await repository.release_experiment_lock(experiment_id)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_plan_run_concurrency_is_applied(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "concurrency")

    async def scenario() -> None:
        engine = create_evaluation_engine(database_url)
        sessions = create_evaluation_session_factory(engine)
        generator = ConcurrentGenerator()
        try:
            async with sessions() as session:
                repository = SqlAlchemyEvaluationRepository(session=session, engine=engine)
                service = EvaluationService(
                    repository=repository,
                    objects=MemoryEvaluationObjects(),
                    snapshotter=StaticSnapshotter([1]),
                    generator=generator,
                )
                plan = _plan("concurrency-plan").model_copy(update={"run_concurrency": 2})
                created = await service.create(plan)
                result = await service.run(
                    experiment_id=cast(str, created["experimentId"]),
                    stage="micro",
                    resume=False,
                )
                assert result["ok"] is True
                assert generator.max_active == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_evaluation_migration_has_isolated_schema(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "schema")

    async def table_names() -> set[str]:
        engine = create_evaluation_engine(database_url)
        try:
            async with engine.connect() as connection:
                return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
        finally:
            await engine.dispose()

    names = asyncio.run(table_names())
    assert {
        "evaluation_experiments",
        "evaluation_cases",
        "evaluation_candidates",
        "evaluation_runs",
        "evaluation_run_attempts",
        "evaluation_run_checkpoints",
        "evaluation_usage_records",
        "evaluation_artifacts",
        "evaluation_reviews",
        "evaluation_micro_selections",
    }.issubset(names)
    assert "videos" not in names
    assert "work_items" not in names
    assert "archive_publications" not in names


def test_control_snapshot_starts_repeatable_read_only_transaction() -> None:
    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Session:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def get_bind(self) -> Bind:
            return Bind()

        async def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

    session = Session()
    snapshotter = ReadOnlyControlSnapshotter(cast(Any, session))
    asyncio.run(snapshotter._begin_read_only_snapshot())
    assert session.statements == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]


def test_generation_service_uses_snapshots_and_fake_codex(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "generation")

    async def scenario() -> None:
        engine = create_evaluation_engine(database_url)
        sessions = create_evaluation_session_factory(engine)
        objects = MemoryEvaluationObjects()
        try:
            async with sessions() as session:
                repository = SqlAlchemyEvaluationRepository(session=session, engine=engine)
                generator = EvaluationGenerationService(
                    settings=CliSettings(),
                    session_factory=sessions,
                    engine=engine,
                    objects=objects,
                    runtime_client_factory=FakeCodexRuntime,
                )
                service = EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=GenerationSnapshotter(),
                    generator=generator,
                )
                plan = _one_candidate_plan("generation-plan")
                created = await service.create(plan)
                experiment_id = cast(str, created["experimentId"])
                micro = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=False,
                )
                assert micro["ok"] is True
                micro_runs = await repository.list_stage_runs(experiment_id, "micro")
                await service.import_scores(
                    experiment_id=experiment_id,
                    scores=EvaluationScoreImport.model_validate(
                        {
                            "stage": "micro",
                            "rubricVersion": "micro-v2",
                            "items": [
                                {
                                    "blindRunId": micro_runs[0]["blindRunId"],
                                    "scores": {
                                        "asrComprehensionAccuracy": 5,
                                        "boundaryEvidenceAccuracy": 5,
                                        "meaningfulCoverage": 5,
                                        "semanticTopicAccuracy": 5,
                                        "noiseDuplicationControl": 5,
                                        "timelineInputUsefulness": 5,
                                    },
                                }
                            ],
                        }
                    ),
                )
                await service.select_micro(
                    experiment_id=experiment_id,
                    selections=MicroSelectionImport.model_validate(
                        {
                            "selections": [
                                {
                                    "videoId": 1,
                                    "blindRunId": micro_runs[0]["blindRunId"],
                                }
                            ]
                        }
                    ),
                )
                timeline = await service.run(
                    experiment_id=experiment_id,
                    stage="timeline",
                    resume=False,
                )
                assert timeline["ok"] is True
                usage_count = await session.scalar(
                    select(func.count()).select_from(EvaluationUsageModel)
                )
                assert usage_count == 2
                artifacts = await repository.artifacts(experiment_id)
                assert any(item["kind"] == "micro-checkpoint" for item in artifacts)
                assert any(item["kind"] == "llm-trace" for item in artifacts)
                assert (await service.verify(experiment_id))["ok"] is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_micro_resume_reuses_successful_window_checkpoint(tmp_path: Path) -> None:
    database_url = _migrated_database(tmp_path, "checkpoint-resume")

    async def scenario() -> None:
        engine = create_evaluation_engine(database_url)
        sessions = create_evaluation_session_factory(engine)
        objects = MemoryEvaluationObjects()
        runtime = RetryCodexRuntime()
        try:
            async with sessions() as session:
                repository = SqlAlchemyEvaluationRepository(session=session, engine=engine)
                service = EvaluationService(
                    repository=repository,
                    objects=objects,
                    snapshotter=GenerationSnapshotter(long_transcript=True),
                    generator=EvaluationGenerationService(
                        settings=CliSettings(),
                        session_factory=sessions,
                        engine=engine,
                        objects=objects,
                        runtime_client_factory=lambda: runtime,
                    ),
                )
                plan_payload = _one_candidate_plan("checkpoint-plan").model_dump(
                    mode="json", by_alias=True
                )
                micro = cast(list[JsonObject], plan_payload["microCandidates"])[0]
                micro["windowMinutes"] = 1
                micro["overlapMinutes"] = 0
                created = await service.create(EvaluationPlan.model_validate(plan_payload))
                experiment_id = cast(str, created["experimentId"])
                first = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=False,
                )
                assert first["ok"] is False
                assert runtime.window_calls.count(1) == 1
                assert runtime.window_calls.count(2) == 3
                checkpoints = await repository.checkpoints(
                    cast(
                        str, (await repository.list_stage_runs(experiment_id, "micro"))[0]["runId"]
                    )
                )
                assert {item["status"] for item in checkpoints} == {"succeeded", "failed"}

                runtime.fail_second_window = False
                resumed = await service.run(
                    experiment_id=experiment_id,
                    stage="micro",
                    resume=True,
                )
                assert resumed["ok"] is True, resumed
                assert runtime.window_calls.count(1) == 1
                assert runtime.window_calls.count(2) == 4
                usage_count = await session.scalar(
                    select(func.count()).select_from(EvaluationUsageModel)
                )
                assert usage_count == 5
                report = await service.report(experiment_id, unblind=False)
                candidates = cast(list[JsonObject], report["candidates"])
                tokens = cast(JsonObject, candidates[0]["tokens"])
                assert tokens == {
                    "actualCachedInputTokens": 4,
                    "actualInputTokens": 20,
                    "actualOutputTokens": 10,
                    "actualReasoningOutputTokens": 2,
                    "actualTotalTokens": 30,
                    "successfulAttemptCachedInputTokens": 2,
                    "successfulAttemptInputTokens": 10,
                    "successfulAttemptOutputTokens": 5,
                    "successfulAttemptReasoningOutputTokens": 1,
                    "successfulAttemptTokens": 15,
                }
        finally:
            await engine.dispose()

    asyncio.run(scenario())


class GenerationSnapshotter:
    def __init__(self, *, long_transcript: bool = False) -> None:
        self._long_transcript = long_transcript

    async def snapshot_plan_inputs(
        self, *, experiment_id: str, plan: EvaluationPlan
    ) -> list[JsonObject]:
        del plan
        now = "2026-07-18T00:00:00+00:00"
        prompt = {
            "versionId": 1,
            "versionLabel": "evaluation-v1",
            "body": "Generate the requested structured result.",
            "bodySha256": "a" * 64,
            "source": "database",
        }
        return [
            {
                "version": 1,
                "experimentId": experiment_id,
                "videoId": 1,
                "youtubeVideoId": "abcdefghijk",
                "video": {
                    "id": 1,
                    "channel_id": 1,
                    "youtube_video_id": "abcdefghijk",
                    "title": "Evaluation video",
                    "description": "",
                    "published_at": now,
                    "duration": "PT1M",
                    "thumbnail_url": None,
                    "source_listing_api_call_id": None,
                    "source_details_api_call_id": None,
                    "source_job_id": None,
                    "created_at": now,
                    "updated_at": now,
                    "is_embeddable": True,
                    "embed_status_checked_at": now,
                    "source_embed_status_api_call_id": None,
                },
                "channel": {
                    "id": 1,
                    "streamer_id": 1,
                    "handle": "@evaluation",
                    "name": "Evaluation",
                    "youtube_channel_id": "channel-1",
                    "uploads_playlist_id": "uploads-1",
                    "source_api_call_id": None,
                    "source_job_id": None,
                },
                "streamer": {"id": 1, "name": "Evaluation", "publish_profile_id": 1},
                "transcript": {
                    "id": 10,
                    "video_id": "abcdefghijk",
                    "language": "English",
                    "language_code": "en",
                    "is_generated": False,
                    "requested_languages": ["en"],
                    "preserve_formatting": False,
                    "storage_bucket": "transcripts",
                    "storage_object_name": "private.json",
                    "storage_uri": "s3://transcripts/private.json",
                    "response_sha256": "b" * 64,
                    "segment_count": 2,
                    "text_length": 20,
                    "notes": None,
                    "created_at": now,
                    "updated_at": now,
                },
                "cues": (
                    [
                        _generation_cue(1, "cue-1", 0, 30_000, now),
                        _generation_cue(2, "cue-2", 30_000, 60_000, now),
                        _generation_cue(3, "cue-3", 60_000, 90_000, now),
                        _generation_cue(4, "cue-4", 90_000, 120_000, now),
                    ]
                    if self._long_transcript
                    else [
                        _generation_cue(1, "cue-1", 0, 30_000, now),
                        _generation_cue(2, "cue-2", 30_000, 60_000, now),
                    ]
                ),
                "domainKnowledge": [],
                "prompts": {
                    "micro": {"micro-a": {"key": "micro_event_extract", **prompt}},
                    "timeline": {"timeline-a": {"key": "timeline_compose", **prompt}},
                    "timelineRepair": {
                        "key": "timeline_episode_repair",
                        **prompt,
                    },
                },
            }
        ]


def _plan(experiment_key: str) -> EvaluationPlan:
    return EvaluationPlan.model_validate(
        {
            "version": 1,
            "experimentKey": experiment_key,
            "videoIds": [1],
            "microCandidates": [
                {
                    "key": "micro-a",
                    "model": "gpt-5.5",
                    "reasoningEffort": "medium",
                    "windowMinutes": 30,
                    "overlapMinutes": 5,
                },
                {
                    "key": "micro-b",
                    "model": "gpt-5.5",
                    "reasoningEffort": "high",
                    "windowMinutes": 30,
                    "overlapMinutes": 5,
                },
            ],
            "timelineCandidates": [
                {
                    "key": "timeline-a",
                    "model": "gpt-5.5",
                    "reasoningEffort": "medium",
                    "copyStyle": "LIGHT_FANDOM_V1",
                },
                {
                    "key": "timeline-b",
                    "model": "gpt-5.5",
                    "reasoningEffort": "high",
                    "copyStyle": "LIGHT_FANDOM_V1",
                },
            ],
        }
    )


def _one_candidate_plan(experiment_key: str) -> EvaluationPlan:
    payload = _plan(experiment_key).model_dump(mode="json", by_alias=True)
    payload["microCandidates"] = cast(list[object], payload["microCandidates"])[:1]
    payload["timelineCandidates"] = cast(list[object], payload["timelineCandidates"])[:1]
    return EvaluationPlan.model_validate(payload)


def _generation_cue(
    cue_index: int,
    cue_id: str,
    start_ms: int,
    end_ms: int,
    now: str,
) -> JsonObject:
    return {
        "id": cue_index,
        "transcript_id": 10,
        "cue_id": cue_id,
        "cue_index": cue_index,
        "text": f"source cue {cue_index}",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": end_ms - start_ms,
        "source_segment_index": cue_index - 1,
        "source_job_id": None,
        "source_job_attempt_id": None,
        "source_work_item_id": None,
        "source_work_attempt_id": None,
        "created_at": now,
        "updated_at": now,
    }


def _migrated_database(tmp_path: Path, name: str) -> str:
    database_path = (tmp_path / f"{name}.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{database_path}"
    configuration = Config("evaluation-alembic.ini")
    configuration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(configuration, "head")
    return database_url
