from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .schemas import EvaluationPlan, EvaluationStage

JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class EvaluationStoredObject:
    key: str
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class EvaluationGenerationResult:
    output: JsonObject
    artifacts: list[EvaluationStoredObject]


class EvaluationObjectStorePort(Protocol):
    async def put_json(self, *, key: str, payload: JsonObject) -> EvaluationStoredObject: ...

    async def get_json(self, *, key: str) -> JsonObject: ...

    async def stat(self, *, key: str) -> EvaluationStoredObject | None: ...


class EvaluationSnapshotterPort(Protocol):
    async def snapshot_plan_inputs(
        self,
        *,
        experiment_id: str,
        plan: EvaluationPlan,
    ) -> list[JsonObject]: ...


class EvaluationGeneratorPort(Protocol):
    async def generate(
        self,
        *,
        experiment_id: str,
        run: JsonObject,
        snapshot: JsonObject,
        resume: bool,
    ) -> EvaluationGenerationResult: ...


class EvaluationRepositoryPort(Protocol):
    async def commit(self) -> None: ...

    async def create_experiment(
        self,
        *,
        experiment_id: str,
        plan: EvaluationPlan,
        plan_hash: str,
        snapshots: list[tuple[JsonObject, EvaluationStoredObject]],
    ) -> JsonObject: ...

    async def get_experiment_by_key(self, experiment_key: str) -> JsonObject | None: ...

    async def get_experiment(self, experiment_id: str) -> JsonObject | None: ...

    async def list_stage_runs(
        self, experiment_id: str, stage: EvaluationStage
    ) -> list[JsonObject]: ...

    async def prepare_run_attempt(self, run_id: str, *, resume: bool) -> JsonObject: ...

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        output: JsonObject | None,
        artifacts: list[EvaluationStoredObject],
        error: Exception | None,
    ) -> None: ...

    async def selected_micro_run(self, experiment_id: str, video_id: int) -> JsonObject | None: ...

    async def import_scores(self, experiment_id: str, payload: JsonObject) -> JsonObject: ...

    async def select_micro(self, experiment_id: str, payload: JsonObject) -> JsonObject: ...

    async def status(self, experiment_id: str) -> JsonObject: ...

    async def report(self, experiment_id: str, *, unblind: bool) -> JsonObject: ...

    async def record_artifact(
        self,
        *,
        run_id: str | None,
        kind: str,
        stored: EvaluationStoredObject,
    ) -> None: ...

    async def artifacts(self, experiment_id: str) -> list[JsonObject]: ...

    async def acquire_experiment_lock(self, experiment_id: str) -> bool: ...

    async def release_experiment_lock(self, experiment_id: str) -> None: ...
