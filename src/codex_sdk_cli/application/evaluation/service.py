from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

from codex_sdk_cli.domains.evaluation.ports import (
    EvaluationGeneratorPort,
    EvaluationObjectStorePort,
    EvaluationRepositoryPort,
    EvaluationSnapshotterPort,
    EvaluationStoredObject,
)
from codex_sdk_cli.domains.evaluation.schemas import (
    RUBRIC_KEYS_BY_VERSION,
    EvaluationPlan,
    EvaluationScoreImport,
    EvaluationStage,
    MicroSelectionImport,
)

JsonObject = dict[str, object]


class EvaluationError(Exception):
    """Base error for evaluation orchestration."""


class EvaluationNotFound(EvaluationError):
    """Raised when an experiment does not exist."""


class EvaluationConflict(EvaluationError):
    """Raised when immutable evaluation state conflicts."""


class EvaluationService:
    def __init__(
        self,
        *,
        repository: EvaluationRepositoryPort,
        objects: EvaluationObjectStorePort,
        snapshotter: EvaluationSnapshotterPort,
        generator: EvaluationGeneratorPort,
    ) -> None:
        self._repository = repository
        self._objects = objects
        self._snapshotter = snapshotter
        self._generator = generator

    async def create(self, plan: EvaluationPlan) -> JsonObject:
        plan_json = plan.model_dump(mode="json", by_alias=True)
        plan_hash = _json_sha256(plan_json)
        existing = await self._repository.get_experiment_by_key(plan.experiment_key)
        if existing is not None:
            if existing.get("planHash") != plan_hash:
                raise EvaluationConflict(
                    "experimentKey already exists with a different evaluation plan."
                )
            return {**existing, "created": False}

        experiment_id = _stable_experiment_id(plan.experiment_key, plan_hash)
        snapshot_payloads = await self._snapshotter.snapshot_plan_inputs(
            experiment_id=experiment_id,
            plan=plan,
        )
        resolved_plan = _pin_prompt_versions(plan, snapshot_payloads)
        snapshots: list[tuple[JsonObject, EvaluationStoredObject]] = []
        for payload in snapshot_payloads:
            video_id = _required_int(payload, "videoId")
            stored = await self._objects.put_json(
                key=(
                    f"experiments/{experiment_id}/snapshots/video-{video_id}/"
                    f"{_json_sha256(payload)}.json"
                ),
                payload=payload,
            )
            snapshots.append((payload, stored))
        result = await self._repository.create_experiment(
            experiment_id=experiment_id,
            plan=resolved_plan,
            plan_hash=plan_hash,
            snapshots=snapshots,
        )
        await self._repository.commit()
        return {**result, "created": True}

    async def run(
        self,
        *,
        experiment_id: str,
        stage: EvaluationStage,
        resume: bool,
    ) -> JsonObject:
        await self._require_experiment(experiment_id)
        if not await self._repository.acquire_experiment_lock(experiment_id):
            raise EvaluationConflict("Another evaluation process owns this experiment.")
        results_by_run: dict[str, JsonObject] = {}
        run_order: list[str] = []
        try:
            runs = await self._repository.list_stage_runs(experiment_id, stage)
            prepared_attempts: list[JsonObject] = []
            for run in runs:
                run_id = _required_str(run, "runId")
                run_order.append(run_id)
                current_status = str(run.get("status") or "")
                if current_status == "succeeded":
                    results_by_run[run_id] = _run_summary(run, reused=True)
                    continue
                retryable_statuses = {"pending", "failed", "abandoned"}
                if resume:
                    retryable_statuses.add("running")
                if current_status not in retryable_statuses:
                    results_by_run[run_id] = _run_summary(run, reused=False)
                    continue
                if current_status in {"failed", "abandoned"} and not resume:
                    results_by_run[run_id] = _run_summary(run, reused=False)
                    continue
                attempt = await self._repository.prepare_run_attempt(run_id, resume=resume)
                await self._repository.commit()
                prepared_attempts.append(attempt)

            concurrency = (
                _required_int(prepared_attempts[0], "runConcurrency") if prepared_attempts else 1
            )
            semaphore = asyncio.Semaphore(concurrency)
            finish_lock = asyncio.Lock()

            async def execute_attempt(attempt: JsonObject) -> tuple[str, JsonObject]:
                run_id = _required_str(attempt, "runId")
                async with semaphore:
                    try:
                        snapshot = await self._objects.get_json(
                            key=_required_str(attempt, "snapshotObjectKey")
                        )
                        generated = await self._generator.generate(
                            experiment_id=experiment_id,
                            run=attempt,
                            snapshot=snapshot,
                            resume=resume,
                        )
                        attempt_no = _required_int(attempt, "attemptNo")
                        result_object = await self._objects.put_json(
                            key=(
                                f"experiments/{experiment_id}/runs/{run_id}/"
                                f"attempts/{attempt_no}/result.json"
                            ),
                            payload=generated.output,
                        )
                        artifacts = [*generated.artifacts, result_object]
                        output: JsonObject = {
                            "resultObjectKey": result_object.key,
                            "resultSha256": result_object.sha256,
                            "resultByteSize": result_object.byte_size,
                        }
                        async with finish_lock:
                            await self._repository.finish_run(
                                run_id,
                                status="succeeded",
                                output=output,
                                artifacts=artifacts,
                                error=None,
                            )
                            await self._repository.commit()
                        return run_id, {"runId": run_id, "status": "succeeded"}
                    except Exception as exc:
                        async with finish_lock:
                            await self._repository.finish_run(
                                run_id,
                                status="failed",
                                output=None,
                                artifacts=[],
                                error=exc,
                            )
                            await self._repository.commit()
                        return run_id, {
                            "runId": run_id,
                            "status": "failed",
                            "errorType": type(exc).__name__,
                            "errorMessage": "Run failed; inspect private evaluation state.",
                        }

            for run_id, result in await asyncio.gather(
                *(execute_attempt(attempt) for attempt in prepared_attempts)
            ):
                results_by_run[run_id] = result
        finally:
            await self._repository.release_experiment_lock(experiment_id)
        results = [results_by_run[run_id] for run_id in run_order]
        failed = sum(item.get("status") == "failed" for item in results)
        incomplete = sum(item.get("status") != "succeeded" for item in results)
        return {
            "experimentId": experiment_id,
            "stage": stage,
            "ok": incomplete == 0,
            "failedCount": failed,
            "incompleteCount": incomplete,
            "items": results,
        }

    async def bundle(self, *, experiment_id: str, stage: EvaluationStage) -> JsonObject:
        experiment = await self._require_experiment(experiment_id)
        runs = await self._repository.list_stage_runs(experiment_id, stage)
        items: list[JsonObject] = []
        for run in runs:
            if run.get("status") != "succeeded":
                continue
            result_key = _required_str(run, "resultObjectKey")
            items.append(
                {
                    "blindRunId": _required_str(run, "blindRunId"),
                    "candidateAlias": _required_str(run, "candidateAlias"),
                    "videoId": _required_int(run, "videoId"),
                    "youtubeVideoId": run.get("youtubeVideoId"),
                    "replicate": _required_int(run, "replicate"),
                    "source": _blind_source(
                        await self._objects.get_json(key=_required_str(run, "snapshotObjectKey"))
                    ),
                    "result": _blind_result(await self._objects.get_json(key=result_key)),
                }
            )
        rubric_version = _experiment_rubric_version(experiment, stage)
        rubric_keys = RUBRIC_KEYS_BY_VERSION[rubric_version]
        return {
            "version": 1,
            "experimentId": experiment_id,
            "experimentKey": experiment.get("experimentKey"),
            "stage": stage,
            "rubricVersion": rubric_version,
            "rubricKeys": sorted(rubric_keys),
            "items": items,
        }

    async def import_scores(
        self,
        *,
        experiment_id: str,
        scores: EvaluationScoreImport,
    ) -> JsonObject:
        experiment = await self._require_experiment(experiment_id)
        expected_version = _experiment_rubric_version(experiment, scores.stage)
        if scores.rubric_version != expected_version:
            raise EvaluationConflict(
                f"rubricVersion must match the experiment bundle: {expected_version}."
            )
        expected = RUBRIC_KEYS_BY_VERSION[scores.rubric_version]
        for item in scores.items:
            if set(item.scores) != expected:
                raise EvaluationConflict(
                    f"Score keys must exactly match rubric {scores.rubric_version}."
                )
        result = await self._repository.import_scores(
            experiment_id,
            scores.model_dump(mode="json", by_alias=True),
        )
        await self._repository.commit()
        return result

    async def select_micro(
        self,
        *,
        experiment_id: str,
        selections: MicroSelectionImport,
    ) -> JsonObject:
        await self._require_experiment(experiment_id)
        result = await self._repository.select_micro(
            experiment_id,
            selections.model_dump(mode="json", by_alias=True),
        )
        await self._repository.commit()
        return result

    async def status(self, experiment_id: str) -> JsonObject:
        await self._require_experiment(experiment_id)
        return await self._repository.status(experiment_id)

    async def report(self, experiment_id: str, *, unblind: bool) -> JsonObject:
        await self._require_experiment(experiment_id)
        return await self._repository.report(experiment_id, unblind=unblind)

    async def verify(self, experiment_id: str) -> JsonObject:
        await self._require_experiment(experiment_id)
        mismatches: list[JsonObject] = []
        for artifact in await self._repository.artifacts(experiment_id):
            key = _required_str(artifact, "objectKey")
            actual = await self._objects.stat(key=key)
            if actual is None:
                mismatches.append({"objectKey": key, "reason": "missing"})
                continue
            if actual.sha256 != artifact.get("sha256") or actual.byte_size != artifact.get(
                "byteSize"
            ):
                mismatches.append({"objectKey": key, "reason": "hash_or_size_mismatch"})
        status = await self._repository.status(experiment_id)
        return {
            "experimentId": experiment_id,
            "ok": not mismatches,
            "artifactCount": len(await self._repository.artifacts(experiment_id)),
            "mismatches": mismatches,
            "status": status,
        }

    async def _require_experiment(self, experiment_id: str) -> JsonObject:
        result = await self._repository.get_experiment(experiment_id)
        if result is None:
            raise EvaluationNotFound("Evaluation experiment was not found.")
        return result


def write_bundle(bundle: JsonObject, *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{bundle['experimentId']}-{bundle['stage']}-blind.json"
    path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _stable_experiment_id(experiment_key: str, plan_hash: str) -> str:
    digest = hashlib.sha256(f"{experiment_key}:{plan_hash}".encode()).hexdigest()
    return f"eval-{digest[:20]}"


def _pin_prompt_versions(
    plan: EvaluationPlan,
    snapshot_payloads: list[JsonObject],
) -> EvaluationPlan:
    if not snapshot_payloads:
        raise EvaluationConflict("Evaluation source snapshot is empty.")
    prompts = _object_or_empty(snapshot_payloads[0].get("prompts"))
    payload = plan.model_dump(mode="json", by_alias=True)
    for stage_key, candidate_key in (
        ("micro", "microCandidates"),
        ("timeline", "timelineCandidates"),
    ):
        resolved_by_candidate = _object_or_empty(prompts.get(stage_key))
        candidates = _list_or_empty(payload.get(candidate_key))
        for value in candidates:
            candidate = _object_or_empty(value)
            if candidate.get("promptVersionId") is not None:
                continue
            key = _required_str(candidate, "key")
            resolved = _object_or_empty(resolved_by_candidate.get(key))
            version_id = resolved.get("versionId")
            if isinstance(version_id, bool) or not isinstance(version_id, int):
                raise EvaluationConflict(
                    f"Snapshot did not resolve an active prompt version for {stage_key}:{key}."
                )
            candidate["promptVersionId"] = version_id
    return EvaluationPlan.model_validate(payload)


def _json_sha256(payload: JsonObject) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _experiment_rubric_version(
    experiment: JsonObject,
    stage: EvaluationStage,
) -> str:
    versions = _object_or_empty(experiment.get("rubricVersions"))
    value = versions.get(stage)
    if not isinstance(value, str) or value not in RUBRIC_KEYS_BY_VERSION:
        raise EvaluationConflict(f"Experiment has no valid {stage} rubric version.")
    return value


def _required_str(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationConflict(f"Missing string field: {key}")
    return value


def _required_int(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationConflict(f"Missing integer field: {key}")
    return value


def _run_summary(run: JsonObject, *, reused: bool) -> JsonObject:
    return {
        "runId": run.get("runId"),
        "status": run.get("status"),
        "reused": reused,
    }


def _blind_source(snapshot: JsonObject) -> JsonObject:
    video = _object_or_empty(snapshot.get("video"))
    channel = _object_or_empty(snapshot.get("channel"))
    streamer = _object_or_empty(snapshot.get("streamer"))
    cues = [
        {
            key: cue.get(key)
            for key in (
                "cue_id",
                "cue_index",
                "text",
                "start_ms",
                "end_ms",
                "duration_ms",
            )
        }
        for cue in (
            _object_or_empty(item)
            for item in _list_or_empty(snapshot.get("cues"))
            if isinstance(item, dict)
        )
    ]
    return {
        "videoId": snapshot.get("videoId"),
        "youtubeVideoId": snapshot.get("youtubeVideoId"),
        "video": {key: video.get(key) for key in ("title", "published_at", "duration")},
        "channel": {key: channel.get(key) for key in ("handle", "name")},
        "streamer": {"name": streamer.get("name")},
        "cues": cues,
        "domainKnowledge": snapshot.get("domainKnowledge"),
    }


def _blind_result(payload: JsonObject) -> JsonObject:
    blocked = {
        "model",
        "reasoningEffort",
        "reasoning_effort",
        "threadId",
        "thread_id",
        "turnId",
        "turn_id",
        "rawResponseText",
        "raw_response_text",
        "usage",
        "tokens",
    }

    def scrub(value: object) -> object:
        if isinstance(value, dict):
            return {str(key): scrub(item) for key, item in value.items() if str(key) not in blocked}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    stage = payload.get("stage")
    if stage == "timeline":
        return cast(JsonObject, scrub(_object_or_empty(payload.get("response"))))
    if stage == "micro":
        detail = _object_or_empty(payload.get("detail"))
        windows = []
        for value in _list_or_empty(detail.get("windows")):
            if not isinstance(value, dict):
                continue
            window = cast(JsonObject, value)
            windows.append(
                {
                    key: scrub(window.get(key))
                    for key in (
                        "window_index",
                        "start_cue_id",
                        "end_cue_id",
                        "cue_count",
                        "status",
                        "carry_out_unfinished",
                        "validation_error",
                        "micro_events",
                        "excluded_ranges",
                        "asr_correction_candidates",
                    )
                }
            )
        return {"stage": "micro", "windows": windows}
    return cast(JsonObject, scrub(payload))


def _object_or_empty(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def _list_or_empty(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []
