from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.domains.domain_knowledge.ports import DomainKnowledgeRepositoryPort
from codex_sdk_cli.domains.evaluation.ports import (
    EvaluationGenerationResult,
    EvaluationGeneratorPort,
    EvaluationObjectStorePort,
    JsonObject,
)
from codex_sdk_cli.domains.micro_events.constants import (
    MICRO_EVENT_EXTRACT_TASK_NAME,
    MICRO_EVENT_EXTRACT_TASK_VERSION,
)
from codex_sdk_cli.domains.micro_events.ports import MicroEventExtractionRepositoryPort
from codex_sdk_cli.domains.micro_events.schemas import MicroEventExtractRequest
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobRepositoryPort
from codex_sdk_cli.domains.prompts.constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.timelines.ports import CopyStyle, TimelineCompositionRepositoryPort
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRepositoryPort
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord, VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRepositoryPort
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptRepositoryPort
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime
from codex_sdk_cli.infra.micro_events.extractor import CodexMicroEventExtractor
from codex_sdk_cli.infra.timelines.composer import CodexTimelineComposer
from codex_sdk_cli.settings import CliSettings

from .memory import (
    MemoryMicroEventRepository,
    MemoryPipelineJobRepository,
    MemoryTimelineRepository,
    MemoryVideoTaskRepository,
    NoopEvaluationEventRecorder,
    SnapshotChannelRepository,
    SnapshotCueRepository,
    SnapshotDomainKnowledgeRepository,
    SnapshotPromptResolver,
    SnapshotStreamerRepository,
    SnapshotTranscriptRepository,
    SnapshotVideoRepository,
    micro_detail_from_json,
    resolved_prompt,
    snapshot_records,
    window_create_from_json,
)
from .recording import (
    EvaluationCheckpointWriter,
    EvaluationUsageRecorder,
    RequiredEvaluationTraceRecorder,
)
from .repository import SqlAlchemyEvaluationRepository


class EvaluationGenerationService(EvaluationGeneratorPort):
    def __init__(
        self,
        *,
        settings: CliSettings,
        session_factory: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
        objects: EvaluationObjectStorePort,
        runtime_client_factory: Callable[[], CodexRuntimePort] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._engine = engine
        self._objects = objects
        self._runtime_client_factory = runtime_client_factory or (
            lambda: CodexRuntimeClient(self._settings)
        )

    @override
    async def generate(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
        resume: bool,
    ) -> EvaluationGenerationResult:
        stage = _str(run, "stage")
        if stage == "micro":
            output = await self._generate_micro(
                experiment_id=experiment_id,
                run=run,
                snapshot=snapshot,
                resume=resume,
            )
        elif stage == "timeline":
            output = await self._generate_timeline(
                experiment_id=experiment_id,
                run=run,
                snapshot=snapshot,
            )
        else:
            raise ValueError(f"Unsupported evaluation stage: {stage}")
        return EvaluationGenerationResult(output=output, artifacts=[])

    async def _generate_micro(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
        resume: bool,
    ) -> JsonObject:
        video, channel, streamer, transcript, cues, domain = snapshot_records(snapshot)
        task_id = _int(run, "runNo")
        tasks = MemoryVideoTaskRepository(video=video, task_id=task_id, resume=resume)
        checkpoints = await self._checkpoints(_str(run, "runId"))
        if resume and checkpoints:
            tasks.seed_source(_resume_task(task_id, video.id))
        checkpoint_writer = EvaluationCheckpointWriter(
            session_factory=self._session_factory,
            objects=self._objects,
            engine=self._engine,
            experiment_id=experiment_id,
            run_id=_str(run, "runId"),
        )
        micro_events = MemoryMicroEventRepository(
            video=video,
            tasks=tasks,
            checkpoint_writer=checkpoint_writer,
        )
        if resume:
            windows = [
                window_create_from_json(cast(JsonObject, item["payload"]))
                for item in checkpoints
                if item.get("payload") is not None
            ]
            if windows:
                micro_events.seed_windows(task_id, windows)
        config = _dict(run, "candidateConfig")
        model = cast(CodexModelChoice, config["model"])
        reasoning_effort = cast(ReasoningEffortChoice, config["reasoningEffort"])
        prompts = _dict(snapshot, "prompts")
        micro_prompts = _dict(prompts, "micro")
        prompt = resolved_prompt(_dict(micro_prompts, _str(run, "candidateKey")))
        runtime = self._runtime(run)
        use_case = ExtractVideoMicroEventsUseCase(
            videos=cast(VideoRepositoryPort, SnapshotVideoRepository(video)),
            video_tasks=cast(VideoTaskRepositoryPort, tasks),
            transcripts=cast(
                YouTubeTranscriptRepositoryPort,
                SnapshotTranscriptRepository(transcript),
            ),
            transcript_cues=cast(TranscriptCueRepositoryPort, SnapshotCueRepository(cues)),
            channels=cast(ChannelRepositoryPort, SnapshotChannelRepository(channel)),
            streamers=cast(StreamerRepositoryPort, SnapshotStreamerRepository(streamer)),
            domain_knowledge=cast(
                DomainKnowledgeRepositoryPort,
                SnapshotDomainKnowledgeRepository(domain),
            ),
            pipeline_jobs=cast(PipelineJobRepositoryPort, MemoryPipelineJobRepository()),
            micro_events=cast(MicroEventExtractionRepositoryPort, micro_events),
            extractor=CodexMicroEventExtractor(
                runtime,
                model=model,
                reasoning_effort=reasoning_effort,
            ),
            prompt_resolver=SnapshotPromptResolver({MICRO_EVENT_EXTRACT_PROMPT_KEY: prompt}),
            timeout_seconds=self._settings.micro_event_extract_timeout_seconds,
            concurrency_limit=_int(run, "microWindowConcurrency"),
            model=model,
            reasoning_effort=reasoning_effort,
            events=NoopEvaluationEventRecorder(),
            llm_traces=self._traces(experiment_id, run),
        )
        response = await use_case.execute(
            video.id,
            MicroEventExtractRequest(
                retryFailed=resume,
                regenerateSucceeded=False,
                windowMinutes=_object_int(config["windowMinutes"]),
                overlapMinutes=_object_int(config["overlapMinutes"]),
                model=model,
                reasoningEffort=reasoning_effort,
                includeNonEmbeddable=True,
            ),
        )
        if response.status != "succeeded":
            raise RuntimeError(
                response.error_message or f"Micro evaluation ended as {response.status}."
            )
        detail = await micro_events.get_extraction(video_id=video.id, video_task_id=task_id)
        if detail is None:
            raise RuntimeError("Micro evaluation did not produce a normalized result.")
        return {
            "version": 1,
            "stage": "micro",
            "response": response.model_dump(mode="json", by_alias=True),
            "detail": cast(JsonObject, _jsonable(asdict(detail))),
        }

    async def _generate_timeline(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
    ) -> JsonObject:
        video, channel, streamer, _transcript, _cues, domain = snapshot_records(snapshot)
        task_id = _int(run, "runNo")
        source_task_id = _int(run, "sourceMicroRunNo")
        source_key = _str(run, "sourceMicroResultObjectKey")
        source_payload = await self._objects.get_json(key=source_key)
        source_detail = micro_detail_from_json(_dict(source_payload, "detail"))
        tasks = MemoryVideoTaskRepository(video=video, task_id=task_id, resume=False)
        tasks.seed_source(_source_task(source_task_id, video.id, source_detail.transcript_id))
        micro_events = MemoryMicroEventRepository(video=video, tasks=tasks)
        micro_events.seed_detail(source_task_id, source_detail)
        timelines = MemoryTimelineRepository(video=video)
        config = _dict(run, "candidateConfig")
        model = cast(CodexModelChoice, config["model"])
        reasoning_effort = cast(ReasoningEffortChoice, config["reasoningEffort"])
        copy_style = cast(CopyStyle, config["copyStyle"])
        prompts = _dict(snapshot, "prompts")
        timeline_prompts = _dict(prompts, "timeline")
        compose_prompt = resolved_prompt(_dict(timeline_prompts, _str(run, "candidateKey")))
        repair_prompt = resolved_prompt(_dict(prompts, "timelineRepair"))
        runtime = self._runtime(run)
        use_case = ComposeTimelineUseCase(
            videos=cast(VideoRepositoryPort, SnapshotVideoRepository(video)),
            video_tasks=cast(VideoTaskRepositoryPort, tasks),
            channels=cast(ChannelRepositoryPort, SnapshotChannelRepository(channel)),
            streamers=cast(StreamerRepositoryPort, SnapshotStreamerRepository(streamer)),
            domain_knowledge=cast(
                DomainKnowledgeRepositoryPort,
                SnapshotDomainKnowledgeRepository(domain),
            ),
            micro_events=cast(MicroEventExtractionRepositoryPort, micro_events),
            timelines=cast(TimelineCompositionRepositoryPort, timelines),
            pipeline_jobs=cast(PipelineJobRepositoryPort, MemoryPipelineJobRepository()),
            composer=CodexTimelineComposer(
                runtime,
                model=model,
                reasoning_effort=reasoning_effort,
            ),
            prompt_resolver=SnapshotPromptResolver(
                {
                    TIMELINE_COMPOSE_PROMPT_KEY: compose_prompt,
                    TIMELINE_EPISODE_REPAIR_PROMPT_KEY: repair_prompt,
                }
            ),
            timeout_seconds=self._settings.timeline_compose_timeout_seconds,
            model=model,
            reasoning_effort=reasoning_effort,
            events=NoopEvaluationEventRecorder(),
            llm_traces=self._traces(experiment_id, run),
        )
        enqueued = await use_case.enqueue(
            TimelineComposeEnqueueRequest(
                target="selected_videos",
                videoIds=[video.id],
                limit=1,
                model=model,
                reasoningEffort=reasoning_effort,
                copyStyle=copy_style,
                includeNonEmbeddable=True,
            )
        )
        if not enqueued.items or enqueued.items[0].video_task_id is None:
            message = enqueued.items[0].error_message if enqueued.items else None
            raise RuntimeError(message or "Timeline evaluation could not be enqueued.")
        claimed = await tasks.claim_pending_task(task_id, worker_id="evaluation-cli")
        if claimed is None:
            raise RuntimeError("Timeline evaluation task could not be claimed.")
        response = await use_case.execute_claimed_task(claimed, worker_id="evaluation-cli")
        detail = await timelines.get_composition(video_id=video.id, video_task_id=task_id)
        if detail is None:
            raise RuntimeError("Timeline evaluation did not produce a normalized result.")
        return {
            "version": 1,
            "stage": "timeline",
            "sourceMicroRunId": run.get("sourceMicroRunId"),
            "response": response.model_dump(mode="json", by_alias=True),
            "detail": cast(JsonObject, _jsonable(asdict(detail))),
        }

    def _runtime(self, run: JsonObject) -> RecordingCodexRuntime:
        return RecordingCodexRuntime(
            self._runtime_client_factory(),
            EvaluationUsageRecorder(
                session_factory=self._session_factory,
                run_id=_str(run, "runId"),
                attempt_id=_str(run, "attemptId"),
            ),
        )

    async def _checkpoints(self, run_id: str) -> list[JsonObject]:
        async with self._session_factory() as session:
            repository = SqlAlchemyEvaluationRepository(session=session, engine=self._engine)
            return await repository.checkpoints(run_id)

    def _traces(self, experiment_id: str, run: JsonObject) -> RequiredEvaluationTraceRecorder:
        return RequiredEvaluationTraceRecorder(
            session_factory=self._session_factory,
            objects=self._objects,
            experiment_id=experiment_id,
            run_id=_str(run, "runId"),
            attempt_id=_str(run, "attemptId"),
            attempt_no=_int(run, "attemptNo"),
        )


def _resume_task(task_id: int, video_id: int) -> VideoTaskRecord:
    return VideoTaskRecord(
        id=task_id,
        video_id=video_id,
        task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
        task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
        input_hash="evaluation-resume",
        status="failed",
        worker_id=None,
        timeout_seconds=1,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=None,
        output_json=None,
        error_type="InterruptedProcess",
        error_message="Resuming evaluation checkpoints.",
        started_at=None,
        completed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _source_task(task_id: int, video_id: int, transcript_id: int | None) -> VideoTaskRecord:
    now = datetime.now(UTC)
    return VideoTaskRecord(
        id=task_id,
        video_id=video_id,
        task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
        task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
        input_hash="selected-evaluation-micro",
        status="succeeded",
        worker_id="evaluation-cli",
        timeout_seconds=1,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=transcript_id,
        output_json={"evaluation": True},
        error_type=None,
        error_message=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _str(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing evaluation run string: {key}")
    return value


def _int(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Missing evaluation run integer: {key}")
    return value


def _dict(payload: JsonObject, key: str) -> JsonObject:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing evaluation object: {key}")
    return cast(JsonObject, value)


def _object_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Evaluation candidate integer configuration is invalid.")
    return value
