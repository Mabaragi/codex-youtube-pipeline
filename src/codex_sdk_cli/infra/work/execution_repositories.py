from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import (
    JsonObject,
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskStatus,
    VideoTaskWithVideoRecord,
)
from codex_sdk_cli.domains.work.models import WorkItemStatus
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository, VideoModel

from .models import WorkAttemptModel, WorkItemModel


class WorkVideoTaskRepository(VideoTaskRepositoryPort):
    """Expose unified work rows to processing code that still uses task-shaped records."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        current_work_item_id: int | None = None,
    ) -> None:
        self._session = session
        self._current_work_item_id = current_work_item_id

    @override
    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        model = await self._session.get(WorkItemModel, task_id)
        return await self._record(model)

    @override
    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        model = await self._session.scalar(
            select(WorkItemModel).where(
                WorkItemModel.subject_type == "video",
                WorkItemModel.subject_id == video_id,
                WorkItemModel.task_type == task_name,
                WorkItemModel.task_version == task_version,
                WorkItemModel.input_hash == input_hash,
            )
        )
        return await self._record(model)

    @override
    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        existing = await self.get_task_for_input(
            video_id=task.video_id,
            task_name=task.task_name,
            task_version=task.task_version,
            input_hash=task.input_hash,
        )
        if existing is not None:
            return existing
        now = _now()
        model = WorkItemModel(
            task_type=task.task_name,
            subject_type="video",
            subject_id=task.video_id,
            external_key=await self._youtube_video_id(task.video_id),
            task_version=task.task_version,
            input_hash=task.input_hash,
            idempotency_key=(
                f"{task.task_name}:video:{task.video_id}:{task.task_version}:{task.input_hash}"
            ),
            execution_mode="inline" if task.task_name == "archive_publish" else "worker",
            status=_work_status(task.status),
            outcome_code=_outcome_code(task.status),
            priority=0,
            timeout_seconds=task.timeout_seconds,
            input_json=task.input_json or {},
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._session.flush()
        record = await self._record(model)
        if record is None:
            raise RuntimeError("Created work item was not found.")
        return record

    @override
    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        statement = (
            select(WorkItemModel, VideoModel.youtube_video_id)
            .join(VideoModel, VideoModel.id == WorkItemModel.subject_id)
            .where(
                WorkItemModel.subject_type == "video",
                VideoModel.channel_id == query.channel_id,
            )
            .order_by(WorkItemModel.id.desc())
            .offset(query.offset)
            .limit(query.limit)
        )
        if query.task_name is not None:
            statement = statement.where(WorkItemModel.task_type == query.task_name)
        if query.status is not None:
            if query.status == "no_transcript":
                statement = statement.where(
                    WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                    WorkItemModel.outcome_code == "no_transcript",
                )
            else:
                statement = statement.where(
                    WorkItemModel.status == _work_status(query.status)
                )
        rows = (await self._session.execute(statement)).all()
        results: list[VideoTaskListRecord] = []
        for model, youtube_video_id in rows:
            record = await self._record(model)
            if record is not None:
                results.append(
                    VideoTaskListRecord(task=record, youtube_video_id=youtube_video_id)
                )
        return results

    @override
    async def list_latest_succeeded_tasks(
        self,
        *,
        task_name: str,
        channel_id: int | None,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        latest = (
            select(
                WorkItemModel.subject_id.label("video_id"),
                func.max(WorkItemModel.id).label("work_item_id"),
            )
            .where(
                WorkItemModel.subject_type == "video",
                WorkItemModel.task_type == task_name,
                WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                WorkItemModel.outcome_code.is_(None),
            )
            .group_by(WorkItemModel.subject_id)
            .subquery()
        )
        statement = (
            select(WorkItemModel, VideoModel)
            .join(latest, latest.c.work_item_id == WorkItemModel.id)
            .join(VideoModel, VideoModel.id == latest.c.video_id)
            .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
            .limit(limit)
        )
        if channel_id is not None:
            statement = statement.where(VideoModel.channel_id == channel_id)
        rows = (await self._session.execute(statement)).all()
        video_repository = SqlAlchemyVideoRepository(self._session)
        results: list[VideoTaskWithVideoRecord] = []
        for model, video_model in rows:
            record = await self._record(model)
            video = await video_repository.get_video(video_model.id)
            if record is not None and video is not None:
                results.append(VideoTaskWithVideoRecord(task=record, video=video))
        return results

    @override
    async def list_no_transcript_tasks_due_for_recheck(
        self,
        *,
        task_name: str,
        completed_before: datetime,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        statement = (
            select(WorkItemModel)
            .where(
                WorkItemModel.subject_type == "video",
                WorkItemModel.task_type == task_name,
                WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                WorkItemModel.outcome_code == "no_transcript",
                WorkItemModel.completed_at <= completed_before,
            )
            .order_by(WorkItemModel.completed_at, WorkItemModel.id)
            .limit(limit)
        )
        models = list((await self._session.scalars(statement)).all())
        video_repository = SqlAlchemyVideoRepository(self._session)
        results: list[VideoTaskWithVideoRecord] = []
        for model in models:
            if model.subject_id is None:
                continue
            record = await self._record(model)
            video = await video_repository.get_video(model.subject_id)
            if record is not None and video is not None:
                results.append(VideoTaskWithVideoRecord(task=record, video=video))
        return results

    @override
    async def get_latest_succeeded_task_for_video(
        self,
        *,
        video_id: int,
        task_name: str,
    ) -> VideoTaskRecord | None:
        model = await self._session.scalar(
            select(WorkItemModel)
            .where(
                WorkItemModel.subject_type == "video",
                WorkItemModel.subject_id == video_id,
                WorkItemModel.task_type == task_name,
                WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                WorkItemModel.outcome_code.is_(None),
            )
            .order_by(WorkItemModel.id.desc())
            .limit(1)
        )
        return await self._record(model)

    @override
    async def get_latest_task_for_video(self, video_id: int) -> VideoTaskRecord | None:
        model = await self._session.scalar(
            select(WorkItemModel)
            .where(
                WorkItemModel.subject_type == "video",
                WorkItemModel.subject_id == video_id,
            )
            .order_by(WorkItemModel.id.desc())
            .limit(1)
        )
        return await self._record(model)

    @override
    async def count_running(self, *, task_name: str) -> int:
        return (
            await self._session.scalar(
                select(func.count()).select_from(WorkItemModel).where(
                    WorkItemModel.task_type == task_name,
                    WorkItemModel.status == WorkItemStatus.RUNNING.value,
                )
            )
            or 0
        )

    @override
    async def claim_next_pending_task(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        model = await self._session.scalar(
            select(WorkItemModel)
            .where(
                WorkItemModel.task_type == task_name,
                WorkItemModel.status == WorkItemStatus.PENDING.value,
            )
            .order_by(WorkItemModel.priority.desc(), WorkItemModel.id)
            .limit(1)
        )
        return await self._claim(model, worker_id)

    @override
    async def claim_pending_task(
        self,
        task_id: int,
        *,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        model = await self._session.get(WorkItemModel, task_id)
        return await self._claim(model, worker_id)

    @override
    async def claim_next_pending_task_excluding_running_video(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        running_videos = select(WorkItemModel.subject_id).where(
            WorkItemModel.task_type == task_name,
            WorkItemModel.status == WorkItemStatus.RUNNING.value,
        )
        model = await self._session.scalar(
            select(WorkItemModel)
            .where(
                WorkItemModel.task_type == task_name,
                WorkItemModel.status == WorkItemStatus.PENDING.value,
                WorkItemModel.subject_id.not_in(running_videos),
            )
            .order_by(WorkItemModel.priority.desc(), WorkItemModel.id)
            .limit(1)
        )
        return await self._claim(model, worker_id)

    @override
    async def reset_task_to_pending(
        self,
        task_id: int,
        *,
        timeout_seconds: int,
        input_json: JsonObject,
    ) -> VideoTaskRecord:
        model = await self._required(task_id)
        model.status = WorkItemStatus.PENDING.value
        model.outcome_code = None
        model.timeout_seconds = timeout_seconds
        model.input_json = input_json
        model.output_json = None
        model.output_transcript_id = None
        model.error_code = None
        model.error_type = None
        model.error_message = None
        model.lease_owner = None
        model.lease_expires_at = None
        model.started_at = None
        model.completed_at = None
        model.updated_at = _now()
        await self._session.flush()
        return await self._required_record(model)

    @override
    async def attach_task_execution(
        self,
        task_id: int,
        *,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        del job_id, job_attempt_id
        return await self._required_record(await self._required(task_id))

    @override
    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        del job_id, job_attempt_id
        model = await self._required(task_id)
        if task_id == self._current_work_item_id:
            return replace(
                await self._required_record(model),
                status="running",
                worker_id=worker_id,
                timeout_seconds=timeout_seconds,
                started_at=model.started_at or _now(),
                updated_at=_now(),
            )
        model.status = WorkItemStatus.RUNNING.value
        model.lease_owner = worker_id
        model.timeout_seconds = timeout_seconds
        model.started_at = model.started_at or _now()
        model.updated_at = _now()
        await self._session.flush()
        return await self._required_record(model)

    @override
    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        return await self._complete(
            task_id,
            status=WorkItemStatus.SUCCEEDED.value,
            output_transcript_id=output_transcript_id,
            output_json=output_json,
        )

    @override
    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return await self._fail(task_id, error_type, error_message, output_json, False)

    @override
    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return await self._fail(task_id, "TimeoutError", error_message, output_json, True)

    @override
    async def mark_task_no_transcript(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        model = await self._required(task_id)
        if task_id == self._current_work_item_id:
            now = _now()
            return replace(
                await self._required_record(model),
                status="no_transcript",
                worker_id=None,
                output_json=output_json,
                error_type="YouTubeTranscriptNotFound",
                error_message=error_message,
                completed_at=now,
                updated_at=now,
            )
        model.status = WorkItemStatus.SUCCEEDED.value
        model.outcome_code = "no_transcript"
        model.error_type = "YouTubeTranscriptNotFound"
        model.error_message = error_message
        model.output_json = output_json
        model.completed_at = _now()
        model.updated_at = _now()
        await self._session.flush()
        return await self._required_record(model)

    @override
    async def cancel_pending_tasks(
        self,
        task_ids: list[int],
        *,
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        if not task_ids:
            return []
        await self._session.execute(
            update(WorkItemModel)
            .where(
                WorkItemModel.id.in_(task_ids),
                WorkItemModel.status == WorkItemStatus.PENDING.value,
            )
            .values(
                status=WorkItemStatus.CANCELED.value,
                outcome_code="canceled",
                error_type=error_type,
                error_message=error_message,
                completed_at=_now(),
                updated_at=_now(),
            )
        )
        return [
            record
            for task_id in task_ids
            if (record := await self.get_task(task_id)) is not None
        ]

    @override
    async def cancel_pending_tasks_for_video(
        self,
        *,
        video_id: int,
        task_names: tuple[str, ...],
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        ids = list(
            (
                await self._session.scalars(
                    select(WorkItemModel.id).where(
                        WorkItemModel.subject_type == "video",
                        WorkItemModel.subject_id == video_id,
                        WorkItemModel.task_type.in_(task_names),
                        WorkItemModel.status == WorkItemStatus.PENDING.value,
                    )
                )
            ).all()
        )
        return await self.cancel_pending_tasks(
            ids,
            error_type=error_type,
            error_message=error_message,
        )

    async def _claim(
        self,
        model: WorkItemModel | None,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        if model is None or model.status != WorkItemStatus.PENDING.value:
            return None
        model.status = WorkItemStatus.RUNNING.value
        model.lease_owner = worker_id
        model.started_at = model.started_at or _now()
        model.updated_at = _now()
        await self._session.flush()
        return await self._record(model)

    async def _complete(
        self,
        task_id: int,
        *,
        status: str,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        model = await self._required(task_id)
        if task_id == self._current_work_item_id:
            now = _now()
            return replace(
                await self._required_record(model),
                status=cast(VideoTaskStatus, status),
                worker_id=None,
                output_transcript_id=output_transcript_id,
                output_json=output_json,
                error_type=None,
                error_message=None,
                completed_at=now,
                updated_at=now,
            )
        model.status = status
        model.outcome_code = None
        model.output_transcript_id = output_transcript_id
        model.output_json = output_json
        model.error_code = None
        model.error_type = None
        model.error_message = None
        model.lease_owner = None
        model.lease_expires_at = None
        model.completed_at = _now()
        model.updated_at = _now()
        await self._session.flush()
        return await self._required_record(model)

    async def _fail(
        self,
        task_id: int,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None,
        timed_out: bool,
    ) -> VideoTaskRecord:
        model = await self._required(task_id)
        if task_id == self._current_work_item_id:
            now = _now()
            return replace(
                await self._required_record(model),
                status="timed_out" if timed_out else "failed",
                worker_id=None,
                output_json=output_json,
                error_type=error_type,
                error_message=error_message,
                completed_at=now,
                updated_at=now,
            )
        model.status = (
            WorkItemStatus.TIMED_OUT.value if timed_out else WorkItemStatus.FAILED.value
        )
        model.error_code = "work.execution_failed"
        model.error_type = error_type
        model.error_message = error_message
        model.output_json = output_json
        model.lease_owner = None
        model.lease_expires_at = None
        model.completed_at = _now()
        model.updated_at = _now()
        await self._session.flush()
        return await self._required_record(model)

    async def _required(self, task_id: int) -> WorkItemModel:
        model = await self._session.get(WorkItemModel, task_id)
        if model is None:
            raise LookupError(f"Work item {task_id} was not found.")
        return model

    async def _required_record(self, model: WorkItemModel) -> VideoTaskRecord:
        record = await self._record(model)
        if record is None:
            raise RuntimeError("Work item cannot be represented as a video task.")
        return record

    async def _record(self, model: WorkItemModel | None) -> VideoTaskRecord | None:
        if model is None or model.subject_type != "video" or model.subject_id is None:
            return None
        attempt_id = await self._session.scalar(
            select(WorkAttemptModel.id)
            .where(WorkAttemptModel.work_item_id == model.id)
            .order_by(WorkAttemptModel.attempt_no.desc())
            .limit(1)
        )
        return VideoTaskRecord(
            id=model.id,
            video_id=model.subject_id,
            task_name=model.task_type,
            task_version=model.task_version,
            input_hash=model.input_hash,
            status=_video_task_status(model),
            worker_id=model.lease_owner,
            timeout_seconds=model.timeout_seconds,
            job_id=model.id if attempt_id is not None else None,
            job_attempt_id=attempt_id,
            output_transcript_id=model.output_transcript_id,
            output_json=model.output_json,
            error_type=model.error_type,
            error_message=model.error_message,
            started_at=model.started_at,
            completed_at=model.completed_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
            input_json={**model.input_json, "inputHash": model.input_hash},
        )

    async def _youtube_video_id(self, video_id: int) -> str | None:
        return await self._session.scalar(
            select(VideoModel.youtube_video_id).where(VideoModel.id == video_id)
        )


class WorkPipelineJobRepository(PipelineJobRepositoryPort):
    """Map job-shaped orchestration calls onto the current unified work execution."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        current_work_item_id: int | None = None,
        current_work_attempt_id: int | None = None,
    ) -> None:
        self._session = session
        self._current_work_item_id = current_work_item_id
        self._current_work_attempt_id = current_work_attempt_id

    @override
    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        if self._current_work_item_id is not None:
            return await self._required_job(self._current_work_item_id)
        now = _now()
        model = WorkItemModel(
            task_type=job.step,
            subject_type=job.subject_type or "system",
            subject_id=job.subject_id,
            external_key=job.external_key,
            task_version="v1",
            input_hash=job.input_hash,
            idempotency_key=f"compat-job:{uuid4().hex}",
            execution_mode=(
                "inline"
                if job.step in {"channel_resolve", "video_collect", "archive_publish"}
                else "worker"
            ),
            status=_work_job_status(job.status),
            priority=0,
            timeout_seconds=_timeout(job.input_json),
            input_json=job.input_json,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._session.flush()
        return _job_record(model)

    @override
    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        model = await self._session.get(WorkItemModel, job_id)
        return _job_record(model) if model is not None else None

    @override
    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        statement = select(WorkItemModel).order_by(WorkItemModel.id.desc()).limit(query.limit)
        if query.cursor is not None:
            statement = statement.where(WorkItemModel.id < query.cursor)
        if query.step is not None:
            statement = statement.where(WorkItemModel.task_type == query.step)
        if query.status is not None:
            statement = statement.where(WorkItemModel.status == _work_job_status(query.status))
        if query.subject_type is not None:
            statement = statement.where(WorkItemModel.subject_type == query.subject_type)
        if query.subject_id is not None:
            statement = statement.where(WorkItemModel.subject_id == query.subject_id)
        if query.external_key is not None:
            statement = statement.where(WorkItemModel.external_key == query.external_key)
        if query.channel_id is not None:
            video_ids = select(VideoModel.id).where(VideoModel.channel_id == query.channel_id)
            statement = statement.where(
                or_(
                    (WorkItemModel.subject_type == "channel")
                    & (WorkItemModel.subject_id == query.channel_id),
                    (WorkItemModel.subject_type == "video")
                    & WorkItemModel.subject_id.in_(video_ids),
                    WorkItemModel.input_json["channelId"].as_integer()
                    == query.channel_id,
                    exists(
                        select(ChannelModel.id).where(
                            ChannelModel.id == query.channel_id,
                            ChannelModel.source_job_id == WorkItemModel.id,
                        )
                    ),
                    exists(
                        select(VideoModel.id).where(
                            VideoModel.channel_id == query.channel_id,
                            VideoModel.source_job_id == WorkItemModel.id,
                        )
                    ),
                    exists(
                        select(WorkAttemptModel.id).where(
                            WorkAttemptModel.work_item_id == WorkItemModel.id,
                            WorkAttemptModel.output_json["channelId"].as_integer()
                            == query.channel_id,
                        )
                    ),
                )
            )
        models = list((await self._session.scalars(statement)).all())
        results: list[PipelineJobSummaryRecord] = []
        for model in models:
            attempts = await self._attempts(model.id)
            latest = attempts[-1] if attempts else None
            results.append(
                PipelineJobSummaryRecord(
                    job=_job_record(model),
                    latest_attempt_id=latest.id if latest else None,
                    latest_attempt_status=latest.status if latest else None,
                    attempt_count=len(attempts),
                )
            )
        return results

    @override
    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        from codex_sdk_cli.infra.pipeline_jobs.repository import (
            LegacySqlAlchemyPipelineJobRepository,
        )

        return await LegacySqlAlchemyPipelineJobRepository(
            self._session
        ).get_job_detail(job_id)

    @override
    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        if self._current_work_attempt_id is not None:
            model = await self._session.get(WorkAttemptModel, self._current_work_attempt_id)
            if model is None:
                raise LookupError("Current work attempt was not found.")
            return _attempt_record(model)
        attempt_no = (
            await self._session.scalar(
                select(func.coalesce(func.max(WorkAttemptModel.attempt_no), 0)).where(
                    WorkAttemptModel.work_item_id == job_id
                )
            )
            or 0
        ) + 1
        model = WorkAttemptModel(
            work_item_id=job_id,
            attempt_no=attempt_no,
            status="running",
            worker_id=worker_id,
            started_at=_now(),
        )
        self._session.add(model)
        await self._session.flush()
        return _attempt_record(model)

    @override
    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        model = await self._required_attempt(attempt_id)
        if attempt_id == self._current_work_attempt_id:
            return replace(
                _attempt_record(model),
                status="succeeded",
                output_json=output_json,
                finished_at=_now(),
            )
        model.status = "succeeded"
        model.output_json = output_json
        model.error_code = None
        model.error_type = None
        model.error_message = None
        model.finished_at = _now()
        await self._session.flush()
        return _attempt_record(model)

    @override
    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> PipelineJobAttemptRecord:
        model = await self._required_attempt(attempt_id)
        if attempt_id == self._current_work_attempt_id:
            return replace(
                _attempt_record(model),
                status="failed",
                output_json=output_json,
                error_type=error_type,
                error_message=error_message,
                finished_at=_now(),
            )
        model.status = "failed"
        model.output_json = output_json
        model.error_code = "work.execution_failed"
        model.error_type = error_type
        model.error_message = error_message
        model.finished_at = _now()
        await self._session.flush()
        return _attempt_record(model)

    @override
    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return await self._set_job_status(job_id, WorkItemStatus.SUCCEEDED.value)

    @override
    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return await self._set_job_status(job_id, WorkItemStatus.FAILED.value)

    @override
    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        return await self._set_job_status(job_id, WorkItemStatus.RUNNING.value)

    async def _set_job_status(self, job_id: int, status: str) -> PipelineJobRecord:
        model = await self._required_model(job_id)
        if job_id == self._current_work_item_id:
            completed_at = (
                _now()
                if status in {WorkItemStatus.SUCCEEDED.value, WorkItemStatus.FAILED.value}
                else None
            )
            return replace(
                _job_record(model),
                status=cast(PipelineJobStatus, status),
                updated_at=_now(),
                completed_at=completed_at,
            )
        model.status = status
        model.updated_at = _now()
        if status in {WorkItemStatus.SUCCEEDED.value, WorkItemStatus.FAILED.value}:
            model.completed_at = _now()
        else:
            model.completed_at = None
        await self._session.flush()
        return _job_record(model)

    async def _required_job(self, job_id: int) -> PipelineJobRecord:
        return _job_record(await self._required_model(job_id))

    async def _required_model(self, job_id: int) -> WorkItemModel:
        model = await self._session.get(WorkItemModel, job_id)
        if model is None:
            raise LookupError(f"Work item {job_id} was not found.")
        return model

    async def _required_attempt(self, attempt_id: int) -> WorkAttemptModel:
        model = await self._session.get(WorkAttemptModel, attempt_id)
        if model is None:
            raise LookupError(f"Work attempt {attempt_id} was not found.")
        return model

    async def _attempts(self, work_item_id: int) -> list[PipelineJobAttemptRecord]:
        models = list(
            (
                await self._session.scalars(
                    select(WorkAttemptModel)
                    .where(WorkAttemptModel.work_item_id == work_item_id)
                    .order_by(WorkAttemptModel.attempt_no)
                )
            ).all()
        )
        return [_attempt_record(model) for model in models]


def _job_record(model: WorkItemModel) -> PipelineJobRecord:
    status = model.status
    if status in {"timed_out", "blocked"}:
        status = "failed"
    if status == "canceled":
        status = "canceled"
    return PipelineJobRecord(
        id=model.id,
        step=model.task_type,
        status=status,  # type: ignore[arg-type]
        subject_type=model.subject_type,
        subject_id=model.subject_id,
        external_key=model.external_key,
        input_json=model.input_json,
        input_hash=model.input_hash,
        parent_job_id=None,
        created_at=_aware(model.created_at),
        updated_at=_aware(model.updated_at),
        completed_at=_aware(model.completed_at) if model.completed_at is not None else None,
    )


def _attempt_record(model: WorkAttemptModel) -> PipelineJobAttemptRecord:
    status = "failed" if model.status == "timed_out" else model.status
    return PipelineJobAttemptRecord(
        id=model.id,
        job_id=model.work_item_id,
        attempt_no=model.attempt_no,
        status=status,  # type: ignore[arg-type]
        started_at=_aware(model.started_at),
        finished_at=_aware(model.finished_at) if model.finished_at is not None else None,
        worker_id=model.worker_id,
        error_type=model.error_type,
        error_message=model.error_message,
        output_json=model.output_json,
    )


def _video_task_status(model: WorkItemModel) -> VideoTaskStatus:
    if model.status == WorkItemStatus.SUCCEEDED.value and model.outcome_code == "no_transcript":
        return "no_transcript"
    if model.status == WorkItemStatus.BLOCKED.value:
        return "failed"
    return model.status  # type: ignore[return-value]


def _work_status(status: VideoTaskStatus) -> str:
    if status == "no_transcript":
        return WorkItemStatus.SUCCEEDED.value
    if status == "skipped":
        return WorkItemStatus.CANCELED.value
    return status


def _outcome_code(status: VideoTaskStatus) -> str | None:
    if status == "no_transcript":
        return "no_transcript"
    if status == "skipped":
        return "legacy_skipped"
    return None


def _work_job_status(status: str) -> str:
    return WorkItemStatus.CANCELED.value if status == "skipped" else status


def _timeout(values: JsonObject) -> int:
    value = values.get("timeoutSeconds")
    return value if isinstance(value, int) and value > 0 else 600


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
