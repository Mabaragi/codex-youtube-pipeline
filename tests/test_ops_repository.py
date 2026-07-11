from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.micro_events.repository import (
    MicroEventCandidateModel,
    MicroEventExtractionWindowModel,
)
from codex_sdk_cli.infra.operation_events.repository import OperationEventModel
from codex_sdk_cli.infra.ops.repository import SqlAlchemyOpsRepository
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.timelines.repository import (
    TimelineCompositionModel,
    TimelineEpisodeModel,
)
from codex_sdk_cli.infra.transcript_cues.repository import TranscriptCueModel
from codex_sdk_cli.infra.videos.repository import VideoModel
from codex_sdk_cli.infra.work.models import WorkAttemptModel, WorkItemModel
from codex_sdk_cli.infra.youtube_transcripts.repository import YouTubeTranscriptRecordModel


def _work_job(
    *,
    task_type: str,
    status: str,
    subject_type: str,
    subject_id: int,
    external_key: str,
    input_json: dict[str, object],
    input_hash: str,
) -> WorkItemModel:
    return WorkItemModel(
        task_type=task_type,
        subject_type=subject_type,
        subject_id=subject_id,
        external_key=external_key,
        task_version="v1",
        input_hash=input_hash,
        idempotency_key=f"ops-job:{task_type}:{subject_type}:{subject_id}:{input_hash}",
        execution_mode="inline",
        status=status,
        priority=0,
        timeout_seconds=600,
        input_json=input_json,
        available_at=datetime.now(UTC),
    )


def _video_task(
    *,
    video_id: int,
    task_name: str,
    task_version: str,
    input_hash: str,
    status: str,
    timeout_seconds: int,
    output_transcript_id: int | None = None,
    output_json: dict[str, object] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    worker_id: str | None = None,
    started_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> WorkItemModel:
    outcome_code = "no_transcript" if status == "no_transcript" else None
    work_status = "succeeded" if status == "no_transcript" else status
    return WorkItemModel(
        task_type=task_name,
        subject_type="video",
        subject_id=video_id,
        external_key=None,
        task_version=task_version,
        input_hash=input_hash,
        idempotency_key=f"ops-task:{task_name}:{video_id}:{input_hash}",
        execution_mode="worker",
        status=work_status,
        outcome_code=outcome_code,
        priority=0,
        timeout_seconds=timeout_seconds,
        input_json={},
        output_transcript_id=output_transcript_id,
        output_json=output_json,
        error_type=error_type,
        error_message=error_message,
        lease_owner=worker_id,
        started_at=started_at,
        available_at=updated_at or datetime.now(UTC),
        updated_at=updated_at or datetime.now(UTC),
    )


def test_ops_repository_lists_operational_views(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_file = migrated_database_path
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_file.as_posix()}",
    )

    result = asyncio.run(_exercise_repository(database_file))

    assert result["counts"].channels == 1
    assert result["counts"].videos == 7
    assert result["channels"][0].video_count == 7
    assert result["channels"][0].transcript_succeeded_count == 1
    assert result["channels"][0].task_no_transcript_count == 1
    assert result["videos"].total == 7
    assert result["videos"].items[0].latest_task_status == "succeeded"
    assert result["videos"].items[0].transcript_id == result["transcript_id"]
    assert result["videos"].items[0].generation.cues.generated is True
    assert result["videos"].items[0].generation.cues.cue_count == 2
    assert result["videos"].items[0].generation.micro_events.generated is True
    assert result["videos"].items[0].generation.micro_events.window_count == 1
    assert result["videos"].items[0].generation.micro_events.micro_event_count == 2
    assert result["videos"].items[0].generation.timeline.generated is True
    assert result["videos"].items[0].generation.timeline.composition_id == result["composition_id"]
    assert result["videos"].items[0].generation.timeline.episode_count == 2
    assert result["micro_candidates"].total == 4
    assert {item.category for item in result["micro_candidates"].items} == {
        "readyNoHistory",
        "failed",
        "active",
    }
    asr_candidate = next(
        item
        for item in result["micro_candidates"].items
        if item.video_id == result["asr_cue_ready_video_id"]
    )
    assert asr_candidate.transcript_id == result["asr_cue_ready_transcript_id"]
    assert asr_candidate.cue_count == 2
    assert asr_candidate.latest_cue_task is None
    assert asr_candidate.category == "readyNoHistory"
    assert result["timeline_candidates"].total == 2
    assert {item.source_micro_event_task_id for item in result["timeline_candidates"].items} == {
        result["timeline_ready_micro_task_id"],
        result["timeline_failed_micro_task_id"],
    }
    assert {item.category for item in result["timeline_candidates"].items} == {
        "readyNoHistory",
        "failed",
    }
    assert result["stuck"].total == 1
    assert result["stuck"].items[0].worker_pid == 4321
    assert result["stuck"].items[0].latest_event is not None
    assert any(item.youtube_video_id == "video1234567" for item in result["tasks"].items)
    assert any(item.kind == "pipeline_job" for item in result["failures"])


async def _exercise_repository(database_file: Path):
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            now = datetime.now(UTC)
            streamer = StreamerModel(name="Streamer")
            session.add(streamer)
            await session.flush()
            channel = ChannelModel(
                streamer_id=streamer.id,
                handle="@channel",
                name="Channel",
                youtube_channel_id="UC123",
                uploads_playlist_id="UU123",
            )
            session.add(channel)
            await session.flush()
            video = VideoModel(
                channel_id=channel.id,
                youtube_video_id="video1234567",
                title="Video",
                description="Description",
                published_at=now,
                duration="PT1M",
            )
            session.add(video)
            transcript = YouTubeTranscriptRecordModel(
                video_id="video1234567",
                language="Korean",
                language_code="ko",
                is_generated=False,
                requested_languages=["ko", "en"],
                preserve_formatting=False,
                storage_bucket="raw",
                storage_object_name="object.json",
                storage_uri="s3://raw/object.json",
                response_sha256="a" * 64,
                segment_count=1,
                text_length=10,
            )
            session.add(transcript)
            failed_job = _work_job(
                task_type="video_collect",
                status="failed",
                subject_type="channel",
                subject_id=channel.id,
                external_key="UC123",
                input_json={"channelId": channel.id},
                input_hash="0" * 64,
            )
            session.add(failed_job)
            await session.flush()
            session.add(
                WorkAttemptModel(
                    work_item_id=failed_job.id,
                    attempt_no=1,
                    status="failed",
                    error_type="UpstreamError",
                    error_message="failed",
                )
            )
            await session.flush()
            no_transcript_task = _video_task(
                video_id=video.id,
                task_name="transcript_collect",
                task_version="v1",
                input_hash="2" * 64,
                status="no_transcript",
                timeout_seconds=600,
                error_type="YouTubeTranscriptNotFound",
                error_message="No transcript.",
            )
            session.add(no_transcript_task)
            await session.flush()
            task = _video_task(
                video_id=video.id,
                task_name="transcript_collect",
                task_version="v1",
                input_hash="1" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
            )
            session.add(task)
            cue_task = _video_task(
                video_id=video.id,
                task_name="transcript_cue_generate",
                task_version="v1",
                input_hash="3" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
                output_json={"cueCount": 1},
            )
            session.add(cue_task)
            await session.flush()
            session.add_all(
                [
                    TranscriptCueModel(
                        transcript_id=transcript.id,
                        cue_id="tr1-c000001",
                        cue_index=1,
                        text="first cue",
                        start_ms=0,
                        end_ms=1000,
                        duration_ms=1000,
                        source_segment_index=0,
                    ),
                    TranscriptCueModel(
                        transcript_id=transcript.id,
                        cue_id="tr1-c000002",
                        cue_index=2,
                        text="second cue",
                        start_ms=1000,
                        end_ms=2000,
                        duration_ms=1000,
                        source_segment_index=1,
                    ),
                ]
            )
            micro_task = _video_task(
                video_id=video.id,
                task_name="micro_event_extract",
                task_version="v2",
                input_hash="4" * 64,
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
            )
            session.add(micro_task)
            await session.flush()
            micro_window = MicroEventExtractionWindowModel(
                video_task_id=micro_task.id,
                video_id=video.id,
                transcript_id=transcript.id,
                window_index=1,
                start_cue_id="tr1-c000001",
                end_cue_id="tr1-c000002",
                cue_count=2,
                status="succeeded",
                carry_out_unfinished=False,
            )
            session.add(micro_window)
            await session.flush()
            session.add_all(
                [
                    MicroEventCandidateModel(
                        window_id=micro_window.id,
                        video_task_id=micro_task.id,
                        transcript_id=transcript.id,
                        candidate_index=1,
                        activity="JUST_CHATTING",
                        event="first event",
                        start_cue_id="tr1-c000001",
                        end_cue_id="tr1-c000001",
                        evidence_cue_ids=["tr1-c000001"],
                        boundary_before=True,
                        boundary_after=False,
                        confidence=0.8,
                    ),
                    MicroEventCandidateModel(
                        window_id=micro_window.id,
                        video_task_id=micro_task.id,
                        transcript_id=transcript.id,
                        candidate_index=2,
                        activity="GAMEPLAY",
                        event="second event",
                        start_cue_id="tr1-c000002",
                        end_cue_id="tr1-c000002",
                        evidence_cue_ids=["tr1-c000002"],
                        boundary_before=False,
                        boundary_after=True,
                        confidence=0.9,
                    ),
                ]
            )
            timeline_task = _video_task(
                video_id=video.id,
                task_name="timeline_compose",
                task_version="v1",
                input_hash="5" * 64,
                status="succeeded",
                timeout_seconds=600,
            )
            session.add(timeline_task)
            await session.flush()
            composition = TimelineCompositionModel(
                video_task_id=timeline_task.id,
                video_id=video.id,
                source_micro_event_task_id=micro_task.id,
                source_micro_event_fingerprint="f" * 64,
                copy_style="LIGHT_FANDOM_V1",
                title="Timeline",
                summary="Summary",
                display_title="Timeline",
                display_summary="Summary",
                main_topics=["topic"],
                output_json={"ok": True},
                validation_warnings=[],
            )
            session.add(composition)
            await session.flush()
            session.add_all(
                [
                    TimelineEpisodeModel(
                        composition_id=composition.id,
                        episode_id="ep-1",
                        episode_index=1,
                        parent_block_id="block-1",
                        program_mode="JUST_CHATTING",
                        primary_content_kind="META_CHAT",
                        title="Episode 1",
                        summary="First episode",
                        display_title="Episode 1",
                        display_summary="First episode",
                        topics=["topic"],
                        viewer_tags=["FUNNY"],
                        highlight_micro_event_candidate_ids=[],
                        visibility="PUBLIC",
                    ),
                    TimelineEpisodeModel(
                        composition_id=composition.id,
                        episode_id="ep-2",
                        episode_index=2,
                        parent_block_id="block-1",
                        program_mode="GAMEPLAY",
                        primary_content_kind="GAME_PROGRESS",
                        title="Episode 2",
                        summary="Second episode",
                        display_title="Episode 2",
                        display_summary="Second episode",
                        topics=["topic"],
                        viewer_tags=["SKILL"],
                        highlight_micro_event_candidate_ids=[],
                        visibility="PUBLIC",
                    ),
                ]
            )

            await _add_video_with_cues(session, channel.id, 2, now - timedelta(minutes=1))

            micro_failed_video, micro_failed_transcript = await _add_video_with_cues(
                session,
                channel.id,
                3,
                now - timedelta(minutes=2),
            )
            session.add(
                _video_task(
                    video_id=micro_failed_video.id,
                    task_name="micro_event_extract",
                    task_version="v2",
                    input_hash="failed-micro",
                    status="failed",
                    timeout_seconds=600,
                    output_transcript_id=micro_failed_transcript.id,
                    error_type="ValidationError",
                    error_message="invalid",
                )
            )

            timeline_ready_video, timeline_ready_transcript = await _add_video_with_cues(
                session,
                channel.id,
                4,
                now - timedelta(minutes=3),
            )
            timeline_ready_micro_task = await _add_micro_success(
                session,
                video=timeline_ready_video,
                transcript=timeline_ready_transcript,
                suffix=4,
                input_hash="timeline-ready-micro",
            )

            timeline_failed_video, timeline_failed_transcript = await _add_video_with_cues(
                session,
                channel.id,
                5,
                now - timedelta(minutes=4),
            )
            timeline_failed_micro_task = await _add_micro_success(
                session,
                video=timeline_failed_video,
                transcript=timeline_failed_transcript,
                suffix=5,
                input_hash="timeline-failed-micro",
            )
            session.add(
                _video_task(
                    video_id=timeline_failed_video.id,
                    task_name="timeline_compose",
                    task_version="v1",
                    input_hash="timeline-failed",
                    status="failed",
                    timeout_seconds=600,
                    error_type="TimelineError",
                    error_message="failed",
                )
            )

            asr_cue_ready_video, asr_cue_ready_transcript = await _add_video_with_cues(
                session,
                channel.id,
                7,
                now - timedelta(minutes=5),
                with_cue_task=False,
            )

            stuck_video, stuck_transcript = await _add_video_with_cues(
                session,
                channel.id,
                6,
                now - timedelta(minutes=6),
            )
            old = now - timedelta(minutes=30)
            stuck_task = _video_task(
                video_id=stuck_video.id,
                task_name="micro_event_extract",
                task_version="v2",
                input_hash="stuck-micro",
                status="running",
                worker_id="micro-event-worker:host:4321",
                timeout_seconds=600,
                output_transcript_id=stuck_transcript.id,
                started_at=old,
                updated_at=old,
            )
            session.add(stuck_task)
            await session.flush()
            session.add(
                OperationEventModel(
                    occurred_at=old,
                    event_type="micro_event_extract.window_started",
                    severity="info",
                    message="Window started.",
                    actor_type="system",
                    source="test",
                    metadata_json={},
                    video_task_id=stuck_task.id,
                    video_id=stuck_video.id,
                )
            )
            await session.commit()

        async with session_factory() as session:
            repository = SqlAlchemyOpsRepository(session)
            from codex_sdk_cli.domains.ops.ports import (
                OpsCandidateListQuery,
                OpsStuckTaskQuery,
                OpsVideoListQuery,
                OpsVideoTaskListQuery,
            )

            return {
                "counts": await repository.get_summary_counts(),
                "channels": await repository.list_channels(),
                "videos": await repository.list_videos(
                    OpsVideoListQuery(
                        channel_id=None,
                        task_status=None,
                        search=None,
                        limit=10,
                        offset=0,
                    )
                ),
                "tasks": await repository.list_video_tasks(
                    OpsVideoTaskListQuery(
                        channel_id=None,
                        task_name=None,
                        status=None,
                        limit=50,
                        offset=0,
                    )
                ),
                "failures": await repository.list_recent_failures(limit=5),
                "micro_candidates": await repository.list_micro_event_ready_candidates(
                    OpsCandidateListQuery(
                        channel_id=None,
                        search=None,
                        category=None,
                        limit=10,
                        offset=0,
                    )
                ),
                "timeline_candidates": await repository.list_timeline_ready_candidates(
                    OpsCandidateListQuery(
                        channel_id=None,
                        search=None,
                        category=None,
                        limit=10,
                        offset=0,
                    )
                ),
                "stuck": await repository.detect_stuck_tasks(
                    OpsStuckTaskQuery(
                        task_name="micro_event_extract",
                        older_than=now - timedelta(minutes=15),
                    )
                ),
                "transcript_id": transcript.id,
                "composition_id": composition.id,
                "timeline_ready_micro_task_id": timeline_ready_micro_task.id,
                "timeline_failed_micro_task_id": timeline_failed_micro_task.id,
                "asr_cue_ready_video_id": asr_cue_ready_video.id,
                "asr_cue_ready_transcript_id": asr_cue_ready_transcript.id,
            }
    finally:
        await engine.dispose()


async def _add_video_with_cues(
    session,
    channel_id: int,
    suffix: int,
    published_at: datetime,
    *,
    with_cue_task: bool = True,
):
    video = VideoModel(
        channel_id=channel_id,
        youtube_video_id=f"video{suffix:07d}",
        title=f"Video {suffix}",
        description="Description",
        published_at=published_at,
        duration="PT1M",
    )
    session.add(video)
    await session.flush()
    transcript = YouTubeTranscriptRecordModel(
        video_id=video.youtube_video_id,
        language="Korean",
        language_code="ko",
        is_generated=False,
        requested_languages=["ko", "en"],
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name=f"object-{suffix}.json",
        storage_uri=f"s3://raw/object-{suffix}.json",
        response_sha256=f"{suffix}" * 64,
        segment_count=2,
        text_length=20,
    )
    session.add(transcript)
    await session.flush()
    if with_cue_task:
        session.add(
            _video_task(
                video_id=video.id,
                task_name="transcript_cue_generate",
                task_version="v1",
                input_hash=f"cue-{suffix}",
                status="succeeded",
                timeout_seconds=600,
                output_transcript_id=transcript.id,
                output_json={"cueCount": 2},
            )
        )
    session.add_all(
        [
            TranscriptCueModel(
                transcript_id=transcript.id,
                cue_id=f"tr{suffix}-c000001",
                cue_index=1,
                text="first cue",
                start_ms=0,
                end_ms=1000,
                duration_ms=1000,
                source_segment_index=0,
            ),
            TranscriptCueModel(
                transcript_id=transcript.id,
                cue_id=f"tr{suffix}-c000002",
                cue_index=2,
                text="second cue",
                start_ms=1000,
                end_ms=2000,
                duration_ms=1000,
                source_segment_index=1,
            ),
        ]
    )
    await session.flush()
    return video, transcript


async def _add_micro_success(
    session,
    *,
    video: VideoModel,
    transcript: YouTubeTranscriptRecordModel,
    suffix: int,
    input_hash: str,
) -> WorkItemModel:
    micro_task = _video_task(
        video_id=video.id,
        task_name="micro_event_extract",
        task_version="v2",
        input_hash=input_hash,
        status="succeeded",
        timeout_seconds=600,
        output_transcript_id=transcript.id,
    )
    session.add(micro_task)
    await session.flush()
    micro_window = MicroEventExtractionWindowModel(
        video_task_id=micro_task.id,
        video_id=video.id,
        transcript_id=transcript.id,
        window_index=1,
        start_cue_id=f"tr{suffix}-c000001",
        end_cue_id=f"tr{suffix}-c000002",
        cue_count=2,
        status="succeeded",
        carry_out_unfinished=False,
    )
    session.add(micro_window)
    await session.flush()
    session.add(
        MicroEventCandidateModel(
            window_id=micro_window.id,
            video_task_id=micro_task.id,
            transcript_id=transcript.id,
            candidate_index=1,
            activity="JUST_CHATTING",
            event="candidate event",
            start_cue_id=f"tr{suffix}-c000001",
            end_cue_id=f"tr{suffix}-c000002",
            evidence_cue_ids=[f"tr{suffix}-c000001", f"tr{suffix}-c000002"],
            boundary_before=True,
            boundary_after=True,
            confidence=0.9,
        )
    )
    await session.flush()
    return micro_task
