from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Table, UniqueConstraint, case, distinct, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.domains.ops.exceptions import OpsPersistenceError
from codex_sdk_cli.domains.ops.ports import (
    OpsChannelRecord,
    OpsRecentFailureRecord,
    OpsRepositoryPort,
    OpsSchemaColumnRecord,
    OpsSchemaForeignKeyConstraintRecord,
    OpsSchemaGraphRecord,
    OpsSchemaIndexRecord,
    OpsSchemaRelationKind,
    OpsSchemaRelationRecord,
    OpsSchemaTableRecord,
    OpsSchemaUniqueConstraintRecord,
    OpsStatusCountRecord,
    OpsSummaryCountsRecord,
    OpsVideoDetailRecord,
    OpsVideoListQuery,
    OpsVideoListResult,
    OpsVideoRecord,
    OpsVideoTaskListQuery,
    OpsVideoTaskListResult,
    OpsVideoTaskRecord,
)
from codex_sdk_cli.domains.video_tasks.constants import TRANSCRIPT_COLLECT_TASK_NAME
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database import models as database_models
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.pipeline_jobs.repository import (
    PipelineJobAttemptModel,
    PipelineJobModel,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.youtube_transcripts.repository import YouTubeTranscriptRecordModel


class SqlAlchemyOpsRepository(OpsRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_summary_counts(self) -> OpsSummaryCountsRecord:
        try:
            streamers = await self._count_rows(StreamerModel)
            channels = await self._count_rows(ChannelModel)
            videos = await self._count_rows(VideoModel)
            transcripts = await self._count_rows(YouTubeTranscriptRecordModel)
            video_tasks = await self._count_by_status(VideoTaskModel)
            pipeline_jobs = await self._count_by_status(PipelineJobModel)
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc
        return OpsSummaryCountsRecord(
            streamers=streamers,
            channels=channels,
            videos=videos,
            transcripts=transcripts,
            video_tasks=tuple(video_tasks),
            pipeline_jobs=tuple(pipeline_jobs),
        )

    @override
    async def list_recent_failures(self, *, limit: int) -> list[OpsRecentFailureRecord]:
        try:
            latest_attempt = (
                select(
                    PipelineJobAttemptModel.job_id.label("job_id"),
                    func.max(PipelineJobAttemptModel.id).label("attempt_id"),
                )
                .group_by(PipelineJobAttemptModel.job_id)
                .subquery()
            )
            job_rows = (
                await self._session.execute(
                    select(PipelineJobModel, PipelineJobAttemptModel)
                    .outerjoin(latest_attempt, latest_attempt.c.job_id == PipelineJobModel.id)
                    .outerjoin(
                        PipelineJobAttemptModel,
                        PipelineJobAttemptModel.id == latest_attempt.c.attempt_id,
                    )
                    .where(PipelineJobModel.status == "failed")
                    .order_by(PipelineJobModel.updated_at.desc(), PipelineJobModel.id.desc())
                    .limit(limit)
                )
            ).all()
            task_rows = (
                await self._session.execute(
                    select(VideoTaskModel, VideoModel)
                    .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                    .where(VideoTaskModel.status.in_(("failed", "timed_out")))
                    .order_by(VideoTaskModel.updated_at.desc(), VideoTaskModel.id.desc())
                    .limit(limit)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        failures = [
            OpsRecentFailureRecord(
                kind="pipeline_job",
                id=job.id,
                status=job.status,
                label=f"{job.step} #{job.id}",
                error_type=attempt.error_type if attempt is not None else None,
                error_message=attempt.error_message if attempt is not None else None,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            for job, attempt in job_rows
        ]
        failures.extend(
            OpsRecentFailureRecord(
                kind="video_task",
                id=task.id,
                status=task.status,
                label=f"{task.task_name} {video.youtube_video_id}",
                error_type=task.error_type,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task, video in task_rows
        )
        return sorted(failures, key=lambda item: (item.updated_at, item.id), reverse=True)[
            :limit
        ]

    @override
    async def list_channels(self) -> list[OpsChannelRecord]:
        try:
            rows = (
                await self._session.execute(
                    select(
                        ChannelModel,
                        StreamerModel.name.label("streamer_name"),
                        func.count(distinct(VideoModel.id)).label("video_count"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        (
                                            VideoTaskModel.task_name
                                            == TRANSCRIPT_COLLECT_TASK_NAME
                                        )
                                        & (VideoTaskModel.status == "succeeded"),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("transcript_succeeded_count"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        (
                                            VideoTaskModel.task_name
                                            == TRANSCRIPT_COLLECT_TASK_NAME
                                        )
                                        & (VideoTaskModel.status == "no_transcript"),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("task_no_transcript_count"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        VideoTaskModel.status.in_(("failed", "timed_out")),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("task_failed_count"),
                        func.coalesce(
                            func.sum(case((VideoTaskModel.status == "running", 1), else_=0)),
                            0,
                        ).label("task_running_count"),
                        func.max(VideoModel.published_at).label("latest_video_published_at"),
                        func.max(VideoTaskModel.updated_at).label("latest_task_updated_at"),
                    )
                    .join(StreamerModel, ChannelModel.streamer_id == StreamerModel.id)
                    .outerjoin(VideoModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(VideoTaskModel, VideoTaskModel.video_id == VideoModel.id)
                    .group_by(ChannelModel.id, StreamerModel.name)
                    .order_by(ChannelModel.id.asc())
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc
        return [
            OpsChannelRecord(
                channel_id=channel.id,
                streamer_id=channel.streamer_id,
                streamer_name=streamer_name,
                handle=channel.handle,
                name=channel.name,
                youtube_channel_id=channel.youtube_channel_id,
                uploads_playlist_id=channel.uploads_playlist_id,
                video_count=video_count,
                transcript_succeeded_count=transcript_succeeded_count,
                task_no_transcript_count=task_no_transcript_count,
                task_failed_count=task_failed_count,
                task_running_count=task_running_count,
                latest_video_published_at=latest_video_published_at,
                latest_task_updated_at=latest_task_updated_at,
            )
            for (
                channel,
                streamer_name,
                video_count,
                transcript_succeeded_count,
                task_no_transcript_count,
                task_failed_count,
                task_running_count,
                latest_video_published_at,
                latest_task_updated_at,
            ) in rows
        ]

    @override
    async def list_videos(self, query: OpsVideoListQuery) -> OpsVideoListResult:
        latest_task = self._latest_task_subquery()
        task_alias = VideoTaskModel
        conditions = []
        if query.channel_id is not None:
            conditions.append(VideoModel.channel_id == query.channel_id)
        if query.task_status is not None:
            conditions.append(task_alias.status == query.task_status)
        if query.search is not None:
            like = f"%{query.search}%"
            conditions.append(
                or_(
                    VideoModel.title.ilike(like),
                    VideoModel.youtube_video_id.ilike(like),
                )
            )

        base = (
            select(VideoModel.id)
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .outerjoin(latest_task, latest_task.c.video_id == VideoModel.id)
            .outerjoin(task_alias, task_alias.id == latest_task.c.task_id)
        )
        if conditions:
            base = base.where(*conditions)

        try:
            total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
            rows = (
                await self._session.execute(
                    select(VideoModel, ChannelModel.name, task_alias)
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(latest_task, latest_task.c.video_id == VideoModel.id)
                    .outerjoin(task_alias, task_alias.id == latest_task.c.task_id)
                    .where(*conditions)
                    .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
                    .limit(query.limit)
                    .offset(query.offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        return OpsVideoListResult(
            items=tuple(
                OpsVideoRecord(
                    video_id=video.id,
                    channel_id=video.channel_id,
                    channel_name=channel_name,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    published_at=video.published_at,
                    duration=video.duration,
                    thumbnail_url=video.thumbnail_url,
                    latest_task_id=task.id if task is not None else None,
                    latest_task_name=task.task_name if task is not None else None,
                    latest_task_status=task.status if task is not None else None,
                    latest_task_updated_at=task.updated_at if task is not None else None,
                    transcript_id=(
                        task.output_transcript_id if task is not None else None
                    ),
                )
                for video, channel_name, task in rows
            ),
            total=total or 0,
        )

    @override
    async def get_video_detail(self, video_id: int) -> OpsVideoDetailRecord | None:
        latest_task = self._latest_task_subquery()
        task_alias = VideoTaskModel
        try:
            row = (
                await self._session.execute(
                    select(VideoModel, ChannelModel.name, task_alias)
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(latest_task, latest_task.c.video_id == VideoModel.id)
                    .outerjoin(task_alias, task_alias.id == latest_task.c.task_id)
                    .where(VideoModel.id == video_id)
                )
            ).first()
            if row is None:
                return None

            video, channel_name, latest_task_model = row
            task_rows = (
                await self._session.scalars(
                    select(VideoTaskModel)
                    .where(VideoTaskModel.video_id == video.id)
                    .order_by(VideoTaskModel.id.desc())
                )
            ).all()
            transcript_rows = (
                await self._session.scalars(
                    select(YouTubeTranscriptRecordModel)
                    .where(
                        YouTubeTranscriptRecordModel.video_id
                        == video.youtube_video_id
                    )
                    .order_by(YouTubeTranscriptRecordModel.id.desc())
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        return OpsVideoDetailRecord(
            video_id=video.id,
            channel_id=video.channel_id,
            channel_name=channel_name,
            youtube_video_id=video.youtube_video_id,
            title=video.title,
            description=video.description,
            published_at=video.published_at,
            duration=video.duration,
            thumbnail_url=video.thumbnail_url,
            source_listing_api_call_id=video.source_listing_api_call_id,
            source_details_api_call_id=video.source_details_api_call_id,
            source_job_id=video.source_job_id,
            created_at=video.created_at,
            updated_at=video.updated_at,
            latest_task_id=latest_task_model.id if latest_task_model is not None else None,
            latest_task_name=(
                latest_task_model.task_name if latest_task_model is not None else None
            ),
            latest_task_status=(
                latest_task_model.status if latest_task_model is not None else None
            ),
            latest_task_updated_at=(
                latest_task_model.updated_at if latest_task_model is not None else None
            ),
            transcript_id=(
                latest_task_model.output_transcript_id
                if latest_task_model is not None
                else None
            ),
            tasks=tuple(
                _ops_video_task_record(
                    task=task,
                    video=video,
                    channel_name=channel_name,
                )
                for task in task_rows
            ),
            transcripts=tuple(_transcript_record(row) for row in transcript_rows),
        )

    @override
    async def list_video_tasks(
        self,
        query: OpsVideoTaskListQuery,
    ) -> OpsVideoTaskListResult:
        conditions = []
        if query.channel_id is not None:
            conditions.append(VideoModel.channel_id == query.channel_id)
        if query.task_name is not None:
            conditions.append(VideoTaskModel.task_name == query.task_name)
        if query.status is not None:
            conditions.append(VideoTaskModel.status == query.status)
        base = (
            select(VideoTaskModel.id)
            .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .where(*conditions)
        )
        try:
            total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
            rows = (
                await self._session.execute(
                    select(VideoTaskModel, VideoModel, ChannelModel.name)
                    .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .where(*conditions)
                    .order_by(VideoTaskModel.id.desc())
                    .limit(query.limit)
                    .offset(query.offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        return OpsVideoTaskListResult(
            items=tuple(
                _ops_video_task_record(
                    task=task,
                    video=video,
                    channel_name=channel_name,
                )
                for task, video, channel_name in rows
            ),
            total=total or 0,
        )

    @override
    async def get_schema_graph(self) -> OpsSchemaGraphRecord:
        _ = database_models
        tables = list(Base.metadata.sorted_tables)
        return OpsSchemaGraphRecord(
            tables=tuple(
                OpsSchemaTableRecord(
                    id=table.name,
                    name=table.name,
                    columns=tuple(
                        OpsSchemaColumnRecord(
                            id=f"{table.name}.{column.name}",
                            name=column.name,
                            type=_column_type(column),
                            nullable=bool(column.nullable),
                            primary_key=column.primary_key,
                            unique=(
                                column.unique
                                or column.name in _unique_column_names(table)
                            ),
                            index=(
                                column.index
                                or column.name in _index_column_names(table)
                            ),
                            default=_column_default(column),
                            foreign_keys=tuple(
                                sorted(
                                    f"{foreign_key.column.table.name}."
                                    f"{foreign_key.column.name}"
                                    for foreign_key in column.foreign_keys
                                )
                            ),
                            constraint_names=tuple(
                                _column_constraint_names(table, column)
                            ),
                        )
                        for column in table.columns
                    ),
                    indexes=tuple(_table_indexes(table)),
                    unique_constraints=tuple(_table_unique_constraints(table)),
                    foreign_key_constraints=tuple(
                        _table_foreign_key_constraints(table)
                    ),
                )
                for table in tables
            ),
            relations=tuple(
                OpsSchemaRelationRecord(
                    id=(
                        f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                        f"->{table.name}.{column.name}"
                    ),
                    constraint_name=_constraint_name(foreign_key.constraint),
                    source_table=foreign_key.column.table.name,
                    source_column=foreign_key.column.name,
                    target_table=table.name,
                    target_column=column.name,
                    source_nullable=bool(column.nullable),
                    target_primary_key=column.primary_key,
                    relation_kind=_relation_kind(table, column),
                )
                for table in tables
                for column in table.columns
                for foreign_key in column.foreign_keys
            ),
        )

    async def _count_rows(self, model: type[object]) -> int:
        count = await self._session.scalar(select(func.count()).select_from(model))
        return count or 0

    async def _count_by_status(
        self,
        model: type[VideoTaskModel] | type[PipelineJobModel],
    ) -> list[OpsStatusCountRecord]:
        status_column = model.status
        rows = (
            await self._session.execute(
                select(status_column, func.count())
                .select_from(model)
                .group_by(status_column)
                .order_by(status_column.asc())
            )
        ).all()
        return [OpsStatusCountRecord(status=status, count=count) for status, count in rows]

    def _latest_task_subquery(self):
        return (
            select(
                VideoTaskModel.video_id.label("video_id"),
                func.max(VideoTaskModel.id).label("task_id"),
            )
            .group_by(VideoTaskModel.video_id)
            .subquery()
        )


def _column_type(column: Column[Any]) -> str:
    return str(column.type).replace("DATETIME", "DateTime")


def _column_default(column: Column[Any]) -> str | None:
    if column.server_default is not None:
        return str(getattr(column.server_default, "arg", column.server_default))
    if column.default is not None:
        return str(getattr(column.default, "arg", column.default))
    return None


def _index_column_names(table: Table) -> set[str]:
    return {column.name for index in table.indexes for column in index.columns}


def _unique_column_names(table: Table) -> set[str]:
    return {
        column.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }


def _table_indexes(table: Table) -> list[OpsSchemaIndexRecord]:
    return [
        OpsSchemaIndexRecord(
            name=_constraint_name(index),
            column_names=tuple(column.name for column in index.columns),
            unique=index.unique,
        )
        for index in sorted(table.indexes, key=_constraint_name)
    ]


def _table_unique_constraints(table: Table) -> list[OpsSchemaUniqueConstraintRecord]:
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    return [
        OpsSchemaUniqueConstraintRecord(
            name=_constraint_name(constraint),
            column_names=tuple(column.name for column in constraint.columns),
        )
        for constraint in sorted(constraints, key=_constraint_name)
    ]


def _table_foreign_key_constraints(
    table: Table,
) -> list[OpsSchemaForeignKeyConstraintRecord]:
    return [
        OpsSchemaForeignKeyConstraintRecord(
            name=_constraint_name(constraint),
            column_names=tuple(element.parent.name for element in constraint.elements),
            target_table=constraint.elements[0].column.table.name,
            target_column_names=tuple(element.column.name for element in constraint.elements),
        )
        for constraint in sorted(table.foreign_key_constraints, key=_constraint_name)
        if constraint.elements
    ]


def _column_constraint_names(table: Table, column: Column[Any]) -> list[str]:
    names: set[str] = set()
    if column.primary_key:
        names.add(_constraint_name(table.primary_key))
    names.update(
        _constraint_name(constraint)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and column.name in constraint.columns
    )
    names.update(
        _constraint_name(constraint)
        for constraint in table.foreign_key_constraints
        if column.name in constraint.columns
    )
    names.update(
        _constraint_name(index)
        for index in table.indexes
        if column.name in index.columns
    )
    return sorted(names)


def _relation_kind(table: Table, column: Column[Any]) -> OpsSchemaRelationKind:
    is_optional = bool(column.nullable)
    is_single_unique = _is_single_column_unique(table, column)
    if is_optional and is_single_unique:
        return "optional_one_to_one"
    if is_optional:
        return "optional_one_to_many"
    if is_single_unique:
        return "one_to_one"
    return "one_to_many"


def _is_single_column_unique(table: Table, column: Column[Any]) -> bool:
    if column.primary_key or column.unique:
        return True
    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint):
            continue
        constraint_column_names = [item.name for item in constraint.columns]
        if constraint_column_names == [column.name]:
            return True
    return any(
        index.unique and [item.name for item in index.columns] == [column.name]
        for index in table.indexes
    )


def _constraint_name(item: Any) -> str:
    return str(item.name or "unnamed")


def _ops_video_task_record(
    *,
    task: VideoTaskModel,
    video: VideoModel,
    channel_name: str,
) -> OpsVideoTaskRecord:
    return OpsVideoTaskRecord(
        video_task_id=task.id,
        video_id=task.video_id,
        channel_id=video.channel_id,
        channel_name=channel_name,
        youtube_video_id=video.youtube_video_id,
        task_name=task.task_name,
        task_version=task.task_version,
        status=task.status,
        worker_id=task.worker_id,
        timeout_seconds=task.timeout_seconds,
        job_id=task.job_id,
        job_attempt_id=task.job_attempt_id,
        output_transcript_id=task.output_transcript_id,
        output_json=task.output_json,
        error_type=task.error_type,
        error_message=task.error_message,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _transcript_record(
    model: YouTubeTranscriptRecordModel,
) -> YouTubeTranscriptMetadataRecord:
    return YouTubeTranscriptMetadataRecord(
        id=model.id,
        video_id=model.video_id,
        language=model.language,
        language_code=model.language_code,
        is_generated=model.is_generated,
        requested_languages=tuple(model.requested_languages),
        preserve_formatting=model.preserve_formatting,
        storage_bucket=model.storage_bucket,
        storage_object_name=model.storage_object_name,
        storage_uri=model.storage_uri,
        response_sha256=model.response_sha256,
        segment_count=model.segment_count,
        text_length=model.text_length,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
