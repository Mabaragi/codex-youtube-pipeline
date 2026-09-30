from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.application.segments.executors import required_int, required_str
from codex_sdk_cli.domains.segments.models import SegmentSourceChangedError
from codex_sdk_cli.domains.segments.policy import validate_time_coverage
from codex_sdk_cli.domains.segments.ports import SegmentPublicationReaderPort
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel
from codex_sdk_cli.infra.work.models import WorkItemModel

from .repository import SegmentClassificationModel, TimelineSegmentModel, classification_payload
from .source import load_source


class SqlAlchemySegmentPublicationReader(SegmentPublicationReaderPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, input_json: dict[str, object]) -> dict[str, object]:
        classification_id = required_int(input_json, "sourceClassificationId")
        source_id = required_int(input_json, "sourceTimelineWorkItemId")
        work_id = required_int(input_json, "sourceClassificationWorkItemId")
        expected_input = required_str(input_json, "sourceClassificationFingerprint")
        model = await self._session.get(SegmentClassificationModel, classification_id)
        work = await self._session.get(WorkItemModel, work_id)
        if (
            model is None
            or work is None
            or model.work_item_id != work_id
            or work.status != "succeeded"
            or work.task_type != "segment_classify"
            or work.outcome_code is not None
            or (work.output_json or {}).get("classificationId") != classification_id
            or model.input_fingerprint != expected_input
            or work.input_hash != expected_input
            or model.source_timeline_work_item_id != source_id
            or model.video_id != required_int(input_json, "videoId")
        ):
            raise SegmentSourceChangedError(
                "Pinned classification does not match this publication."
            )
        await self._session.scalar(
            select(TimelineCompositionModel)
            .where(
                TimelineCompositionModel.id == model.composition_id,
            )
            .with_for_update()
        )
        source = await load_source(self._session, model.video_id, source_id)
        if source.fingerprint != model.source_fingerprint:
            raise SegmentSourceChangedError(
                "Source changed after classification; classify it again."
            )
        rows = list(
            await self._session.scalars(
                select(TimelineSegmentModel)
                .where(
                    TimelineSegmentModel.classification_id == model.id,
                )
                .order_by(TimelineSegmentModel.segment_index)
            )
        )
        validate_time_coverage([r.payload for r in rows], source.episodes)
        return await classification_payload(self._session, classification_id)
