from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Column, Table, UniqueConstraint, case, distinct, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from typing_extensions import override

from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.ops.exceptions import OpsPersistenceError
from codex_sdk_cli.domains.ops.ports import (
    OpsCandidateCategory,
    OpsCandidateListQuery,
    OpsChannelRecord,
    OpsLatestEventRecord,
    OpsMicroEventReadyCandidateListResult,
    OpsMicroEventReadyCandidateRecord,
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
    OpsStuckTaskListResult,
    OpsStuckTaskQuery,
    OpsStuckTaskRecord,
    OpsSummaryCountsRecord,
    OpsTaskSummaryRecord,
    OpsTimelineReadyCandidateListResult,
    OpsTimelineReadyCandidateRecord,
    OpsVideoCueGenerationRecord,
    OpsVideoDetailRecord,
    OpsVideoGenerationRecord,
    OpsVideoListQuery,
    OpsVideoListResult,
    OpsVideoMicroEventGenerationRecord,
    OpsVideoRecord,
    OpsVideoTaskListQuery,
    OpsVideoTaskListResult,
    OpsVideoTaskRecord,
    OpsVideoTimelineGenerationRecord,
)
from codex_sdk_cli.domains.video_tasks.constants import (
    TIMELINE_COMPOSE_TASK_NAME,
    TRANSCRIPT_COLLECT_TASK_NAME,
    TRANSCRIPT_CUE_GENERATE_TASK_NAME,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database import models as database_models
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.micro_events.repository import (
    MicroEventCandidateModel,
    MicroEventExtractionWindowModel,
)
from codex_sdk_cli.infra.operation_events.repository import OperationEventModel
from codex_sdk_cli.infra.pipeline_jobs.repository import (
    PipelineJobAttemptModel,
    PipelineJobModel,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.timelines.repository import (
    TimelineCompositionModel,
    TimelineEpisodeModel,
)
from codex_sdk_cli.infra.transcript_cues.repository import TranscriptCueModel
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
        latest_transcript = self._latest_transcript_subquery()
        cue_summary = self._cue_summary_subquery()
        latest_cue_task = self._latest_task_subquery(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME
        )
        latest_micro_task = self._latest_task_subquery(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME
        )
        latest_timeline_task = self._latest_task_subquery(
            task_name=TIMELINE_COMPOSE_TASK_NAME
        )
        micro_summary = self._micro_event_summary_subquery()
        timeline_summary = self._timeline_summary_subquery()
        task_alias = aliased(VideoTaskModel)
        cue_task_alias = aliased(VideoTaskModel)
        micro_task_alias = aliased(VideoTaskModel)
        timeline_task_alias = aliased(VideoTaskModel)
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
        if query.embed_status == "embeddable":
            conditions.append(VideoModel.is_embeddable.is_(True))
        if query.embed_status == "no_embed":
            conditions.append(VideoModel.is_embeddable.is_(False))
        if query.embed_status == "unknown":
            conditions.append(VideoModel.is_embeddable.is_(None))

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
                    select(
                        VideoModel,
                        ChannelModel.name,
                        task_alias,
                        latest_transcript.c.transcript_id,
                        cue_summary.c.cue_count,
                        cue_task_alias,
                        micro_task_alias,
                        micro_summary.c.video_task_id,
                        micro_summary.c.window_count,
                        micro_summary.c.micro_event_count,
                        timeline_task_alias,
                        timeline_summary.c.composition_id,
                        timeline_summary.c.video_task_id,
                        timeline_summary.c.episode_count,
                    )
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(latest_task, latest_task.c.video_id == VideoModel.id)
                    .outerjoin(task_alias, task_alias.id == latest_task.c.task_id)
                    .outerjoin(
                        latest_transcript,
                        latest_transcript.c.youtube_video_id
                        == VideoModel.youtube_video_id,
                    )
                    .outerjoin(
                        cue_summary,
                        cue_summary.c.transcript_id
                        == latest_transcript.c.transcript_id,
                    )
                    .outerjoin(
                        latest_cue_task,
                        latest_cue_task.c.video_id == VideoModel.id,
                    )
                    .outerjoin(
                        cue_task_alias,
                        cue_task_alias.id == latest_cue_task.c.task_id,
                    )
                    .outerjoin(
                        latest_micro_task,
                        latest_micro_task.c.video_id == VideoModel.id,
                    )
                    .outerjoin(
                        micro_task_alias,
                        micro_task_alias.id == latest_micro_task.c.task_id,
                    )
                    .outerjoin(
                        micro_summary,
                        micro_summary.c.video_id == VideoModel.id,
                    )
                    .outerjoin(
                        latest_timeline_task,
                        latest_timeline_task.c.video_id == VideoModel.id,
                    )
                    .outerjoin(
                        timeline_task_alias,
                        timeline_task_alias.id == latest_timeline_task.c.task_id,
                    )
                    .outerjoin(
                        timeline_summary,
                        timeline_summary.c.video_id == VideoModel.id,
                    )
                    .where(*conditions)
                    .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
                    .limit(query.limit)
                    .offset(query.offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        records: list[OpsVideoRecord] = []
        for row in rows:
            video = row[0]
            channel_name = row[1]
            task = cast(VideoTaskModel | None, row[2])
            transcript_id = cast(int | None, row[3])
            cue_count = cast(int | None, row[4])
            cue_task = cast(VideoTaskModel | None, row[5])
            micro_task = cast(VideoTaskModel | None, row[6])
            micro_video_task_id = cast(int | None, row[7])
            window_count = cast(int | None, row[8])
            micro_event_count = cast(int | None, row[9])
            timeline_task = cast(VideoTaskModel | None, row[10])
            composition_id = cast(int | None, row[11])
            timeline_video_task_id = cast(int | None, row[12])
            episode_count = cast(int | None, row[13])
            records.append(
                OpsVideoRecord(
                    video_id=video.id,
                    channel_id=video.channel_id,
                    channel_name=channel_name,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    published_at=video.published_at,
                    duration=video.duration,
                    is_embeddable=video.is_embeddable,
                    embed_status_checked_at=video.embed_status_checked_at,
                    thumbnail_url=video.thumbnail_url,
                    latest_task_id=task.id if task is not None else None,
                    latest_task_name=task.task_name if task is not None else None,
                    latest_task_status=task.status if task is not None else None,
                    latest_task_updated_at=task.updated_at if task is not None else None,
                    transcript_id=transcript_id,
                    generation=_ops_video_generation_record(
                        transcript_id=transcript_id,
                        cue_count=cue_count,
                        cue_task=cue_task,
                        micro_task=micro_task,
                        micro_video_task_id=micro_video_task_id,
                        window_count=window_count,
                        micro_event_count=micro_event_count,
                        timeline_task=timeline_task,
                        composition_id=composition_id,
                        timeline_video_task_id=timeline_video_task_id,
                        episode_count=episode_count,
                    ),
                )
            )

        return OpsVideoListResult(
            items=tuple(records),
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
            is_embeddable=video.is_embeddable,
            embed_status_checked_at=video.embed_status_checked_at,
            thumbnail_url=video.thumbnail_url,
            source_listing_api_call_id=video.source_listing_api_call_id,
            source_details_api_call_id=video.source_details_api_call_id,
            source_embed_status_api_call_id=video.source_embed_status_api_call_id,
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
    async def list_micro_event_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsMicroEventReadyCandidateListResult:
        latest_cue_task = self._latest_task_subquery(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
            status="succeeded",
        )
        latest_micro_task = self._latest_task_subquery(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
        )
        latest_transcript = self._latest_transcript_subquery()
        micro_summary = self._micro_event_summary_subquery()
        task_cue_summary = self._cue_summary_subquery()
        video_cue_summary = self._cue_summary_subquery()
        cue_task_alias = aliased(VideoTaskModel)
        micro_task_alias = aliased(VideoTaskModel)
        category_expr = _candidate_category_expr(micro_task_alias.status)
        transcript_id_expr = func.coalesce(
            cue_task_alias.output_transcript_id,
            latest_transcript.c.transcript_id,
        )
        cue_count_expr = func.coalesce(
            task_cue_summary.c.cue_count,
            video_cue_summary.c.cue_count,
            0,
        )
        conditions = [
            cue_count_expr > 0,
            micro_summary.c.video_task_id.is_(None),
            VideoModel.is_embeddable.is_not(False),
        ]
        conditions.extend(_candidate_filter_conditions(query))
        if query.category is not None:
            conditions.append(category_expr == query.category)

        base = (
            select(VideoModel.id)
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .outerjoin(latest_cue_task, latest_cue_task.c.video_id == VideoModel.id)
            .outerjoin(cue_task_alias, cue_task_alias.id == latest_cue_task.c.task_id)
            .outerjoin(
                latest_transcript,
                latest_transcript.c.youtube_video_id == VideoModel.youtube_video_id,
            )
            .outerjoin(
                task_cue_summary,
                task_cue_summary.c.transcript_id == cue_task_alias.output_transcript_id,
            )
            .outerjoin(
                video_cue_summary,
                video_cue_summary.c.transcript_id == latest_transcript.c.transcript_id,
            )
            .outerjoin(latest_micro_task, latest_micro_task.c.video_id == VideoModel.id)
            .outerjoin(micro_task_alias, micro_task_alias.id == latest_micro_task.c.task_id)
            .outerjoin(micro_summary, micro_summary.c.video_id == VideoModel.id)
            .where(*conditions)
        )
        try:
            total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
            rows = (
                await self._session.execute(
                    select(
                        VideoModel,
                        ChannelModel.name,
                        cue_task_alias,
                        transcript_id_expr.label("transcript_id"),
                        cue_count_expr.label("cue_count"),
                        micro_task_alias,
                        category_expr.label("category"),
                    )
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(latest_cue_task, latest_cue_task.c.video_id == VideoModel.id)
                    .outerjoin(cue_task_alias, cue_task_alias.id == latest_cue_task.c.task_id)
                    .outerjoin(
                        latest_transcript,
                        latest_transcript.c.youtube_video_id == VideoModel.youtube_video_id,
                    )
                    .outerjoin(
                        task_cue_summary,
                        task_cue_summary.c.transcript_id == cue_task_alias.output_transcript_id,
                    )
                    .outerjoin(
                        video_cue_summary,
                        video_cue_summary.c.transcript_id
                        == latest_transcript.c.transcript_id,
                    )
                    .outerjoin(latest_micro_task, latest_micro_task.c.video_id == VideoModel.id)
                    .outerjoin(
                        micro_task_alias,
                        micro_task_alias.id == latest_micro_task.c.task_id,
                    )
                    .outerjoin(micro_summary, micro_summary.c.video_id == VideoModel.id)
                    .where(*conditions)
                    .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
                    .limit(query.limit)
                    .offset(query.offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        return OpsMicroEventReadyCandidateListResult(
            items=tuple(
                OpsMicroEventReadyCandidateRecord(
                    video_id=video.id,
                    channel_id=video.channel_id,
                    channel_name=channel_name,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    published_at=video.published_at,
                    transcript_id=transcript_id,
                    cue_count=int(cue_count or 0),
                    latest_cue_task=(
                        _task_summary_record(cue_task)
                        if cue_task is not None
                        else None
                    ),
                    latest_micro_task=(
                        _task_summary_record(micro_task)
                        if micro_task is not None
                        else None
                    ),
                    category=_candidate_category(category),
                    recommended_retry_failed=_recommended_retry_failed(category),
                )
                for (
                    video,
                    channel_name,
                    cue_task,
                    transcript_id,
                    cue_count,
                    micro_task,
                    category,
                ) in rows
            ),
            total=total or 0,
        )

    @override
    async def list_timeline_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsTimelineReadyCandidateListResult:
        latest_timeline_task = self._latest_task_subquery(
            task_name=TIMELINE_COMPOSE_TASK_NAME,
        )
        micro_summary = self._micro_event_summary_subquery()
        timeline_summary = self._timeline_summary_subquery()
        timeline_task_alias = aliased(VideoTaskModel)
        category_expr = _candidate_category_expr(timeline_task_alias.status)
        conditions = [
            micro_summary.c.video_task_id.is_not(None),
            micro_summary.c.micro_event_count > 0,
            timeline_summary.c.video_task_id.is_(None),
            VideoModel.is_embeddable.is_not(False),
        ]
        conditions.extend(_candidate_filter_conditions(query))
        if query.category is not None:
            conditions.append(category_expr == query.category)

        base = (
            select(VideoModel.id)
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .outerjoin(micro_summary, micro_summary.c.video_id == VideoModel.id)
            .outerjoin(latest_timeline_task, latest_timeline_task.c.video_id == VideoModel.id)
            .outerjoin(
                timeline_task_alias,
                timeline_task_alias.id == latest_timeline_task.c.task_id,
            )
            .outerjoin(timeline_summary, timeline_summary.c.video_id == VideoModel.id)
            .where(*conditions)
        )
        try:
            total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
            rows = (
                await self._session.execute(
                    select(
                        VideoModel,
                        ChannelModel.name,
                        micro_summary.c.video_task_id,
                        micro_summary.c.micro_event_count,
                        micro_summary.c.window_count,
                        timeline_task_alias,
                        category_expr.label("category"),
                    )
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(micro_summary, micro_summary.c.video_id == VideoModel.id)
                    .outerjoin(
                        latest_timeline_task,
                        latest_timeline_task.c.video_id == VideoModel.id,
                    )
                    .outerjoin(
                        timeline_task_alias,
                        timeline_task_alias.id == latest_timeline_task.c.task_id,
                    )
                    .outerjoin(timeline_summary, timeline_summary.c.video_id == VideoModel.id)
                    .where(*conditions)
                    .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
                    .limit(query.limit)
                    .offset(query.offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        return OpsTimelineReadyCandidateListResult(
            items=tuple(
                OpsTimelineReadyCandidateRecord(
                    video_id=video.id,
                    channel_id=video.channel_id,
                    channel_name=channel_name,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    published_at=video.published_at,
                    source_micro_event_task_id=int(source_micro_event_task_id),
                    micro_event_count=int(micro_event_count or 0),
                    window_count=int(window_count or 0),
                    latest_timeline_task=(
                        _task_summary_record(timeline_task)
                        if timeline_task is not None
                        else None
                    ),
                    category=_candidate_category(category),
                    recommended_retry_failed=_recommended_retry_failed(category),
                )
                for (
                    video,
                    channel_name,
                    source_micro_event_task_id,
                    micro_event_count,
                    window_count,
                    timeline_task,
                    category,
                ) in rows
            ),
            total=total or 0,
        )

    @override
    async def detect_stuck_tasks(
        self,
        query: OpsStuckTaskQuery,
    ) -> OpsStuckTaskListResult:
        latest_event = (
            select(
                OperationEventModel.video_task_id.label("video_task_id"),
                func.max(OperationEventModel.id).label("event_id"),
            )
            .where(OperationEventModel.video_task_id.is_not(None))
            .group_by(OperationEventModel.video_task_id)
            .subquery()
        )
        event_alias = aliased(OperationEventModel)
        try:
            rows = (
                await self._session.execute(
                    select(
                        VideoTaskModel,
                        VideoModel,
                        ChannelModel.name,
                        PipelineJobAttemptModel,
                        event_alias,
                    )
                    .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .outerjoin(
                        PipelineJobAttemptModel,
                        PipelineJobAttemptModel.id == VideoTaskModel.job_attempt_id,
                    )
                    .outerjoin(latest_event, latest_event.c.video_task_id == VideoTaskModel.id)
                    .outerjoin(event_alias, event_alias.id == latest_event.c.event_id)
                    .where(
                        VideoTaskModel.task_name == query.task_name,
                        VideoTaskModel.status == "running",
                    )
                    .order_by(VideoTaskModel.updated_at.asc(), VideoTaskModel.id.asc())
                )
            ).all()
        except SQLAlchemyError as exc:
            raise OpsPersistenceError("Ops metadata read failed.") from exc

        older_than = _utc(query.older_than)
        items: list[OpsStuckTaskRecord] = []
        for task, video, channel_name, attempt, event in rows:
            stale_since = _latest_activity_at(task, event)
            if stale_since > older_than:
                continue
            items.append(
                OpsStuckTaskRecord(
                    video_task_id=task.id,
                    video_id=video.id,
                    channel_id=video.channel_id,
                    channel_name=channel_name,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    task_name=task.task_name,
                    status=task.status,
                    worker_id=task.worker_id,
                    worker_pid=_worker_pid(task.worker_id),
                    job_id=task.job_id,
                    job_attempt_id=task.job_attempt_id,
                    job_attempt_status=attempt.status if attempt is not None else None,
                    started_at=task.started_at,
                    updated_at=task.updated_at,
                    stale_since=stale_since,
                    latest_event=(
                        _latest_event_record(event) if event is not None else None
                    ),
                    error_type=task.error_type,
                    error_message=task.error_message,
                )
            )
        return OpsStuckTaskListResult(items=tuple(items), total=len(items))

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

    def _latest_task_subquery(
        self,
        *,
        task_name: str | None = None,
        status: str | None = None,
    ):
        statement = select(
            VideoTaskModel.video_id.label("video_id"),
            func.max(VideoTaskModel.id).label("task_id"),
        )
        if task_name is not None:
            statement = statement.where(VideoTaskModel.task_name == task_name)
        if status is not None:
            statement = statement.where(VideoTaskModel.status == status)
        return statement.group_by(VideoTaskModel.video_id).subquery()

    def _latest_transcript_subquery(self):
        return (
            select(
                YouTubeTranscriptRecordModel.video_id.label("youtube_video_id"),
                func.max(YouTubeTranscriptRecordModel.id).label("transcript_id"),
            )
            .group_by(YouTubeTranscriptRecordModel.video_id)
            .subquery()
        )

    def _cue_summary_subquery(self):
        return (
            select(
                TranscriptCueModel.transcript_id.label("transcript_id"),
                func.count(TranscriptCueModel.id).label("cue_count"),
            )
            .group_by(TranscriptCueModel.transcript_id)
            .subquery()
        )

    def _micro_event_summary_subquery(self):
        latest_micro_task = self._latest_task_subquery(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
            status="succeeded",
        )
        return (
            select(
                latest_micro_task.c.video_id.label("video_id"),
                latest_micro_task.c.task_id.label("video_task_id"),
                func.count(
                    distinct(MicroEventExtractionWindowModel.id)
                ).label("window_count"),
                func.count(distinct(MicroEventCandidateModel.id)).label(
                    "micro_event_count"
                ),
            )
            .select_from(latest_micro_task)
            .outerjoin(
                MicroEventExtractionWindowModel,
                MicroEventExtractionWindowModel.video_task_id
                == latest_micro_task.c.task_id,
            )
            .outerjoin(
                MicroEventCandidateModel,
                MicroEventCandidateModel.video_task_id == latest_micro_task.c.task_id,
            )
            .group_by(latest_micro_task.c.video_id, latest_micro_task.c.task_id)
            .subquery()
        )

    def _timeline_summary_subquery(self):
        latest_timeline_task = self._latest_task_subquery(
            task_name=TIMELINE_COMPOSE_TASK_NAME,
            status="succeeded",
        )
        return (
            select(
                latest_timeline_task.c.video_id.label("video_id"),
                TimelineCompositionModel.id.label("composition_id"),
                TimelineCompositionModel.video_task_id.label("video_task_id"),
                func.count(TimelineEpisodeModel.id).label("episode_count"),
            )
            .select_from(latest_timeline_task)
            .join(
                TimelineCompositionModel,
                TimelineCompositionModel.video_task_id
                == latest_timeline_task.c.task_id,
            )
            .outerjoin(
                TimelineEpisodeModel,
                TimelineEpisodeModel.composition_id == TimelineCompositionModel.id,
            )
            .group_by(
                latest_timeline_task.c.video_id,
                TimelineCompositionModel.id,
                TimelineCompositionModel.video_task_id,
            )
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


def _task_summary_record(task: VideoTaskModel) -> OpsTaskSummaryRecord:
    return OpsTaskSummaryRecord(
        video_task_id=task.id,
        status=task.status,
        worker_id=task.worker_id,
        job_id=task.job_id,
        job_attempt_id=task.job_attempt_id,
        error_type=task.error_type,
        error_message=task.error_message,
        updated_at=task.updated_at,
    )


def _latest_event_record(event: OperationEventModel) -> OpsLatestEventRecord:
    return OpsLatestEventRecord(
        operation_event_id=event.id,
        occurred_at=event.occurred_at,
        event_type=event.event_type,
        severity=event.severity,
        message=event.message,
        error_type=event.error_type,
        error_message=event.error_message,
    )


def _candidate_filter_conditions(query: OpsCandidateListQuery) -> list[Any]:
    conditions: list[Any] = []
    if query.channel_id is not None:
        conditions.append(VideoModel.channel_id == query.channel_id)
    if query.search is not None:
        like = f"%{query.search}%"
        conditions.append(
            or_(
                VideoModel.title.ilike(like),
                VideoModel.youtube_video_id.ilike(like),
            )
        )
    return conditions


def _candidate_category_expr(status_column: Any) -> Any:
    return case(
        (status_column.is_(None), "readyNoHistory"),
        (status_column.in_(("pending", "running")), "active"),
        (status_column == "canceled", "retryableCanceled"),
        (status_column.in_(("failed", "timed_out")), "failed"),
        else_="blocked",
    )


def _candidate_category(value: object) -> OpsCandidateCategory:
    if value in {"readyNoHistory", "retryableCanceled", "failed", "active", "blocked"}:
        return cast(OpsCandidateCategory, value)
    return "blocked"


def _recommended_retry_failed(value: object) -> bool:
    return value in {"retryableCanceled", "failed"}


def _latest_activity_at(
    task: VideoTaskModel,
    event: OperationEventModel | None,
) -> datetime:
    latest = _utc(task.updated_at)
    if event is not None:
        event_time = _utc(event.occurred_at)
        if event_time > latest:
            latest = event_time
    return latest


def _worker_pid(worker_id: str | None) -> int | None:
    if not worker_id:
        return None
    for part in reversed(worker_id.split(":")):
        if part.isdigit():
            return int(part)
    return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _ops_video_generation_record(
    *,
    transcript_id: int | None,
    cue_count: int | None,
    cue_task: VideoTaskModel | None,
    micro_task: VideoTaskModel | None,
    micro_video_task_id: int | None,
    window_count: int | None,
    micro_event_count: int | None,
    timeline_task: VideoTaskModel | None,
    composition_id: int | None,
    timeline_video_task_id: int | None,
    episode_count: int | None,
) -> OpsVideoGenerationRecord:
    cue_total = cue_count or 0
    window_total = window_count or 0
    micro_event_total = micro_event_count or 0
    episode_total = episode_count or 0
    return OpsVideoGenerationRecord(
        cues=OpsVideoCueGenerationRecord(
            generated=cue_total > 0,
            transcript_id=transcript_id,
            cue_count=cue_total,
            latest_task_id=cue_task.id if cue_task is not None else None,
            latest_task_status=cue_task.status if cue_task is not None else None,
            latest_task_updated_at=cue_task.updated_at if cue_task is not None else None,
        ),
        micro_events=OpsVideoMicroEventGenerationRecord(
            generated=micro_event_total > 0,
            video_task_id=micro_video_task_id,
            window_count=window_total,
            micro_event_count=micro_event_total,
            latest_task_id=micro_task.id if micro_task is not None else None,
            latest_task_status=micro_task.status if micro_task is not None else None,
            latest_task_updated_at=micro_task.updated_at if micro_task is not None else None,
        ),
        timeline=OpsVideoTimelineGenerationRecord(
            generated=composition_id is not None,
            composition_id=composition_id,
            video_task_id=timeline_video_task_id,
            episode_count=episode_total,
            latest_task_id=timeline_task.id if timeline_task is not None else None,
            latest_task_status=timeline_task.status if timeline_task is not None else None,
            latest_task_updated_at=timeline_task.updated_at
            if timeline_task is not None
            else None,
        ),
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
