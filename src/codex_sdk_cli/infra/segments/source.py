from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.segments.ports import SegmentSourceReaderPort
from codex_sdk_cli.domains.segments.models import (
    EpisodeRange,
    SegmentClassificationError,
    SegmentSource,
)
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.domain_knowledge.repository import SqlAlchemyDomainKnowledgeRepository
from codex_sdk_cli.infra.micro_events.repository import MicroEventCandidateModel
from codex_sdk_cli.infra.timelines.repository import (
    TimelineBlockModel,
    TimelineCompositionModel,
    TimelineEpisodeModel,
)
from codex_sdk_cli.infra.transcript_cues.repository import TranscriptCueModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.work.models import WorkItemModel


class SqlAlchemySegmentSourceReader(SegmentSourceReaderPort):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, video_id: int, timeline_work_item_id: int) -> SegmentSource:
        async with self._sessions() as session:
            return await load_source(session, video_id, timeline_work_item_id)


async def load_source(
    session: AsyncSession,
    video_id: int,
    timeline_work_item_id: int,
) -> SegmentSource:
    video = await session.get(VideoModel, video_id)
    work = await session.get(WorkItemModel, timeline_work_item_id)
    composition = await session.scalar(
        select(TimelineCompositionModel).where(
            TimelineCompositionModel.video_task_id == timeline_work_item_id,
            TimelineCompositionModel.video_id == video_id,
        )
    )
    if (
        video is None
        or composition is None
        or work is None
        or work.task_type != "timeline_compose"
        or work.status != "succeeded"
        or work.outcome_code is not None
        or work.subject_id != video_id
    ):
        raise SegmentClassificationError("A successful source timeline is required.")
    channel = await session.get(ChannelModel, video.channel_id)
    knowledge = await SqlAlchemyDomainKnowledgeRepository(session).list_prompt_entries_for_streamer(
        channel.streamer_id if channel else None
    )
    blocks = list(
        await session.scalars(
            select(TimelineBlockModel)
            .where(TimelineBlockModel.composition_id == composition.id)
            .order_by(TimelineBlockModel.block_index)
        )
    )
    episode_models = list(
        await session.scalars(
            select(TimelineEpisodeModel)
            .where(TimelineEpisodeModel.composition_id == composition.id)
            .order_by(TimelineEpisodeModel.episode_index)
        )
    )
    empty = composition.output_json.get("timeline_state") == "empty"
    episodes, payloads = ([], []) if empty else await _episodes(session, episode_models)
    payload: dict[str, object] = {
        "videoId": video_id,
        "youtubeVideoId": video.youtube_video_id,
        "title": video.title,
        "description": video.description,
        "timelineTitle": composition.title,
        "timelineSummary": composition.summary,
        "displayTitle": composition.display_title,
        "displaySummary": composition.display_summary,
        "timelineState": "empty" if empty else "ready",
        "blocks": [
            {
                "blockId": b.block_id,
                "title": b.title,
                "summary": b.summary,
                "displayTitle": b.display_title,
                "displaySummary": b.display_summary,
                "episodeIds": b.episode_ids,
            }
            for b in blocks
        ],
        "episodes": payloads,
        "domainKnowledge": [
            asdict(k)
            for k in knowledge
            if k.type_key in {"fan-name", "person", "streamer", "group", "game"}
        ],
    }
    return SegmentSource(
        video_id, timeline_work_item_id, composition.id, payload, tuple(episodes), empty
    )


async def _episodes(
    session: AsyncSession,
    models: list[TimelineEpisodeModel],
) -> tuple[list[EpisodeRange], list[dict[str, object]]]:
    candidate_ids = {
        i
        for e in models
        for i in (e.start_micro_event_candidate_id, e.end_micro_event_candidate_id)
        if i is not None
    }
    candidates = {
        c.id: c
        for c in await session.scalars(
            select(MicroEventCandidateModel).where(MicroEventCandidateModel.id.in_(candidate_ids))
        )
    }
    cue_ids = {cue for c in candidates.values() for cue in (c.start_cue_id, c.end_cue_id)}
    cues = {
        c.cue_id: c
        for c in await session.scalars(
            select(TranscriptCueModel).where(TranscriptCueModel.cue_id.in_(cue_ids))
        )
    }
    ranges: list[EpisodeRange] = []
    payloads: list[dict[str, object]] = []
    for index, e in enumerate(models, 1):
        first = candidates.get(e.start_micro_event_candidate_id or -1)
        last = candidates.get(e.end_micro_event_candidate_id or -1)
        if (
            first is None
            or last is None
            or first.start_cue_id not in cues
            or last.end_cue_id not in cues
        ):
            raise SegmentClassificationError("Episode cue boundaries are missing.")
        start, end = cues[first.start_cue_id].start_ms, cues[last.end_cue_id].end_ms
        ranges.append(EpisodeRange(e.episode_id, start, end))
        payloads.append(
            {
                "index": index,
                "episodeId": e.episode_id,
                "blockId": e.parent_block_id,
                "startMs": start,
                "endMs": end,
                "title": e.title,
                "summary": e.summary,
                "displayTitle": e.display_title,
                "displaySummary": e.display_summary,
                "topics": e.topics,
            }
        )
    if not ranges:
        raise SegmentClassificationError("A nonempty timeline must contain episodes.")
    return ranges, payloads
