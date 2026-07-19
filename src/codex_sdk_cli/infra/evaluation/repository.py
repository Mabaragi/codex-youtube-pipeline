from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from typing_extensions import override

from codex_sdk_cli.domains.evaluation.ports import (
    EvaluationRepositoryPort,
    EvaluationStoredObject,
    JsonObject,
)
from codex_sdk_cli.domains.evaluation.schemas import (
    CURRENT_RUBRIC_VERSION,
    EvaluationPlan,
    EvaluationStage,
)

from .models import (
    EvaluationArtifactModel,
    EvaluationCandidateModel,
    EvaluationCaseModel,
    EvaluationCheckpointModel,
    EvaluationExperimentModel,
    EvaluationMicroSelectionModel,
    EvaluationReviewModel,
    EvaluationRunAttemptModel,
    EvaluationRunModel,
    EvaluationUsageModel,
)


class SqlAlchemyEvaluationRepository(EvaluationRepositoryPort):
    def __init__(self, *, session: AsyncSession, engine: AsyncEngine) -> None:
        self._session = session
        self._engine = engine
        self._lock_connections: dict[str, AsyncConnection] = {}
        self._local_locks: set[str] = set()

    @override
    async def commit(self) -> None:
        await self._session.commit()

    @override
    async def create_experiment(
        self,
        *,
        experiment_id: str,
        plan: EvaluationPlan,
        plan_hash: str,
        snapshots: list[tuple[JsonObject, EvaluationStoredObject]],
    ) -> JsonObject:
        experiment = EvaluationExperimentModel(
            id=experiment_id,
            experiment_key=plan.experiment_key,
            plan_hash=plan_hash,
            plan_json=plan.model_dump(mode="json", by_alias=True),
            micro_rubric_version=CURRENT_RUBRIC_VERSION["micro"],
            timeline_rubric_version=CURRENT_RUBRIC_VERSION["timeline"],
        )
        self._session.add(experiment)
        await self._session.flush()
        cases: list[EvaluationCaseModel] = []
        for payload, stored in snapshots:
            video_id = _int(payload, "videoId")
            youtube_video_id = _str(payload, "youtubeVideoId")
            case = EvaluationCaseModel(
                id=_stable_id("case", experiment_id, str(video_id)),
                experiment_id=experiment_id,
                video_id=video_id,
                youtube_video_id=youtube_video_id,
                snapshot_object_key=stored.key,
                snapshot_sha256=stored.sha256,
                snapshot_byte_size=stored.byte_size,
            )
            cases.append(case)
            self._session.add(case)
            self._session.add(
                EvaluationArtifactModel(
                    id=_stable_id("artifact", experiment_id, stored.key),
                    experiment_id=experiment_id,
                    run_id=None,
                    kind="source-snapshot",
                    object_key=stored.key,
                    sha256=stored.sha256,
                    byte_size=stored.byte_size,
                )
            )

        candidates: list[EvaluationCandidateModel] = []
        for stage, configured in (
            ("micro", plan.micro_candidates),
            ("timeline", plan.timeline_candidates),
        ):
            ordered = sorted(
                configured,
                key=lambda item: _stable_id("blind", experiment_id, stage, item.key),
            )
            aliases = {item.key: _candidate_alias(index) for index, item in enumerate(ordered)}
            for item in configured:
                candidate = EvaluationCandidateModel(
                    id=_stable_id("candidate", experiment_id, stage, item.key),
                    experiment_id=experiment_id,
                    stage=stage,
                    candidate_key=item.key,
                    blind_alias=aliases[item.key],
                    config_json=item.model_dump(mode="json", by_alias=True),
                )
                candidates.append(candidate)
                self._session.add(candidate)

        await self._session.flush()

        existing_numbers = set(
            (await self._session.scalars(select(EvaluationRunModel.run_no))).all()
        )
        for case in cases:
            for candidate in candidates:
                for replicate in range(1, plan.repetitions + 1):
                    run_id = _stable_uuid(
                        "run",
                        experiment_id,
                        case.id,
                        candidate.id,
                        str(replicate),
                    )
                    run_no = _stable_run_no(run_id, existing_numbers)
                    existing_numbers.add(run_no)
                    self._session.add(
                        EvaluationRunModel(
                            id=run_id,
                            run_no=run_no,
                            experiment_id=experiment_id,
                            case_id=case.id,
                            candidate_id=candidate.id,
                            stage=candidate.stage,
                            replicate=replicate,
                            blind_run_id=_stable_id(
                                "blind-run", experiment_id, case.id, candidate.id, str(replicate)
                            ),
                            status="pending",
                            attempt_count=0,
                        )
                    )
        await self._session.flush()
        return _experiment_dict(experiment)

    @override
    async def get_experiment_by_key(self, experiment_key: str) -> JsonObject | None:
        result = await self._session.scalar(
            select(EvaluationExperimentModel).where(
                EvaluationExperimentModel.experiment_key == experiment_key
            )
        )
        return _experiment_dict(result) if result is not None else None

    @override
    async def get_experiment(self, experiment_id: str) -> JsonObject | None:
        result = await self._session.get(EvaluationExperimentModel, experiment_id)
        return _experiment_dict(result) if result is not None else None

    @override
    async def list_stage_runs(self, experiment_id: str, stage: EvaluationStage) -> list[JsonObject]:
        if stage == "timeline":
            await self._bind_timeline_sources(experiment_id)
        rows = (
            await self._session.execute(
                select(
                    EvaluationRunModel,
                    EvaluationCaseModel,
                    EvaluationCandidateModel,
                )
                .join(EvaluationCaseModel, EvaluationCaseModel.id == EvaluationRunModel.case_id)
                .join(
                    EvaluationCandidateModel,
                    EvaluationCandidateModel.id == EvaluationRunModel.candidate_id,
                )
                .where(
                    EvaluationRunModel.experiment_id == experiment_id,
                    EvaluationRunModel.stage == stage,
                )
                .order_by(
                    EvaluationCaseModel.video_id,
                    EvaluationCandidateModel.blind_alias,
                    EvaluationRunModel.replicate,
                )
            )
        ).all()
        return [await self._run_dict(run, case, candidate) for run, case, candidate in rows]

    @override
    async def prepare_run_attempt(self, run_id: str, *, resume: bool) -> JsonObject:
        run = await self._session.get(EvaluationRunModel, run_id)
        if run is None:
            raise ValueError("Evaluation run was not found.")
        if run.status == "running":
            if not resume:
                raise ValueError("Evaluation run is already running.")
            await self._abandon_running_attempts(run_id)
        attempt_no = run.attempt_count + 1
        attempt = EvaluationRunAttemptModel(
            id=_stable_id("attempt", run_id, str(attempt_no)),
            run_id=run_id,
            attempt_no=attempt_no,
            status="running",
        )
        self._session.add(attempt)
        run.status = "running"
        run.attempt_count = attempt_no
        run.error_type = None
        run.error_message = None
        run.started_at = datetime.now(UTC)
        run.completed_at = None
        await self._session.flush()
        case = await self._session.get(EvaluationCaseModel, run.case_id)
        candidate = await self._session.get(EvaluationCandidateModel, run.candidate_id)
        if case is None or candidate is None:
            raise ValueError("Evaluation run references missing case or candidate state.")
        result = await self._run_dict(run, case, candidate)
        result.update({"attemptId": attempt.id, "attemptNo": attempt.attempt_no})
        return result

    @override
    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        output: JsonObject | None,
        artifacts: list[EvaluationStoredObject],
        error: Exception | None,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("Invalid terminal evaluation run status.")
        run = await self._session.get(EvaluationRunModel, run_id)
        if run is None:
            raise ValueError("Evaluation run was not found.")
        attempt = await self._session.scalar(
            select(EvaluationRunAttemptModel).where(
                EvaluationRunAttemptModel.run_id == run_id,
                EvaluationRunAttemptModel.attempt_no == run.attempt_count,
            )
        )
        if attempt is None:
            raise ValueError("Evaluation run attempt was not found.")
        now = datetime.now(UTC)
        run.status = status
        run.output_json = output
        run.completed_at = now
        run.error_type = type(error).__name__ if error is not None else None
        run.error_message = (str(error) or type(error).__name__) if error is not None else None
        attempt.status = status
        attempt.finished_at = now
        attempt.error_type = run.error_type
        attempt.error_message = run.error_message
        for stored in artifacts:
            await self.record_artifact(run_id=run_id, kind="run-output", stored=stored)

    @override
    async def selected_micro_run(self, experiment_id: str, video_id: int) -> JsonObject | None:
        row = (
            await self._session.execute(
                select(
                    EvaluationRunModel,
                    EvaluationCaseModel,
                    EvaluationCandidateModel,
                )
                .join(
                    EvaluationMicroSelectionModel,
                    EvaluationMicroSelectionModel.micro_run_id == EvaluationRunModel.id,
                )
                .join(EvaluationCaseModel, EvaluationCaseModel.id == EvaluationRunModel.case_id)
                .join(
                    EvaluationCandidateModel,
                    EvaluationCandidateModel.id == EvaluationRunModel.candidate_id,
                )
                .where(
                    EvaluationMicroSelectionModel.experiment_id == experiment_id,
                    EvaluationCaseModel.video_id == video_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return await self._run_dict(row[0], row[1], row[2])

    @override
    async def import_scores(self, experiment_id: str, payload: JsonObject) -> JsonObject:
        stage = _str(payload, "stage")
        evaluator = _str(payload, "evaluator")
        rubric_version = _str(payload, "rubricVersion")
        items = _list_of_dict(payload, "items")
        imported = 0
        for item in items:
            blind_run_id = _str(item, "blindRunId")
            run = await self._session.scalar(
                select(EvaluationRunModel).where(
                    EvaluationRunModel.experiment_id == experiment_id,
                    EvaluationRunModel.blind_run_id == blind_run_id,
                )
            )
            if run is None or run.stage != stage:
                raise ValueError(f"Unknown {stage} blindRunId: {blind_run_id}")
            if run.status != "succeeded":
                raise ValueError(f"Run must be succeeded before scoring: {blind_run_id}")
            scores = cast(dict[str, object], item.get("scores"))
            total = sum(float(cast(int, score)) for score in scores.values())
            review = await self._session.scalar(
                select(EvaluationReviewModel).where(
                    EvaluationReviewModel.run_id == run.id,
                    EvaluationReviewModel.evaluator == evaluator,
                    EvaluationReviewModel.rubric_version == rubric_version,
                )
            )
            if review is None:
                review = EvaluationReviewModel(
                    id=_stable_id("review", run.id, evaluator, rubric_version),
                    run_id=run.id,
                    evaluator=evaluator,
                    rubric_version=rubric_version,
                    scores_json=scores,
                    total_score=total,
                    notes=_optional_str(item.get("notes")),
                    evidence_json=cast(list[object], item.get("evidence") or []),
                )
                self._session.add(review)
            else:
                review.scores_json = scores
                review.total_score = total
                review.notes = _optional_str(item.get("notes"))
                review.evidence_json = cast(list[object], item.get("evidence") or [])
            imported += 1
        return {"experimentId": experiment_id, "stage": stage, "importedCount": imported}

    @override
    async def select_micro(self, experiment_id: str, payload: JsonObject) -> JsonObject:
        experiment = await self._session.get(EvaluationExperimentModel, experiment_id)
        if experiment is None:
            raise ValueError("Evaluation experiment was not found.")
        selections = _list_of_dict(payload, "selections")
        cases = (
            await self._session.scalars(
                select(EvaluationCaseModel).where(
                    EvaluationCaseModel.experiment_id == experiment_id
                )
            )
        ).all()
        case_by_video = {case.video_id: case for case in cases}
        selected_videos = {_int(item, "videoId") for item in selections}
        if selected_videos != set(case_by_video):
            raise ValueError("Every experiment video must have exactly one micro selection.")
        timeline_started = await self._session.scalar(
            select(func.count())
            .select_from(EvaluationRunModel)
            .where(
                EvaluationRunModel.experiment_id == experiment_id,
                EvaluationRunModel.stage == "timeline",
                EvaluationRunModel.attempt_count > 0,
            )
        )
        if timeline_started:
            raise ValueError("Micro selections are immutable after timeline execution starts.")
        resolved: list[tuple[EvaluationCaseModel, EvaluationRunModel]] = []
        for item in selections:
            video_id = _int(item, "videoId")
            blind_run_id = _str(item, "blindRunId")
            run = await self._session.scalar(
                select(EvaluationRunModel).where(
                    EvaluationRunModel.experiment_id == experiment_id,
                    EvaluationRunModel.blind_run_id == blind_run_id,
                    EvaluationRunModel.case_id == case_by_video[video_id].id,
                    EvaluationRunModel.stage == "micro",
                )
            )
            if run is None or run.status != "succeeded":
                raise ValueError(f"Invalid succeeded micro selection: {blind_run_id}")
            score_count = await self._session.scalar(
                select(func.count())
                .select_from(EvaluationReviewModel)
                .where(
                    EvaluationReviewModel.run_id == run.id,
                    EvaluationReviewModel.rubric_version
                    == experiment.micro_rubric_version,
                )
            )
            if not score_count:
                raise ValueError(f"Micro selection has no imported score: {blind_run_id}")
            resolved.append((case_by_video[video_id], run))
        await self._session.execute(
            delete(EvaluationMicroSelectionModel).where(
                EvaluationMicroSelectionModel.experiment_id == experiment_id
            )
        )
        for case, run in resolved:
            self._session.add(
                EvaluationMicroSelectionModel(
                    id=_stable_id("selection", experiment_id, case.id),
                    experiment_id=experiment_id,
                    case_id=case.id,
                    micro_run_id=run.id,
                )
            )
        await self._session.execute(
            update(EvaluationRunModel)
            .where(
                EvaluationRunModel.experiment_id == experiment_id,
                EvaluationRunModel.stage == "timeline",
            )
            .values(source_micro_run_id=None)
        )
        return {"experimentId": experiment_id, "selectedCount": len(resolved)}

    @override
    async def status(self, experiment_id: str) -> JsonObject:
        rows = (
            await self._session.execute(
                select(EvaluationRunModel.stage, EvaluationRunModel.status, func.count())
                .where(EvaluationRunModel.experiment_id == experiment_id)
                .group_by(EvaluationRunModel.stage, EvaluationRunModel.status)
            )
        ).all()
        stages: dict[str, dict[str, int]] = {"micro": {}, "timeline": {}}
        for stage, status, count in rows:
            stages[stage][status] = count
        case_count = (
            await self._session.scalar(
                select(func.count())
                .select_from(EvaluationCaseModel)
                .where(EvaluationCaseModel.experiment_id == experiment_id)
            )
            or 0
        )
        selection_count = (
            await self._session.scalar(
                select(func.count())
                .select_from(EvaluationMicroSelectionModel)
                .where(EvaluationMicroSelectionModel.experiment_id == experiment_id)
            )
            or 0
        )
        return {
            "experimentId": experiment_id,
            "stages": stages,
            "microSelections": {"selected": selection_count, "required": case_count},
        }

    @override
    async def report(self, experiment_id: str, *, unblind: bool) -> JsonObject:
        experiment = await self._session.get(EvaluationExperimentModel, experiment_id)
        if experiment is None:
            raise ValueError("Evaluation experiment was not found.")
        expected_review = _expected_review_filter(experiment)
        rows = (
            await self._session.execute(
                select(EvaluationRunModel, EvaluationCandidateModel)
                .join(
                    EvaluationCandidateModel,
                    EvaluationCandidateModel.id == EvaluationRunModel.candidate_id,
                )
                .where(EvaluationRunModel.experiment_id == experiment_id)
            )
        ).all()
        if unblind:
            incomplete = [run for run, _ in rows if run.status in {"pending", "running"}]
            succeeded_ids = [run.id for run, _ in rows if run.status == "succeeded"]
            reviewed_ids = set(
                (
                    await self._session.scalars(
                        select(EvaluationReviewModel.run_id)
                        .join(
                            EvaluationRunModel,
                            EvaluationRunModel.id == EvaluationReviewModel.run_id,
                        )
                        .where(
                            EvaluationReviewModel.run_id.in_(succeeded_ids),
                            expected_review,
                        )
                    )
                ).all()
            )
            if incomplete or set(succeeded_ids) - reviewed_ids:
                raise ValueError("Unblinding requires terminal runs and all successful scores.")
        usage_rows = (
            await self._session.execute(
                select(EvaluationUsageModel, EvaluationRunAttemptModel.status)
                .join(
                    EvaluationRunAttemptModel,
                    EvaluationRunAttemptModel.id == EvaluationUsageModel.attempt_id,
                )
                .join(EvaluationRunModel, EvaluationRunModel.id == EvaluationUsageModel.run_id)
                .where(EvaluationRunModel.experiment_id == experiment_id)
            )
        ).all()
        reviews = (
            await self._session.execute(
                select(
                    EvaluationReviewModel,
                    EvaluationRunModel.candidate_id,
                    EvaluationRunModel.blind_run_id,
                    EvaluationCaseModel.video_id,
                )
                .join(EvaluationRunModel, EvaluationRunModel.id == EvaluationReviewModel.run_id)
                .join(EvaluationCaseModel, EvaluationCaseModel.id == EvaluationRunModel.case_id)
                .where(
                    EvaluationRunModel.experiment_id == experiment_id,
                    expected_review,
                )
            )
        ).all()
        usage_by_candidate: dict[str, dict[str, int]] = defaultdict(
            _empty_token_totals
        )
        run_candidate = {run.id: candidate.id for run, candidate in rows}
        for usage, attempt_status in usage_rows:
            total = usage.total_tokens or 0
            bucket = usage_by_candidate[run_candidate[usage.run_id]]
            bucket["actualInputTokens"] += usage.input_tokens or 0
            bucket["actualOutputTokens"] += usage.output_tokens or 0
            bucket["actualTotalTokens"] += total
            bucket["actualCachedInputTokens"] += usage.cached_input_tokens or 0
            bucket["actualReasoningOutputTokens"] += usage.reasoning_output_tokens or 0
            if attempt_status == "succeeded":
                bucket["successfulAttemptInputTokens"] += usage.input_tokens or 0
                bucket["successfulAttemptOutputTokens"] += usage.output_tokens or 0
                bucket["successfulAttemptTokens"] += total
                bucket["successfulAttemptCachedInputTokens"] += (
                    usage.cached_input_tokens or 0
                )
                bucket["successfulAttemptReasoningOutputTokens"] += (
                    usage.reasoning_output_tokens or 0
                )
        quality: dict[str, list[float]] = defaultdict(list)
        for review, candidate_id, _blind_run_id, _video_id in reviews:
            quality[candidate_id].append(review.total_score)
        run_counts: dict[str, Counter[str]] = defaultdict(Counter)
        candidate_map: dict[str, EvaluationCandidateModel] = {}
        for run, candidate in rows:
            run_counts[candidate.id][run.status] += 1
            candidate_map[candidate.id] = candidate
        candidate_results: list[JsonObject] = []
        for candidate_id, candidate in sorted(
            candidate_map.items(), key=lambda item: (item[1].stage, item[1].blind_alias)
        ):
            counts = run_counts[candidate_id]
            total = sum(counts.values())
            terminal_total = counts["succeeded"] + counts["failed"] + counts["abandoned"]
            terminal_failures = counts["failed"] + counts["abandoned"]
            item: JsonObject = {
                "stage": candidate.stage,
                "candidateAlias": candidate.blind_alias,
                "runs": dict(counts),
                "failureRate": (terminal_failures / terminal_total if terminal_total else 0.0),
                "runCount": total,
                "tokens": usage_by_candidate[candidate_id],
                "quality": {
                    "reviewCount": len(quality[candidate_id]),
                    "averageTotalScore": (
                        sum(quality[candidate_id]) / len(quality[candidate_id])
                        if quality[candidate_id]
                        else None
                    ),
                },
            }
            if unblind:
                item.update(
                    {
                        "candidateKey": candidate.candidate_key,
                        "config": candidate.config_json,
                    }
                )
            candidate_results.append(item)
        video_results = _video_review_results(
            cast(list[tuple[EvaluationReviewModel, str, str, int]], reviews),
            candidate_map,
            unblind=unblind,
        )
        return {
            "version": 1,
            "experimentId": experiment_id,
            "unblinded": unblind,
            "candidates": candidate_results,
            "videos": video_results,
        }

    @override
    async def record_artifact(
        self,
        *,
        run_id: str | None,
        kind: str,
        stored: EvaluationStoredObject,
    ) -> None:
        existing = await self._session.scalar(
            select(EvaluationArtifactModel).where(EvaluationArtifactModel.object_key == stored.key)
        )
        if existing is not None:
            if existing.sha256 != stored.sha256 or existing.byte_size != stored.byte_size:
                raise ValueError("Evaluation artifact identity changed for an existing key.")
            return
        if run_id is None:
            raise ValueError("A run is required for non-snapshot evaluation artifacts.")
        run = await self._session.get(EvaluationRunModel, run_id)
        if run is None:
            raise ValueError("Evaluation run was not found.")
        self._session.add(
            EvaluationArtifactModel(
                id=_stable_id("artifact", run.experiment_id, stored.key),
                experiment_id=run.experiment_id,
                run_id=run_id,
                kind=kind,
                object_key=stored.key,
                sha256=stored.sha256,
                byte_size=stored.byte_size,
            )
        )

    @override
    async def artifacts(self, experiment_id: str) -> list[JsonObject]:
        rows = (
            await self._session.scalars(
                select(EvaluationArtifactModel)
                .where(EvaluationArtifactModel.experiment_id == experiment_id)
                .order_by(EvaluationArtifactModel.object_key)
            )
        ).all()
        return [
            {
                "objectKey": row.object_key,
                "sha256": row.sha256,
                "byteSize": row.byte_size,
                "kind": row.kind,
                "runId": row.run_id,
            }
            for row in rows
        ]

    @override
    async def acquire_experiment_lock(self, experiment_id: str) -> bool:
        if self._engine.dialect.name != "postgresql":
            if experiment_id in self._local_locks:
                return False
            self._local_locks.add(experiment_id)
            return True
        connection = await self._engine.connect()
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _advisory_key(experiment_id)},
            )
        )
        if acquired:
            self._lock_connections[experiment_id] = connection
        else:
            await connection.close()
        return acquired

    @override
    async def release_experiment_lock(self, experiment_id: str) -> None:
        if self._engine.dialect.name != "postgresql":
            self._local_locks.discard(experiment_id)
            return
        connection = self._lock_connections.pop(experiment_id, None)
        if connection is None:
            return
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _advisory_key(experiment_id)},
            )
        finally:
            await connection.close()

    async def checkpoints(self, run_id: str) -> list[JsonObject]:
        rows = (
            await self._session.scalars(
                select(EvaluationCheckpointModel)
                .where(EvaluationCheckpointModel.run_id == run_id)
                .order_by(EvaluationCheckpointModel.checkpoint_key)
            )
        ).all()
        return [
            {
                "checkpointKey": row.checkpoint_key,
                "status": row.status,
                "payload": row.payload_json,
                "objectKey": row.object_key,
                "sha256": row.sha256,
                "byteSize": row.byte_size,
            }
            for row in rows
        ]

    async def upsert_checkpoint(
        self,
        *,
        run_id: str,
        checkpoint_key: str,
        status: str,
        payload: JsonObject | None,
        stored: EvaluationStoredObject | None,
    ) -> None:
        row = await self._session.scalar(
            select(EvaluationCheckpointModel).where(
                EvaluationCheckpointModel.run_id == run_id,
                EvaluationCheckpointModel.checkpoint_key == checkpoint_key,
            )
        )
        values = {
            "status": status,
            "payload_json": payload,
            "object_key": stored.key if stored else None,
            "sha256": stored.sha256 if stored else None,
            "byte_size": stored.byte_size if stored else None,
        }
        if row is None:
            row = EvaluationCheckpointModel(
                id=_stable_id("checkpoint", run_id, checkpoint_key),
                run_id=run_id,
                checkpoint_key=checkpoint_key,
                **values,
            )
            self._session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        if stored is not None:
            await self.record_artifact(run_id=run_id, kind="micro-checkpoint", stored=stored)

    async def _bind_timeline_sources(self, experiment_id: str) -> None:
        case_count = (
            await self._session.scalar(
                select(func.count())
                .select_from(EvaluationCaseModel)
                .where(EvaluationCaseModel.experiment_id == experiment_id)
            )
            or 0
        )
        selections = (
            await self._session.execute(
                select(
                    EvaluationMicroSelectionModel.case_id,
                    EvaluationMicroSelectionModel.micro_run_id,
                ).where(EvaluationMicroSelectionModel.experiment_id == experiment_id)
            )
        ).all()
        if len(selections) != case_count:
            raise ValueError(
                "Timeline evaluation requires a scored micro selection for every video."
            )
        source_by_case = dict(selections)
        timeline_runs = (
            await self._session.scalars(
                select(EvaluationRunModel).where(
                    EvaluationRunModel.experiment_id == experiment_id,
                    EvaluationRunModel.stage == "timeline",
                )
            )
        ).all()
        for run in timeline_runs:
            selected = source_by_case[run.case_id]
            if run.source_micro_run_id is not None and run.source_micro_run_id != selected:
                raise ValueError("Timeline run already references a different immutable micro run.")
            run.source_micro_run_id = selected
        await self._session.flush()

    async def _run_dict(
        self,
        run: EvaluationRunModel,
        case: EvaluationCaseModel,
        candidate: EvaluationCandidateModel,
    ) -> JsonObject:
        result: JsonObject = {
            "runId": run.id,
            "runNo": run.run_no,
            "experimentId": run.experiment_id,
            "stage": run.stage,
            "status": run.status,
            "attemptCount": run.attempt_count,
            "replicate": run.replicate,
            "blindRunId": run.blind_run_id,
            "candidateAlias": candidate.blind_alias,
            "candidateKey": candidate.candidate_key,
            "candidateConfig": candidate.config_json,
            "videoId": case.video_id,
            "youtubeVideoId": case.youtube_video_id,
            "snapshotObjectKey": case.snapshot_object_key,
            "sourceMicroRunId": run.source_micro_run_id,
        }
        experiment = await self._session.get(EvaluationExperimentModel, run.experiment_id)
        if experiment is not None:
            result["runConcurrency"] = experiment.plan_json.get("runConcurrency", 1)
            result["microWindowConcurrency"] = experiment.plan_json.get("microWindowConcurrency", 1)
        if run.output_json:
            result.update(run.output_json)
        if run.source_micro_run_id:
            source = await self._session.get(EvaluationRunModel, run.source_micro_run_id)
            if source is None or source.status != "succeeded" or not source.output_json:
                raise ValueError("Selected micro run is not available for timeline generation.")
            result["sourceMicroRunNo"] = source.run_no
            result["sourceMicroResultObjectKey"] = source.output_json.get("resultObjectKey")
        return result

    async def _abandon_running_attempts(self, run_id: str) -> None:
        now = datetime.now(UTC)
        attempts = (
            await self._session.scalars(
                select(EvaluationRunAttemptModel).where(
                    EvaluationRunAttemptModel.run_id == run_id,
                    EvaluationRunAttemptModel.status == "running",
                )
            )
        ).all()
        for attempt in attempts:
            attempt.status = "abandoned"
            attempt.finished_at = now
            attempt.error_type = "InterruptedProcess"
            attempt.error_message = (
                "Previous evaluation process ended before the attempt completed."
            )


def _experiment_dict(experiment: EvaluationExperimentModel) -> JsonObject:
    return {
        "experimentId": experiment.id,
        "experimentKey": experiment.experiment_key,
        "planHash": experiment.plan_hash,
        "plan": experiment.plan_json,
        "rubricVersions": {
            "micro": experiment.micro_rubric_version,
            "timeline": experiment.timeline_rubric_version,
        },
    }


def _expected_review_filter(experiment: EvaluationExperimentModel):
    return or_(
        and_(
            EvaluationRunModel.stage == "micro",
            EvaluationReviewModel.rubric_version == experiment.micro_rubric_version,
        ),
        and_(
            EvaluationRunModel.stage == "timeline",
            EvaluationReviewModel.rubric_version == experiment.timeline_rubric_version,
        ),
    )


def _empty_token_totals() -> dict[str, int]:
    return {
        "actualInputTokens": 0,
        "actualOutputTokens": 0,
        "actualTotalTokens": 0,
        "actualCachedInputTokens": 0,
        "actualReasoningOutputTokens": 0,
        "successfulAttemptInputTokens": 0,
        "successfulAttemptOutputTokens": 0,
        "successfulAttemptTokens": 0,
        "successfulAttemptCachedInputTokens": 0,
        "successfulAttemptReasoningOutputTokens": 0,
    }


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(parts)))


def _stable_run_no(run_id: str, used: set[int]) -> int:
    candidate = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) & 0x7FFF_FFFF
    candidate = candidate or 1
    while candidate in used:
        candidate = (candidate + 1) & 0x7FFF_FFFF or 1
    return candidate


def _advisory_key(experiment_id: str) -> int:
    return int(hashlib.sha256(experiment_id.encode()).hexdigest()[:15], 16)


def _candidate_alias(index: int) -> str:
    value = index
    letters = ""
    while True:
        letters = chr(ord("A") + value % 26) + letters
        value = value // 26 - 1
        if value < 0:
            return f"candidate-{letters}"


def _str(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing string field: {key}")
    return value


def _int(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Missing integer field: {key}")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _list_of_dict(payload: JsonObject, key: str) -> list[JsonObject]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Missing object list field: {key}")
    return cast(list[JsonObject], value)


def _video_review_results(
    reviews: list[tuple[EvaluationReviewModel, str, str, int]],
    candidate_map: dict[str, EvaluationCandidateModel],
    *,
    unblind: bool,
) -> list[JsonObject]:
    results: list[JsonObject] = []
    for review, candidate_id, blind_run_id, video_id in reviews:
        candidate = candidate_map[candidate_id]
        item: JsonObject = {
            "videoId": video_id,
            "stage": candidate.stage,
            "candidateAlias": candidate.blind_alias,
            "blindRunId": blind_run_id,
            "scores": review.scores_json,
            "totalScore": review.total_score,
        }
        if unblind:
            item["candidateKey"] = candidate.candidate_key
        results.append(item)
    results.sort(
        key=lambda item: (
            cast(int, item["videoId"]),
            str(item["stage"]),
            str(item["candidateAlias"]),
        )
    )
    return results
