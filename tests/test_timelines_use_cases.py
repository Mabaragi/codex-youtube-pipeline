from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

from codex_sdk_cli.domains.micro_events.ports import (
    ContentKind,
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    ProgramMode,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.timelines.constants import TIMELINE_COMPOSE_PROMPT_VERSION
from codex_sdk_cli.domains.timelines.ports import TimelineComposeResult
from codex_sdk_cli.domains.timelines.use_cases import (
    PROMPT_HEADER,
    _ComposerInput,
    _composition_create,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_timeline_composition_accepts_topic_cluster_title_aliases() -> None:
    composer_input = _composer_input(_candidates(4))
    output_json = {
        "video_summary": {"title": "테스트 타임라인"},
        "blocks": [
            {
                "block_id": "block_001",
                "block_type": "JUST_CHATTING",
                "episode_ids": ["episode_001", "episode_002"],
            }
        ],
        "episodes": [
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0002",
                topics=[f"주제{i}" for i in range(1, 8)],
                highlights=["me_0001", "me_0002", "me_0001", "me_0002"],
            ),
            _episode_output("episode_002", "me_0003", "me_0004"),
        ],
        "topic_clusters": [
            {
                "cluster_id": "cluster_food",
                "title": "음식 이야기",
                "summary": "음식 관련 에피소드를 묶는다.",
                "episode_ids": ["episode_001", "episode_002"],
            }
        ],
        "review_flags": [],
    }

    create = _composition_create(
        composer_input,
        TimelineComposeResult(
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            final_response=json.dumps(output_json),
        ),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    assert create.topic_clusters[0].topic_id == "cluster_food"
    assert create.topic_clusters[0].label == "음식 이야기"
    assert create.topic_clusters[0].display_label == "음식 이야기"
    assert create.episodes[0].topics == [f"주제{i}" for i in range(1, 7)]
    assert len(create.episodes[0].highlight_micro_event_candidate_ids) == 3
    assert "episode episode_001 topics truncated to 6" in create.validation_warnings
    assert (
        "episode episode_001 highlight_micro_event_ids truncated to 3"
        in create.validation_warnings
    )


def test_timeline_soft_verifier_adds_review_flags() -> None:
    candidates = _candidates(14)
    candidates[10] = _candidate(
        11,
        11,
        event="새벽 1시쯤 방송할 예정이라고 말한다.",
        program_mode="CLOSING",
        content_kind="META_CHAT",
    )
    composer_input = _composer_input(candidates)
    output_json = {
        "video_summary": {"title": "테스트 타임라인"},
        "blocks": [
            {
                "block_id": "block_001",
                "block_type": "MIXED",
                "episode_ids": ["episode_001"],
            },
            {
                "block_id": "block_002",
                "block_type": "BREAK",
                "episode_ids": ["episode_002"],
            },
            {
                "block_id": "block_003",
                "block_type": "CLOSING",
                "episode_ids": ["episode_003"],
            },
        ],
        "episodes": [
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0009",
                topics=[f"주제{i}" for i in range(1, 7)],
            ),
            _episode_output(
                "episode_002",
                "me_0010",
                "me_0010",
                program_mode="BREAK",
                content_kind="BREAK_TIME",
            ),
            _episode_output(
                "episode_003",
                "me_0011",
                "me_0014",
                title="새벽 1시 방송할 예정",
                summary="방송 후반 일정 표현을 말한다.",
                program_mode="CLOSING",
            ),
        ],
        "topic_clusters": [],
        "review_flags": [],
    }

    create = _composition_create(
        composer_input,
        TimelineComposeResult(
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            final_response=json.dumps(output_json),
        ),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    flag_types = {flag.type for flag in create.review_flags}
    assert "OVERBROAD_MICRO_EVENT" in flag_types
    assert "BOUNDARY_AMBIGUOUS" in flag_types
    assert "ASR_SEMANTIC_RISK" in flag_types


def test_timeline_prompt_documents_output_limits_and_topic_cluster_keys() -> None:
    assert TIMELINE_COMPOSE_PROMPT_VERSION == "timeline-compose-v2"
    assert "topics는 episode마다 검색에 유용한 구체적 명사구 2~6개" in PROMPT_HEADER
    assert "highlight_micro_event_ids는 episode 안의 핵심 후보만 0~3개" in PROMPT_HEADER
    assert "topic_id, label, summary, display_label, episode_ids" in PROMPT_HEADER
    assert '"topic_id": "topic_001"' in PROMPT_HEADER


def _composer_input(candidates: list[MicroEventCandidateRecord]) -> _ComposerInput:
    synthetic_id_by_candidate_id = {
        candidate.id: f"me_{candidate.candidate_index:04d}" for candidate in candidates
    }
    candidate_id_by_synthetic_id = {
        synthetic_id: candidate_id
        for candidate_id, synthetic_id in synthetic_id_by_candidate_id.items()
    }
    return _ComposerInput(
        video=_video(),
        streamer_name="나기",
        domain_entries=[],
        source_task=_video_task(task_id=91),
        source_detail=MicroEventExtractionDetailRecord(
            video_task_id=91,
            video_id=71,
            youtube_video_id="youtube-1",
            transcript_id=47,
            status="succeeded",
            job_id=12,
            job_attempt_id=13,
            output_json={},
            error_type=None,
            error_message=None,
            started_at=NOW,
            completed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            windows=[],
        ),
        micro_events=candidates,
        synthetic_id_by_candidate_id=synthetic_id_by_candidate_id,
        candidate_id_by_synthetic_id=candidate_id_by_synthetic_id,
        input_json={"sourceMicroEventFingerprint": "abc123"},
        input_hash="hash-1",
        model="gpt-5.5",
        reasoning_effort="medium",
        copy_style="LIGHT_FANDOM_V1",
    )


def _episode_output(
    episode_id: str,
    start_micro_event_id: str,
    end_micro_event_id: str,
    *,
    title: str = "대표 제목",
    summary: str = "대표 요약",
    topics: list[str] | None = None,
    highlights: list[str] | None = None,
    program_mode: str = "JUST_CHATTING",
    content_kind: str = "META_CHAT",
) -> dict[str, object]:
    return {
        "episode_id": episode_id,
        "parent_block_id": "block_001",
        "start_micro_event_id": start_micro_event_id,
        "end_micro_event_id": end_micro_event_id,
        "program_mode": program_mode,
        "primary_content_kind": content_kind,
        "title": title,
        "summary": summary,
        "display_title": title,
        "display_summary": summary,
        "topics": topics or ["대표 주제", "보조 주제"],
        "viewer_tags": ["META"],
        "highlight_micro_event_ids": highlights or [start_micro_event_id],
        "visibility": "DEFAULT",
    }


def _candidates(count: int) -> list[MicroEventCandidateRecord]:
    modes = ["JUST_CHATTING", "GAMEPLAY", "POST_GAME"]
    kinds = ["META_CHAT", "GAME_PROGRESS", "PERSONAL_STORY"]
    return [
        _candidate(
            index,
            index,
            event=f"{index}번째 마이크로 이벤트",
            program_mode=modes[(index - 1) % len(modes)],
            content_kind=kinds[(index - 1) % len(kinds)],
        )
        for index in range(1, count + 1)
    ]


def _candidate(
    candidate_id: int,
    index: int,
    *,
    event: str,
    program_mode: str,
    content_kind: str,
) -> MicroEventCandidateRecord:
    return MicroEventCandidateRecord(
        id=candidate_id,
        window_id=1,
        video_task_id=91,
        transcript_id=47,
        candidate_index=index,
        activity="JUST_CHATTING",
        event=event,
        start_cue_id=f"tr47-c{index:06d}",
        end_cue_id=f"tr47-c{index:06d}",
        evidence_cue_ids=[f"tr47-c{index:06d}"],
        boundary_before=True,
        boundary_after=True,
        confidence=0.8,
        program_mode=cast(ProgramMode, program_mode),
        content_kind=cast(ContentKind, content_kind),
        topics=["주제"],
        relation_to_previous=None,
        continues_to_next=False,
        support_level="DIRECT",
        created_at=NOW,
        updated_at=NOW,
    )


def _video() -> VideoRecord:
    return VideoRecord(
        id=71,
        channel_id=5,
        youtube_video_id="youtube-1",
        title="방송 제목",
        description="",
        published_at=NOW,
        duration="PT1H",
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _video_task(task_id: int = 184) -> VideoTaskRecord:
    return VideoTaskRecord(
        id=task_id,
        video_id=71,
        task_name="timeline_compose",
        task_version="v1",
        input_hash="hash-1",
        status="running",
        worker_id="timeline-worker",
        timeout_seconds=1200,
        job_id=12,
        job_attempt_id=13,
        output_transcript_id=None,
        output_json=None,
        error_type=None,
        error_message=None,
        started_at=NOW,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
        input_json={},
    )


def _job() -> PipelineJobRecord:
    return PipelineJobRecord(
        id=12,
        step="timeline_compose",
        status="running",
        subject_type="video",
        subject_id=71,
        external_key="youtube-1",
        input_json={},
        input_hash="hash-1",
        parent_job_id=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )


def _attempt() -> PipelineJobAttemptRecord:
    return PipelineJobAttemptRecord(
        id=13,
        job_id=12,
        attempt_no=1,
        status="running",
        started_at=NOW,
        finished_at=None,
        worker_id="timeline-worker",
        error_type=None,
        error_message=None,
        output_json=None,
    )
