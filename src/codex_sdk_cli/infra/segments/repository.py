from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from codex_sdk_cli.application.segments.executors import required_int, required_str
from codex_sdk_cli.application.segments.ports import SegmentResultStorePort
from codex_sdk_cli.domains.segments.models import SegmentSourceChangedError, fingerprint
from codex_sdk_cli.domains.segments.policy import public_segments, validate_time_coverage
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel
from codex_sdk_cli.infra.work.models import WorkAttemptModel, WorkItemModel

from .source import load_source


class SegmentClassificationModel(Base):
    __tablename__ = "segment_classifications"
    __table_args__ = (
        UniqueConstraint(
            "work_item_id", "work_attempt_id", name="uq_segment_classifications_attempt"
        ),
        Index("ix_segment_classifications_source", "composition_id", "source_fingerprint"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="RESTRICT"))
    work_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="RESTRICT")
    )
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="RESTRICT"))
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="RESTRICT")
    )
    source_timeline_work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="RESTRICT")
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    prompt_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=True
    )
    prompt_body_sha256: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    reasoning_effort: Mapped[str] = mapped_column(String(32))
    raw_response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimelineSegmentModel(Base):
    __tablename__ = "timeline_segments"
    __table_args__ = (
        UniqueConstraint("classification_id", "segment_index", name="uq_timeline_segments_index"),
        CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="timeline_segments_time_valid"),
        CheckConstraint("segment_index >= 1", name="timeline_segments_index_min"),
        CheckConstraint(
            "category IN ('chat','game','sing','watch','cafe','setup','asmr','other')",
            name="timeline_segments_category_allowed",
        ),
        Index("ix_timeline_segments_category", "category", "classification_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classification_id: Mapped[int] = mapped_column(
        ForeignKey("segment_classifications.id", ondelete="CASCADE")
    )
    segment_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    start_episode_id: Mapped[str] = mapped_column(String(64))
    end_episode_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    collab: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class SqlAlchemySegmentResultStore(SegmentResultStorePort):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        input_json: dict[str, object],
        segments: list[dict[str, object]],
        raw_response: str,
    ) -> int:
        async with self._sessions() as session, session.begin():
            work = await session.get(WorkItemModel, work_item_id)
            attempt = await session.get(WorkAttemptModel, work_attempt_id)
            if (
                work is None
                or attempt is None
                or work.task_type != "segment_classify"
                or work.status != "running"
                or attempt.status != "running"
                or attempt.work_item_id != work_item_id
                or work.input_hash != fingerprint(input_json)
            ):
                raise SegmentSourceChangedError(
                    "Classification execution provenance does not match."
                )
            source_work = required_int(input_json, "sourceTimelineWorkItemId")
            await session.scalar(
                select(TimelineCompositionModel)
                .where(TimelineCompositionModel.video_task_id == source_work)
                .with_for_update()
            )
            source = await load_source(session, required_int(input_json, "videoId"), source_work)
            if source.fingerprint != input_json["sourceFingerprint"]:
                raise SegmentSourceChangedError(
                    "Source changed during classification; enqueue it again."
                )
            validate_time_coverage(segments, source.episodes)
            existing = await session.scalar(
                select(SegmentClassificationModel).where(
                    SegmentClassificationModel.work_item_id == work_item_id,
                    SegmentClassificationModel.work_attempt_id == work_attempt_id,
                )
            )
            if existing:
                return existing.id
            model = SegmentClassificationModel(
                work_item_id=work_item_id,
                work_attempt_id=work_attempt_id,
                video_id=source.video_id,
                composition_id=source.composition_id,
                source_timeline_work_item_id=source_work,
                source_fingerprint=source.fingerprint,
                input_fingerprint=fingerprint(input_json),
                taxonomy_version=required_str(input_json, "taxonomyVersion"),
                policy_version=required_str(input_json, "policyVersion"),
                prompt_version_id=input_json.get("promptVersionId"),
                prompt_body_sha256=required_str(input_json, "promptBodySha256"),
                model=required_str(input_json, "model"),
                reasoning_effort=required_str(input_json, "reasoningEffort"),
                raw_response=raw_response,
            )
            session.add(model)
            await session.flush()
            for index, row in enumerate(segments, 1):
                session.add(
                    TimelineSegmentModel(
                        classification_id=model.id,
                        segment_index=index,
                        start_ms=row["startMs"],
                        end_ms=row["endMs"],
                        start_episode_id=row["startEpisodeId"],
                        end_episode_id=row["endEpisodeId"],
                        category=row["category"],
                        collab=row["collab"],
                        payload=row,
                    )
                )
            return model.id


async def classification_payload(
    session: AsyncSession, classification_id: int
) -> dict[str, object]:
    model = await session.get(SegmentClassificationModel, classification_id)
    if model is None:
        raise SegmentSourceChangedError("Selected classification does not exist.")
    rows = list(
        await session.scalars(
            select(TimelineSegmentModel)
            .where(TimelineSegmentModel.classification_id == model.id)
            .order_by(TimelineSegmentModel.segment_index)
        )
    )
    return {
        "taxonomyVersion": model.taxonomy_version,
        "segments": public_segments([r.payload for r in rows]),
        "segmentClassification": {
            "id": model.id,
            "workItemId": model.work_item_id,
            "sourceTimelineWorkItemId": model.source_timeline_work_item_id,
            "sourceFingerprint": model.source_fingerprint,
            "inputFingerprint": model.input_fingerprint,
            "policyVersion": model.policy_version,
            "promptBodySha256": model.prompt_body_sha256,
        },
    }
