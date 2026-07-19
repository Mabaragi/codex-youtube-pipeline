from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.domains.codex_usage.ports import CodexUsageCreate, CodexUsageRecorderPort
from codex_sdk_cli.domains.evaluation.ports import EvaluationObjectStorePort, JsonObject
from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent, LlmTraceRecorderPort

from .models import EvaluationArtifactModel, EvaluationUsageModel
from .repository import SqlAlchemyEvaluationRepository, _stable_id


class EvaluationUsageRecorder(CodexUsageRecorderPort):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        run_id: str,
        attempt_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._run_id = run_id
        self._attempt_id = attempt_id
        self._sequence = 0

    @override
    async def record_usage(self, usage: CodexUsageCreate) -> None:
        self._sequence += 1
        async with self._session_factory() as session:
            session.add(
                EvaluationUsageModel(
                    id=_stable_id(
                        "usage",
                        self._attempt_id,
                        str(self._sequence),
                    ),
                    run_id=self._run_id,
                    attempt_id=self._attempt_id,
                    source=usage.source,
                    operation=usage.operation,
                    phase=_usage_phase(usage),
                    window_index=usage.window_index,
                    model=usage.model,
                    reasoning_effort=usage.reasoning_effort,
                    status=usage.status,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    reasoning_output_tokens=usage.reasoning_output_tokens,
                    duration_ms=usage.duration_ms,
                    usage_json=usage.usage_json,
                    error_type=usage.error_type,
                    error_message=usage.error_message,
                )
            )
            await session.commit()


class RequiredEvaluationTraceRecorder(LlmTraceRecorderPort):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        objects: EvaluationObjectStorePort,
        experiment_id: str,
        run_id: str,
        attempt_id: str,
        attempt_no: int,
    ) -> None:
        self._session_factory = session_factory
        self._objects = objects
        self._experiment_id = experiment_id
        self._run_id = run_id
        self._attempt_id = attempt_id
        self._attempt_no = attempt_no
        self._sequence = 0

    @override
    async def record_event(self, event: LlmTraceEvent) -> None:
        self._sequence += 1
        payload = cast(JsonObject, _jsonable(asdict(event)))
        stored = await self._objects.put_json(
            key=(
                f"experiments/{self._experiment_id}/runs/{self._run_id}/attempts/"
                f"{self._attempt_no}/traces/{self._sequence:05d}-{event.phase}.json"
            ),
            payload=payload,
        )
        async with self._session_factory() as session:
            existing = await session.get(
                EvaluationArtifactModel,
                _stable_id("artifact", self._experiment_id, stored.key),
            )
            if existing is None:
                session.add(
                    EvaluationArtifactModel(
                        id=_stable_id("artifact", self._experiment_id, stored.key),
                        experiment_id=self._experiment_id,
                        run_id=self._run_id,
                        kind="llm-trace",
                        object_key=stored.key,
                        sha256=stored.sha256,
                        byte_size=stored.byte_size,
                    )
                )
            await session.commit()


class EvaluationCheckpointWriter:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        objects: EvaluationObjectStorePort,
        engine: AsyncEngine,
        experiment_id: str,
        run_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._objects = objects
        self._engine = engine
        self._experiment_id = experiment_id
        self._run_id = run_id

    async def write(self, *, window_index: int, payload: JsonObject, status: str) -> None:
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        key = (
            f"experiments/{self._experiment_id}/runs/{self._run_id}/"
            f"checkpoints/window-{window_index:05d}/{digest}.json"
        )
        stored = await self._objects.put_json(key=key, payload=payload)
        async with self._session_factory() as session:
            repository = SqlAlchemyEvaluationRepository(session=session, engine=self._engine)
            await repository.upsert_checkpoint(
                run_id=self._run_id,
                checkpoint_key=f"micro-window-{window_index}",
                status=status,
                payload=payload,
                stored=stored,
            )
            await repository.commit()


def _usage_phase(usage: CodexUsageCreate) -> str:
    if usage.operation == "repair_window":
        return "repair"
    if usage.operation == "repair_episode":
        return "repair"
    return "generation"


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)
