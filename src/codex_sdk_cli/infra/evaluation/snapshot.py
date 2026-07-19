from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.domains.evaluation.ports import EvaluationSnapshotterPort, JsonObject
from codex_sdk_cli.domains.evaluation.schemas import EvaluationPlan
from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.domain_knowledge.repository import (
    SqlAlchemyDomainKnowledgeRepository,
)
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.transcript_cues.repository import TranscriptCueModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.youtube_transcripts.repository import YouTubeTranscriptRecordModel


class ReadOnlyControlSnapshotter(EvaluationSnapshotterPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def snapshot_plan_inputs(
        self,
        *,
        experiment_id: str,
        plan: EvaluationPlan,
    ) -> list[JsonObject]:
        await self._begin_read_only_snapshot()
        prompt_resolver = PromptResolver(
            SqlAlchemyPromptRepository(self._session),
            cache=PromptCache(),
            ttl_seconds=0,
        )
        micro_prompts = {
            candidate.key: _prompt_json(
                await prompt_resolver.resolve_prompt_for_request(
                    MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    candidate.prompt_version_id,
                )
            )
            for candidate in plan.micro_candidates
        }
        timeline_prompts = {
            candidate.key: _prompt_json(
                await prompt_resolver.resolve_prompt_for_request(
                    TIMELINE_COMPOSE_PROMPT_KEY,
                    candidate.prompt_version_id,
                )
            )
            for candidate in plan.timeline_candidates
        }
        repair_prompt = _prompt_json(
            await prompt_resolver.resolve_prompt(TIMELINE_EPISODE_REPAIR_PROMPT_KEY)
        )
        snapshots: list[JsonObject] = []
        domain_repository = SqlAlchemyDomainKnowledgeRepository(self._session)
        for video_id in plan.video_ids:
            video = await self._session.get(VideoModel, video_id)
            if video is None:
                raise ValueError(f"Evaluation source video was not found: {video_id}")
            channel = await self._session.get(ChannelModel, video.channel_id)
            if channel is None:
                raise ValueError(f"Evaluation source channel was not found: {video.channel_id}")
            streamer = await self._session.get(StreamerModel, channel.streamer_id)
            if streamer is None:
                raise ValueError(f"Evaluation source streamer was not found: {channel.streamer_id}")
            transcript = await self._latest_transcript_with_cues(video.youtube_video_id)
            if transcript is None:
                raise ValueError(f"No transcript cues are available for video: {video_id}")
            cues = list(
                (
                    await self._session.scalars(
                        select(TranscriptCueModel)
                        .where(TranscriptCueModel.transcript_id == transcript.id)
                        .order_by(TranscriptCueModel.cue_index)
                    )
                ).all()
            )
            domain_entries = await domain_repository.list_prompt_entries_for_streamer(streamer.id)
            snapshots.append(
                cast(
                    JsonObject,
                    _jsonable(
                        {
                            "version": 1,
                            "experimentId": experiment_id,
                            "videoId": video.id,
                            "youtubeVideoId": video.youtube_video_id,
                            "video": _model_columns(video),
                            "channel": _model_columns(channel),
                            "streamer": _model_columns(streamer),
                            "transcript": _model_columns(transcript),
                            "cues": [_model_columns(cue) for cue in cues],
                            "domainKnowledge": [asdict(entry) for entry in domain_entries],
                            "prompts": {
                                "micro": micro_prompts,
                                "timeline": timeline_prompts,
                                "timelineRepair": repair_prompt,
                            },
                        }
                    ),
                )
            )
        return snapshots

    async def _begin_read_only_snapshot(self) -> None:
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            await self._session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )

    async def _latest_transcript_with_cues(
        self, youtube_video_id: str
    ) -> YouTubeTranscriptRecordModel | None:
        return await self._session.scalar(
            select(YouTubeTranscriptRecordModel)
            .join(
                TranscriptCueModel,
                TranscriptCueModel.transcript_id == YouTubeTranscriptRecordModel.id,
            )
            .where(YouTubeTranscriptRecordModel.video_id == youtube_video_id)
            .group_by(YouTubeTranscriptRecordModel.id)
            .order_by(YouTubeTranscriptRecordModel.id.desc())
            .limit(1)
        )


def _model_columns(model: Any) -> dict[str, object]:
    table = model.__table__
    return {column.name: getattr(model, column.name) for column in table.columns}


def _prompt_json(prompt: ResolvedPrompt) -> JsonObject:
    return {
        "key": prompt.key,
        "versionId": prompt.version_id,
        "versionLabel": prompt.version_label,
        "body": prompt.body,
        "bodySha256": prompt.body_sha256,
        "source": prompt.source,
    }


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"Unsupported evaluation snapshot value: {type(value).__name__}")
