from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from codex_sdk_cli.api.main import app, create_app
from codex_sdk_cli.api.use_case_dependencies.automation import (
    get_automation_repository,
    get_execute_incident_action_use_case,
)
from codex_sdk_cli.application.asr.executors import _permanently_unavailable
from codex_sdk_cli.application.automation.use_cases import (
    ExecuteIncidentActionUseCase,
    MarkRuntimeStoppedUseCase,
    RequestRuntimeDrainUseCase,
    ResumeRuntimeUseCase,
    RunPipelineSupervisorUseCase,
    RuntimeNotDrained,
    _is_transient,
)
from codex_sdk_cli.application.scheduler.ports import SchedulerEvent
from codex_sdk_cli.application.scheduler.use_cases import (
    PipelineSchedulerConfig,
    RunPipelineSchedulerTickUseCase,
)
from codex_sdk_cli.application.transcripts.commands import CollectTranscriptsUseCase
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.work.ports import CreateWorkflowRun, CreateWorkItem
from codex_sdk_cli.application.workflows.commands import StartProcessToPublishUseCase
from codex_sdk_cli.domains.asr.ports import (
    AudioChunkCheckpoint,
    AudioTranscriptionSegment,
)
from codex_sdk_cli.domains.automation.ports import IncidentUpsert
from codex_sdk_cli.domains.work.models import (
    WorkExecutionMode,
    WorkflowStatus,
    WorkItemStatus,
)
from codex_sdk_cli.infra.asr.checkpoints import SqlAlchemyAsrChunkCheckpointRepository
from codex_sdk_cli.infra.automation.repository import (
    SqlAlchemyAutomationRepository,
    SqlAlchemySafeRemediator,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.models import WorkflowRunModel
from codex_sdk_cli.infra.work.scheduler import (
    SqlAlchemyPublishedPromptSnapshot,
    SqlAlchemyWorkflowCandidateReader,
)
from codex_sdk_cli.infra.work.transcript_execution import YouTubeTranscriptMetadataReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection


class EmptyChannels:
    async def list_scheduled_channels(self):
        return []


class UnexpectedChannels:
    async def list_scheduled_channels(self):
        raise AssertionError("scheduler must not read channels while draining")


class UnusedInlineRunner:
    async def run_inline(self, work_item_id: int):
        raise AssertionError(f"unexpected inline work {work_item_id}")


class RecordingEvents:
    def __init__(self) -> None:
        self.events: list[SchedulerEvent] = []

    async def record(self, event: SchedulerEvent) -> None:
        self.events.append(event)


class TimeoutExecutor(WorkExecutorPort):
    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        raise TimeoutError(f"temporary timeout for {context.work_item.id}")


def test_automation_openapi_paths_are_registered() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert "/ops/automation/status" in paths
    assert "/ops/automation/runtime/drain" in paths
    assert "/ops/automation/runtime/mark-stopped" in paths
    assert "/ops/automation/runtime/resume" in paths
    assert "/ops/incidents" in paths
    assert "/ops/incidents/{incident_id}/actions" in paths
    automation_status = schema["components"]["schemas"]["AutomationStatusResponse"]
    assert "dailyVideoQuota" in automation_status["properties"]
    properties = schema["components"]["schemas"]["ProcessToPublishOperationRequest"][
        "properties"
    ]
    assert {"microPromptVersionId", "timelinePromptVersionId", "transcriptFallback"} <= set(
        properties
    )
    assert properties["microModel"]["default"] == "gpt-5.6-sol"
    assert properties["microReasoningEffort"]["default"] == "high"
    assert properties["timelineModel"]["default"] == "gpt-5.6-luna"
    assert properties["timelineReasoningEffort"]["default"] == "xhigh"
    micro = schema["components"]["schemas"]["MicroEventOperationRequest"]["properties"]
    timeline = schema["components"]["schemas"]["TimelineOperationRequest"]["properties"]
    assert (micro["model"]["default"], micro["reasoningEffort"]["default"]) == (
        "gpt-5.6-sol",
        "high",
    )
    assert (timeline["model"]["default"], timeline["reasoningEffort"]["default"]) == (
        "gpt-5.6-luna",
        "xhigh",
    )
    fallback = schema["components"]["schemas"]["TranscriptFallbackRequest"]
    assert fallback["properties"]["recheckIntervalSeconds"]["default"] == 1800


def test_runtime_drain_blocks_claims_until_resumed(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_runtime_drain(migrated_database_path))


def test_runtime_transition_api_returns_conflict_until_drained(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_runtime_transition_api(migrated_database_path))


def test_asr_checkpoint_round_trip_updates_work_progress(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_checkpoint(migrated_database_path))


def test_supervisor_retries_transient_failure_with_backoff(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_supervisor(migrated_database_path))


def test_scheduler_enqueues_backfill_with_published_prompt_snapshot(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_scheduler_workflow(migrated_database_path))


def test_error_code_prevents_unsafe_persistence_retry() -> None:
    assert _permanently_unavailable(
        "ERROR: Video unavailable. This video has been removed by the uploader"
    )
    assert not _permanently_unavailable("temporary connection reset")
    assert not _is_transient(
        "transcript_collect",
        "transcript.persistence_failed",
        "YouTubeTranscriptPersistenceError",
        "connection closed while storing metadata",
    )
    assert _is_transient(
        "transcript_collect",
        "work.timed_out",
        "TimeoutError",
        "timed out",
    )
    assert not _is_transient(
        "asr_transcribe",
        "asr.audio_unavailable",
        "AsrAudioUnavailable",
        "connection text must not override a permanent error code",
    )


def test_orphan_video_is_excluded_reported_and_deduplicated(
    migrated_database_path: Path,
) -> None:
    connection = sqlite3.connect(migrated_database_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
            "published_at, created_at, is_embeddable) VALUES "
            "(65, 4, 'orphanvid65', 'Orphan', '', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1)"
        )
        connection.commit()
    finally:
        connection.close()

    asyncio.run(_exercise_orphan_quarantine(migrated_database_path))


def test_retry_remediation_resumes_linked_failed_workflow(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_retry_with_workflow(migrated_database_path))


def test_timeout_remediation_extends_existing_timeout(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_timeout_extension(migrated_database_path))


def test_work_item_action_without_work_item_returns_validation_error(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_invalid_incident_action(migrated_database_path))


async def _exercise_runtime_drain(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (1, 'Nagi', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@nagi', 'Nagi')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                    "published_at, created_at, is_embeddable) VALUES "
                    "(1, 1, 'abcdefghijk', 'Test', '', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1)"
                )
            )
            await session.commit()

        async with unit_of_work_factory() as unit_of_work:
            running_item, _ = await unit_of_work.work_items.get_or_create(
                _runtime_work_item("transcript_collect", "running", now)
            )
            pending_item, _ = await unit_of_work.work_items.get_or_create(
                _runtime_work_item("transcript_cue_generate", "pending", now)
            )
            inline_item, _ = await unit_of_work.work_items.get_or_create(
                _runtime_work_item(
                    "archive_publish",
                    "inline",
                    now,
                    execution_mode=WorkExecutionMode.INLINE,
                )
            )
            workflow, _ = await unit_of_work.workflows.create_or_get(
                CreateWorkflowRun(
                    workflow_type="process_to_publish",
                    workflow_version="v2",
                    video_id=1,
                    input_hash="runtime-drain-workflow",
                    options_json={},
                    available_at=now,
                )
            )
            claimed_item = await unit_of_work.work_items.claim_next(
                task_types=("transcript_collect",),
                worker_id="worker:running",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            claimed_workflow = await unit_of_work.workflows.claim_next(
                worker_id="coordinator:running",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            await unit_of_work.commit()
        assert claimed_item is not None and claimed_item.id == running_item.id
        assert claimed_workflow is not None and claimed_workflow.id == workflow.id

        repository = SqlAlchemyAutomationRepository(session_factory)
        drained = await RequestRuntimeDrainUseCase(repository, repository, now=lambda: now).execute(
            reason="test drain"
        )
        assert drained.mode == "draining"
        assert drained.running_work_item_count == 1
        assert drained.running_workflow_count == 1
        assert drained.ready_to_stop is False

        events = RecordingEvents()
        scheduler_result = await RunPipelineSchedulerTickUseCase(
            channels=UnexpectedChannels(),  # type: ignore[arg-type]
            collect_transcripts=CollectTranscriptsUseCase(
                videos=SqlAlchemyVideoSelection(session_factory),
                transcripts=YouTubeTranscriptMetadataReader(session_factory),
                unit_of_work_factory=unit_of_work_factory,
            ),
            unit_of_work_factory=unit_of_work_factory,
            inline_runner=UnusedInlineRunner(),  # type: ignore[arg-type]
            events=events,
            config=PipelineSchedulerConfig(
                channel_interval_seconds=21600,
                transcript_limit=5,
                no_transcript_recheck_interval_seconds=604800,
                no_transcript_limit=2,
            ),
            automation_state=repository,
        ).execute_once()
        assert scheduler_result.channel_count == 0
        assert [event.event_type for event in events.events] == [
            "pipeline_scheduler.tick_skipped"
        ]

        with pytest.raises(RuntimeNotDrained) as error:
            await MarkRuntimeStoppedUseCase(
                repository,
                repository,
                now=lambda: now,
            ).execute(reason="too early")
        assert error.value.descriptor.code == "pipeline.runtime_not_drained"

        async with unit_of_work_factory() as unit_of_work:
            assert (
                await unit_of_work.work_items.claim_next(
                    task_types=("transcript_cue_generate",),
                    worker_id="worker:blocked",
                    now=now,
                    lease_expires_at=now.replace(year=now.year + 1),
                )
                is None
            )
            assert (
                await unit_of_work.work_items.start_inline(
                    work_item_id=inline_item.id,
                    worker_id="inline:blocked",
                    now=now,
                    lease_expires_at=now.replace(year=now.year + 1),
                )
                is None
            )
            assert (
                await unit_of_work.workflows.claim_next(
                    worker_id="coordinator:blocked",
                    now=now,
                    lease_expires_at=now.replace(year=now.year + 1),
                )
                is None
            )
            assert await unit_of_work.work_items.heartbeat(
                work_item_id=running_item.id,
                worker_id="worker:running",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            assert await unit_of_work.workflows.heartbeat(
                workflow_run_id=workflow.id,
                worker_id="coordinator:running",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            await unit_of_work.work_items.mark_succeeded(
                work_item_id=running_item.id,
                now=now,
                output_json={"ok": True},
            )
            await unit_of_work.workflows.mark_succeeded(
                workflow_run_id=workflow.id,
                now=now,
                output_json={"ok": True},
            )
            await unit_of_work.commit()

        stopped = await MarkRuntimeStoppedUseCase(
            repository,
            repository,
            now=lambda: now,
        ).execute(reason="clean stop")
        assert stopped.mode == "stopped"
        assert stopped.ready_to_stop is True
        status = await repository.automation_status(now=now)
        assert status["runtime"] == {
            "state": "stopped",
            "drainRequestedAt": now.isoformat(),
            "drainReason": "clean stop",
            "runningWorkItemCount": 0,
            "runningWorkflowCount": 0,
            "runningByTaskType": [],
            "readyToStop": True,
        }

        resumed = await ResumeRuntimeUseCase(
            repository,
            repository,
            now=lambda: now,
        ).execute(reason="test resume")
        assert resumed.mode == "active"
        async with unit_of_work_factory() as unit_of_work:
            claimed_pending = await unit_of_work.work_items.claim_next(
                task_types=("transcript_cue_generate",),
                worker_id="worker:resumed",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            started_inline = await unit_of_work.work_items.start_inline(
                work_item_id=inline_item.id,
                worker_id="inline:resumed",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            await unit_of_work.commit()
        assert claimed_pending is not None and claimed_pending.id == pending_item.id
        assert started_inline is not None and started_inline.id == inline_item.id

        async with session_factory() as session:
            audit_events = list(
                await session.scalars(
                    text(
                        "SELECT event_type FROM operation_events "
                        "WHERE source = 'pipeline_runtime' ORDER BY id"
                    )
                )
            )
        assert audit_events == [
            "pipeline_runtime.drain_requested",
            "pipeline_runtime.stopped",
            "pipeline_runtime.resumed",
        ]
    finally:
        await engine.dispose()


async def _exercise_runtime_transition_api(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    repository = SqlAlchemyAutomationRepository(session_factory)
    now = datetime.now(UTC)
    try:
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type="micro_event_extract",
                    subject_type="video",
                    subject_id=None,
                    external_key="abcdefghijk",
                    task_version="v3",
                    input_hash="runtime-api-running",
                    idempotency_key="runtime-api-running",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=600,
                    input_json={"videoId": 1},
                    available_at=now,
                )
            )
            claimed = await unit_of_work.work_items.claim_next(
                task_types=("micro_event_extract",),
                worker_id="worker:api-test",
                now=now,
                lease_expires_at=now.replace(year=now.year + 1),
            )
            await unit_of_work.commit()
        assert claimed is not None

        test_app = create_app()
        test_app.dependency_overrides[get_automation_repository] = lambda: repository
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            drained = await client.post(
                "/ops/automation/runtime/drain",
                json={"reason": "api test"},
            )
            assert drained.status_code == 200, drained.text
            assert drained.json()["state"] == "draining"

            rejected = await client.post(
                "/ops/automation/runtime/mark-stopped",
                json={"reason": "too early"},
            )
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["error"]["code"] == "pipeline.runtime_not_drained"

            async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
                await unit_of_work.work_items.mark_succeeded(
                    work_item_id=item.id,
                    now=now,
                    output_json={"ok": True},
                )
                await unit_of_work.commit()

            stopped = await client.post(
                "/ops/automation/runtime/mark-stopped",
                json={"reason": "api test complete"},
            )
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["state"] == "stopped"
            status = await client.get("/ops/automation/status")
            assert status.status_code == 200, status.text
            assert status.json()["runtime"]["readyToStop"] is True
            resumed = await client.post(
                "/ops/automation/runtime/resume",
                json={"reason": "api test resume"},
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["state"] == "active"
    finally:
        await engine.dispose()


def _runtime_work_item(
    task_type: str,
    key: str,
    now: datetime,
    *,
    execution_mode: WorkExecutionMode = WorkExecutionMode.WORKER,
) -> CreateWorkItem:
    return CreateWorkItem(
        task_type=task_type,
        subject_type="video",
        subject_id=1,
        external_key="abcdefghijk",
        task_version="v1",
        input_hash=key,
        idempotency_key=f"runtime:{task_type}:{key}",
        execution_mode=execution_mode,
        timeout_seconds=600,
        input_json={"videoId": 1},
        available_at=now,
    )


async def _exercise_checkpoint(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    try:
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type="asr_transcribe",
                    subject_type="video",
                    subject_id=None,
                    external_key="abcdefghijk",
                    task_version="v1",
                    input_hash="a" * 64,
                    idempotency_key="test:asr:checkpoint",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=64800,
                    input_json={"videoId": 1},
                    available_at=datetime.now(UTC),
                )
            )
            await unit_of_work.commit()
        checkpoints = SqlAlchemyAsrChunkCheckpointRepository(
            session_factory,
            work_item_id=item.id,
        )
        await checkpoints.save(
            AudioChunkCheckpoint(
                chunk_index=2,
                segments=(
                    AudioTranscriptionSegment(
                        text="테스트",
                        start_seconds=1.5,
                        end_seconds=2.5,
                    ),
                ),
                device="cuda",
                compute_type="int8_float16",
            )
        )
        loaded = await checkpoints.load(2)
        assert loaded is not None and loaded.segments[0].text == "테스트"
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            progressed = await unit_of_work.work_items.get(item.id)
        assert progressed is not None
        assert progressed.output_json == {
            "completedChunkCount": 3,
            "lastCompletedChunkIndex": 2,
            "device": "cuda",
            "computeType": "int8_float16",
        }
    finally:
        await engine.dispose()


async def _exercise_supervisor(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    now = datetime.now(UTC)
    try:
        async with unit_of_work_factory() as unit_of_work:
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type="micro_event_extract",
                    subject_type="video",
                    subject_id=None,
                    external_key="abcdefghijk",
                    task_version="v3",
                    input_hash="b" * 64,
                    idempotency_key="test:supervisor:retry",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=60,
                    input_json={"videoId": 1},
                    available_at=now,
                )
            )
            await unit_of_work.commit()
        execution = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {"micro_event_extract": lambda: TimeoutExecutor()}
            ),
            task_types=("micro_event_extract",),
            worker_id="automation:test",
        )
        failed = await execution.run_once_with_result()
        assert failed.succeeded is False

        repository = SqlAlchemyAutomationRepository(session_factory)
        result = await RunPipelineSupervisorUseCase(
            reader=repository,
            incidents=repository,
            remediator=SqlAlchemySafeRemediator(session_factory),
            now=lambda: now,
        ).execute_once()
        assert result["automaticRetryCount"] == 1
        incidents = await repository.list_incidents(state="acknowledged", limit=10)
        assert len(incidents) == 1
        async with unit_of_work_factory() as unit_of_work:
            retried = await unit_of_work.work_items.get(item.id)
        assert retried is not None and retried.status is WorkItemStatus.PENDING
        available_at = retried.available_at
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        assert available_at > now
    finally:
        await engine.dispose()


async def _exercise_scheduler_workflow(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (1, 'Nagi', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@nagi', 'Nagi')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                    "published_at, created_at, is_embeddable) VALUES "
                    "(1, 1, 'abcdefghijk', 'Test', '', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1)"
                )
            )
            for prompt_id, key in ((10, "micro_event_extract"), (11, "timeline_compose")):
                await session.execute(
                    text(
                        "INSERT INTO prompt_versions "
                        "(id, prompt_key, version_label, body, body_sha256, status, published_at) "
                        "VALUES (:id, :key, :label, 'body', :sha, 'PUBLISHED', CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": prompt_id,
                        "key": key,
                        "label": f"{key}-prod",
                        "sha": str(prompt_id) * 64,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO prompt_active_versions(prompt_key, version_id) "
                        "VALUES (:key, :id)"
                    ),
                    {"key": key, "id": prompt_id},
                )
            await session.commit()

        selection = SqlAlchemyVideoSelection(session_factory)
        repository = SqlAlchemyAutomationRepository(session_factory)
        result = await RunPipelineSchedulerTickUseCase(
            channels=EmptyChannels(),  # type: ignore[arg-type]
            collect_transcripts=CollectTranscriptsUseCase(
                videos=selection,
                transcripts=YouTubeTranscriptMetadataReader(session_factory),
                unit_of_work_factory=unit_of_work_factory,
            ),
            unit_of_work_factory=unit_of_work_factory,
            inline_runner=UnusedInlineRunner(),  # type: ignore[arg-type]
            events=RecordingEvents(),
            config=PipelineSchedulerConfig(
                channel_interval_seconds=21600,
                transcript_limit=5,
                no_transcript_recheck_interval_seconds=604800,
                no_transcript_limit=2,
            ),
            start_workflows=StartProcessToPublishUseCase(
                videos=selection,
                unit_of_work_factory=unit_of_work_factory,
            ),
            workflow_candidates=SqlAlchemyWorkflowCandidateReader(session_factory),
            automation_state=repository,
            prompts=SqlAlchemyPublishedPromptSnapshot(session_factory),
        ).execute_once()
        assert result.workflow_enqueued_count == 1
        async with session_factory() as session:
            workflow = await session.scalar(select(WorkflowRunModel))
        assert workflow is not None
        assert workflow.workflow_version == "v2"
        assert workflow.options_json["micro_model"] == "gpt-5.6-sol"
        assert workflow.options_json["micro_reasoning_effort"] == "high"
        assert workflow.options_json["timeline_model"] == "gpt-5.6-luna"
        assert workflow.options_json["timeline_reasoning_effort"] == "xhigh"
        assert workflow.options_json["micro_prompt_version_id"] == 10
        assert workflow.options_json["timeline_prompt_version_id"] == 11
        assert workflow.options_json["automation_mode"] == "backfill"
        observed_at = datetime(2027, 1, 1, tzinfo=UTC)
        assert await repository.sla_breaches(now=observed_at, limit=10) == []
        incident = await repository.upsert(
            IncidentUpsert(
                fingerprint="backfill-sla-test",
                incident_type="sla_breach",
                severity="error",
                work_item_id=None,
                workflow_run_id=workflow.id,
                task_type="micro_event_extract",
                error_type="SlaDeadlineExceeded",
                error_message="Backfill SLA should be ignored.",
                metadata_json={},
                seen_at=observed_at,
            )
        )
        assert await repository.resolve_backfill_sla(now=observed_at) == 1
        resolved = await repository.get(incident.id)
        assert resolved is not None and resolved.state == "resolved"
    finally:
        await engine.dispose()


async def _exercise_orphan_quarantine(database_path: Path) -> None:
    now = datetime.now(UTC)
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    repository = SqlAlchemyAutomationRepository(session_factory)
    try:
        state = await repository.get_state(now=now)
        candidates = await SqlAlchemyWorkflowCandidateReader(
            session_factory
        ).list_candidates(state=state, limit=10)
        assert candidates == []
        assert [item.video_id for item in await repository.orphan_videos(limit=10)] == [65]
        status = await repository.automation_status(now=now)
        assert status["dataIntegrity"] == {"orphanVideoCount": 1}

        supervisor = RunPipelineSupervisorUseCase(
            reader=repository,
            incidents=repository,
            remediator=SqlAlchemySafeRemediator(session_factory),
            now=lambda: now,
        )
        await supervisor.execute_once()
        await supervisor.execute_once()
        incidents = await repository.list_incidents(state="open", limit=10)
        assert len(incidents) == 1
        incident = incidents[0]
        assert incident.incident_type == "data_integrity"
        assert incident.error_type == "OrphanVideoChannelMissing"
        assert incident.metadata_json["errorCode"] == "pipeline.orphan_video_channel"
        assert incident.metadata_json["videoId"] == 65
        assert incident.occurrence_count == 2

        await repository.mark_steady(now=now)
        assert (await repository.get_state(now=now)).mode == "steady"
    finally:
        await engine.dispose()


async def _exercise_retry_with_workflow(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (1, 'Nagi', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@nagi', 'Nagi')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                    "published_at, created_at, is_embeddable) VALUES "
                    "(1, 1, 'abcdefghijk', 'Test', '', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1)"
                )
            )
            await session.commit()
        async with unit_of_work_factory() as unit_of_work:
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type="transcript_collect",
                    subject_type="video",
                    subject_id=1,
                    external_key="abcdefghijk",
                    task_version="v1",
                    input_hash="c" * 64,
                    idempotency_key="test:retry:workflow",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=60,
                    input_json={"videoId": 1},
                    available_at=now,
                )
            )
            workflow, _ = await unit_of_work.workflows.create_or_get(
                CreateWorkflowRun(
                    workflow_type="process_to_publish",
                    workflow_version="v2",
                    video_id=1,
                    input_hash="d" * 64,
                    options_json={"automation_mode": "backfill"},
                    available_at=now,
                )
            )
            await unit_of_work.workflows.add_step(
                workflow_run_id=workflow.id,
                stage_name="transcript_collect",
                position=0,
                work_item_id=item.id,
                status="failed",
            )
            await unit_of_work.workflows.mark_failed(
                workflow_run_id=workflow.id,
                error_code="transcript.persistence_failed",
                error_message="Transcript metadata persistence failed.",
                blocked=False,
                now=now,
            )
            claimed = await unit_of_work.work_items.claim_next(
                task_types=("transcript_collect",),
                worker_id="worker:test",
                now=now,
                lease_expires_at=now,
            )
            assert claimed is not None
            await unit_of_work.work_items.mark_failed(
                work_item_id=item.id,
                now=now,
                error_code="transcript.persistence_failed",
                error_type="TranscriptPersistenceUnavailable",
                error_message="Transcript metadata persistence failed.",
                timed_out=False,
            )
            await unit_of_work.commit()

        result = await SqlAlchemySafeRemediator(session_factory).execute(
            action="retry",
            work_item_id=item.id,
            parameters={"delaySeconds": 0},
            now=now,
        )

        assert result["workflowRunIds"] == [workflow.id]
        async with unit_of_work_factory() as unit_of_work:
            retried_item = await unit_of_work.work_items.get(item.id)
            retried_workflow = await unit_of_work.workflows.get(workflow.id)
        assert retried_item is not None
        assert retried_item.status is WorkItemStatus.PENDING
        assert retried_workflow is not None
        assert retried_workflow.status is WorkflowStatus.PENDING
        assert retried_workflow.error_code is None
        assert retried_workflow.options_json["retry_failed"] is False
    finally:
        await engine.dispose()


async def _exercise_timeout_extension(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    now = datetime.now(UTC)
    try:
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type="micro_event_extract",
                    subject_type="video",
                    subject_id=None,
                    external_key="timeout-extension",
                    task_version="v3",
                    input_hash="timeout-extension",
                    idempotency_key="test:timeout-extension",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=3600,
                    input_json={"videoId": 1},
                    available_at=now,
                )
            )
            await unit_of_work.commit()

        result = await SqlAlchemySafeRemediator(session_factory).execute(
            action="extend_timeout",
            work_item_id=item.id,
            parameters={"extensionSeconds": 1800},
            now=now,
        )

        assert result == {"workItemId": item.id, "timeoutSeconds": 5400}
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            extended = await unit_of_work.work_items.get(item.id)
        assert extended is not None and extended.timeout_seconds == 5400
    finally:
        await engine.dispose()


async def _exercise_invalid_incident_action(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    repository = SqlAlchemyAutomationRepository(session_factory)
    now = datetime.now(UTC)
    try:
        incident = await repository.upsert(
            IncidentUpsert(
                fingerprint="incident-without-work-item",
                incident_type="data_integrity",
                severity="error",
                work_item_id=None,
                workflow_run_id=None,
                task_type=None,
                error_type="OrphanVideoChannelMissing",
                error_message="Video references a missing channel.",
                metadata_json={"videoId": 1},
                seen_at=now,
            )
        )
        use_case = ExecuteIncidentActionUseCase(
            repository,
            SqlAlchemySafeRemediator(session_factory),
            now=lambda: now,
        )
        test_app = create_app()
        test_app.dependency_overrides[get_execute_incident_action_use_case] = lambda: use_case
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/ops/incidents/{incident.id}/actions",
                json={
                    "action": "retry",
                    "parameters": {},
                    "idempotencyKey": "invalid-without-work-item",
                },
            )

        assert response.status_code == 422, response.text
        assert response.json()["error"] == {
            "code": "automation.incident_action_not_allowed",
            "message": "The incident action requires a linked work item.",
            "details": {"incidentId": incident.id, "action": "retry"},
        }
    finally:
        await engine.dispose()
