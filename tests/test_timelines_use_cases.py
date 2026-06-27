from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from codex_sdk_cli.domains.domain_knowledge.ports import (
    AliasKind,
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
    PromptPolicy,
)
from codex_sdk_cli.domains.micro_events.ports import (
    ContentKind,
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionWindowRecord,
    ProgramMode,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.prompts.constants import (
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
    PromptKey,
)
from codex_sdk_cli.domains.prompts.fallbacks import (
    fallback_prompt,
    fallback_prompt_text,
)
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.timelines.exceptions import TimelineCompositionOutputInvalid
from codex_sdk_cli.domains.timelines.ports import (
    TimelineComposeRequest,
    TimelineComposeResult,
    TimelineEpisodeRepairRequest,
    TimelineEpisodeRepairResult,
)
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest
from codex_sdk_cli.domains.timelines.use_cases import (
    ComposeTimelineUseCase,
    _ComposerInput,
    _composition_create,
    _composition_create_with_repairs,
    _task_input_hash,
    _task_input_json,
    _timeline_prompt,
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
        "episode episode_001 highlight_micro_event_ids truncated to 3" in create.validation_warnings
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
    assert "OVERBROAD_EPISODE" in flag_types
    assert "BOUNDARY_AMBIGUOUS" not in flag_types
    assert "ASR_SEMANTIC_RISK" in flag_types


def test_timeline_prompt_documents_output_limits_and_topic_cluster_keys() -> None:
    compose_prompt = fallback_prompt(TIMELINE_COMPOSE_PROMPT_KEY)
    prompt_text = compose_prompt.body
    prompt_sha = compose_prompt.body_sha256

    assert compose_prompt.version_label == "timeline-compose-v3"
    assert len(prompt_sha) == 64
    assert "topics는 episode마다 2~6개의 구체적인 명사구" in prompt_text
    assert "highlight_micro_event_ids는 episode 안의 핵심 후보만 0~3개" in prompt_text
    assert "META" in prompt_text
    assert "QNA" in prompt_text
    assert "OVERBROAD_EPISODE" in prompt_text
    assert '"topic_id": "topic_001"' in prompt_text
    assert '"display_label": "string"' in prompt_text
    assert '"episode_ids": ["episode_001", "episode_003"]' in prompt_text
    assert '"target_episode_id": "episode_001"' in fallback_prompt_text(
        TIMELINE_EPISODE_REPAIR_PROMPT_KEY
    )


def test_timeline_prompt_filters_domain_entries_like_micro_event_extraction() -> None:
    matching = _domain_entry(
        1,
        "치치",
        prompt_policy="AUTO_ON_MATCH",
        priority=10,
        aliases=[_domain_alias("치티", "ASR_ERROR")],
    )
    non_matching = _domain_entry(
        2,
        "쿠온 레이",
        prompt_policy="AUTO_ON_MATCH",
        priority=100,
        aliases=[_domain_alias("레이", "ALIAS")],
    )
    always = _domain_entry(
        3,
        "카네코 파냐",
        prompt_policy="ALWAYS_FOR_SCOPED_STREAMER",
        priority=50,
        aliases=[_domain_alias("파냐", "ALIAS")],
    )
    disabled = _domain_entry(
        4,
        "나부",
        prompt_policy="DISABLED",
        priority=1000,
        aliases=[_domain_alias("나부", "ALIAS")],
    )
    candidates = [
        _candidate(
            1,
            1,
            event="치티치 이야기를 한다.",
            program_mode="JUST_CHATTING",
            content_kind="META_CHAT",
        )
    ]
    composer_input = _composer_input(
        candidates,
        domain_entries=[matching, non_matching, always, disabled],
    )

    prompt = _timeline_prompt(composer_input)
    payload = json.loads(prompt.rsplit("\n", 1)[1])

    assert [entry["canonicalName"] for entry in payload["domain_entries"]] == [
        "카네코 파냐",
        "치치",
    ]


def test_timeline_task_input_json_includes_prompt_sha() -> None:
    input_json = _task_input_json(
        video=_video(),
        source_task=_video_task(91),
        source_fingerprint="abc123",
        input_hash="hash-1",
        copy_style="LIGHT_FANDOM_V1",
        model="gpt-5.5",
        reasoning_effort="medium",
        timeout_seconds=1200,
        prompt=fallback_prompt(TIMELINE_COMPOSE_PROMPT_KEY),
    )

    assert input_json["promptSha256"] == fallback_prompt(TIMELINE_COMPOSE_PROMPT_KEY).body_sha256
    assert len(str(input_json["promptSha256"])) == 64


def test_timeline_task_input_hash_changes_with_prompt_version() -> None:
    first_prompt = _timeline_db_prompt(version_id=201, sha="a" * 64)
    second_prompt = _timeline_db_prompt(version_id=202, sha="b" * 64)

    first_hash = _task_input_hash(
        video=_video(),
        source_task=_video_task(91),
        source_fingerprint="abc123",
        copy_style="LIGHT_FANDOM_V1",
        model="gpt-5.5",
        reasoning_effort="medium",
        prompt=first_prompt,
    )
    second_hash = _task_input_hash(
        video=_video(),
        source_task=_video_task(91),
        source_fingerprint="abc123",
        copy_style="LIGHT_FANDOM_V1",
        model="gpt-5.5",
        reasoning_effort="medium",
        prompt=second_prompt,
    )

    assert first_hash != second_hash


@pytest.mark.anyio
async def test_timeline_prepare_uses_requested_compose_prompt_version() -> None:
    requested_prompt = _timeline_db_prompt(
        version_id=201,
        version_label="timeline-db-v1",
        body="REQUESTED TIMELINE PROMPT\n",
        sha="a" * 64,
    )
    prompt_resolver = _TimelinePromptResolver(requested_prompt)
    use_case = ComposeTimelineUseCase(
        videos=cast(Any, _Noop()),
        video_tasks=cast(Any, _TimelineVideoTasks()),
        channels=cast(Any, _Noop()),
        streamers=cast(Any, _Noop()),
        domain_knowledge=cast(Any, _Noop()),
        micro_events=cast(Any, _TimelineMicroEvents()),
        timelines=cast(Any, _Noop()),
        pipeline_jobs=cast(Any, _Noop()),
        composer=cast(Any, _Noop()),
        prompt_resolver=prompt_resolver,
        timeout_seconds=1200,
        model="gpt-5.5",
        reasoning_effort="medium",
        events=cast(Any, _Noop()),
    )

    prepared = await use_case._prepare(
        _video(),
        TimelineComposeEnqueueRequest(
            target="selected_videos",
            videoIds=[71],
            promptVersionId=201,
        ),
    )

    assert prepared.prompt == requested_prompt
    assert prepared.input_json["promptVersionId"] == 201
    assert prepared.input_json["promptVersion"] == "timeline-db-v1"
    assert prepared.input_json["promptSource"] == "database"
    assert prepared.reasoning_effort == "high"
    assert prepared.input_json["reasoningEffort"] == "high"
    assert prompt_resolver.requested_version_ids == [201]


@pytest.mark.anyio
async def test_timeline_prepare_respects_requested_reasoning_effort() -> None:
    use_case = ComposeTimelineUseCase(
        videos=cast(Any, _Noop()),
        video_tasks=cast(Any, _TimelineVideoTasks()),
        channels=cast(Any, _Noop()),
        streamers=cast(Any, _Noop()),
        domain_knowledge=cast(Any, _Noop()),
        micro_events=cast(Any, _TimelineMicroEvents()),
        timelines=cast(Any, _Noop()),
        pipeline_jobs=cast(Any, _Noop()),
        composer=cast(Any, _Noop()),
        prompt_resolver=_TimelinePromptResolver(fallback_prompt(TIMELINE_COMPOSE_PROMPT_KEY)),
        timeout_seconds=1200,
        model="gpt-5.5",
        reasoning_effort="medium",
        events=cast(Any, _Noop()),
    )

    prepared = await use_case._prepare(
        _video(),
        TimelineComposeEnqueueRequest(
            target="selected_videos",
            videoIds=[71],
            reasoningEffort="medium",
        ),
    )

    assert prepared.reasoning_effort == "medium"
    assert prepared.input_json["reasoningEffort"] == "medium"


def test_timeline_normalizes_content_kind_values_in_viewer_tags() -> None:
    composer_input = _composer_input(_candidates(2))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0002",
                content_kind="QNA",
                viewer_tags=[
                    "QNA",
                    "OPINION",
                    "PERSONAL_STORY",
                    "META_CHAT",
                    "COMMUNITY_REVIEW",
                    "MEDIA_REVIEW",
                    "BREAK_TIME",
                    "NOT_A_TAG",
                    "QNA",
                ],
            )
        ],
    )

    create = _composition_create(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    assert create.episodes[0].viewer_tags == [
        "QNA",
        "INFORMATION",
        "STORY",
        "META",
        "COMMUNITY",
        "MEDIA",
    ]
    assert (
        "episode episode_001 viewer_tags mapped content kind value in viewer_tags: "
        "OPINION -> INFORMATION"
    ) in create.validation_warnings
    assert (
        "episode episode_001 viewer_tags removed content kind value "
        "from viewer_tags: BREAK_TIME" in create.validation_warnings
    )
    assert (
        "episode episode_001 viewer_tags removed unknown viewer tag: NOT_A_TAG"
        in create.validation_warnings
    )
    assert "episode episode_001 viewer_tags duplicate viewer tag removed: QNA" in (
        create.validation_warnings
    )


def test_timeline_all_invalid_viewer_tags_can_normalize_to_empty_list() -> None:
    composer_input = _composer_input(_candidates(2))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0002",
                viewer_tags=["BREAK_TIME", "NOT_A_TAG"],
            )
        ],
    )

    create = _composition_create(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    assert create.episodes[0].viewer_tags == []
    assert (
        "episode episode_001 viewer_tags removed content kind value "
        "from viewer_tags: BREAK_TIME" in create.validation_warnings
    )
    assert (
        "episode episode_001 viewer_tags removed unknown viewer tag: NOT_A_TAG"
        in create.validation_warnings
    )


def test_timeline_legacy_overbroad_flag_is_normalized() -> None:
    composer_input = _composer_input(_candidates(2))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[_episode_output("episode_001", "me_0001", "me_0002")],
        review_flags=[
            {
                "start_micro_event_id": "me_0001",
                "end_micro_event_id": "me_0002",
                "type": "OVERBROAD_MICRO_EVENT",
                "reason": "legacy flag",
            }
        ],
    )

    create = _composition_create(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    assert create.review_flags[0].type == "OVERBROAD_EPISODE"


def test_timeline_composition_normalizes_polite_style_but_keeps_raw_response() -> None:
    polite_summary = "\uac8c\uc784\uc774 \uc774\uc5b4\uc9d1\ub2c8\ub2e4."
    polite_block = "\ub300\ud654\ub97c \ub098\ub215\ub2c8\ub2e4."
    polite_episode = "\uc2dc\uc791\ud569\ub2c8\ub2e4."
    polite_topic = "\uad6c\uac04\uc785\ub2c8\ub2e4."
    polite_flag = "\uc790\ub8cc\uac00 \uc788\uc2b5\ub2c8\ub2e4."
    output_json = {
        "video_summary": {
            "title": "\ud14c\uc2a4\ud2b8",
            "summary": polite_summary,
            "display_title": "\ud14c\uc2a4\ud2b8",
            "display_summary": polite_summary,
            "main_topics": ["topic"],
        },
        "blocks": [
            {
                **_block_output(
                    "block_001",
                    "JUST_CHATTING",
                    ["episode_001", "episode_002"],
                ),
                "summary": polite_block,
                "display_summary": polite_block,
            }
        ],
        "episodes": [
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0002",
                summary=polite_episode,
            ),
            _episode_output("episode_002", "me_0003", "me_0004"),
        ],
        "topic_clusters": [
            {
                "topic_id": "topic_001",
                "label": polite_topic,
                "summary": polite_topic,
                "display_label": polite_topic,
                "episode_ids": ["episode_001", "episode_002"],
            }
        ],
        "review_flags": [
            {
                "start_micro_event_id": "me_0001",
                "end_micro_event_id": "me_0002",
                "type": "BOUNDARY_AMBIGUOUS",
                "reason": polite_flag,
            }
        ],
    }
    result = _compose_result(output_json)

    create = _composition_create(
        _composer_input(_candidates(4)),
        result,
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    assert create.display_summary == "\uac8c\uc784\uc774 \uc774\uc5b4\uc9c4\ub2e4."
    assert create.blocks[0].display_summary == "\ub300\ud654\ub97c \ub098\ub208\ub2e4."
    assert create.episodes[0].display_summary == "\uc2dc\uc791\ud55c\ub2e4."
    assert create.topic_clusters[0].summary == "\uad6c\uac04\uc774\ub2e4."
    assert create.review_flags[0].reason == "\uc790\ub8cc\uac00 \uc788\ub2e4."
    assert create.output_json["episodes"][0]["display_summary"] == "\uc2dc\uc791\ud55c\ub2e4."
    assert create.output_json["review_flags"][0]["reason"] == "\uc790\ub8cc\uac00 \uc788\ub2e4."
    assert create.raw_response_text == result.final_response
    assert create.raw_response_text is not None
    raw_output_json = json.loads(create.raw_response_text)
    assert raw_output_json["episodes"][0]["summary"] == polite_episode


def test_timeline_repairs_post_game_break_and_closing_blocks() -> None:
    composer_input = _composer_input(_candidates(8))
    output_json = _timeline_output(
        blocks=[
            _block_output("block_001", "POST_GAME", ["episode_001", "episode_002", "episode_003"]),
            _block_output("block_002", "BREAK", ["episode_004"]),
            _block_output("block_003", "CLOSING", ["episode_005", "episode_006"]),
        ],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0002",
                title="게임 엔딩 회고",
                summary="게임 엔딩과 플레이를 돌아본다.",
                program_mode="POST_GAME",
                content_kind="GAME_DISCUSSION",
            ),
            _episode_output(
                "episode_002",
                "me_0003",
                "me_0003",
                title="운전면허 이야기",
                summary="운전면허와 교통 이야기를 한다.",
                program_mode="POST_GAME",
                content_kind="PERSONAL_STORY",
            ),
            _episode_output(
                "episode_003",
                "me_0004",
                "me_0004",
                title="수면과 건강 이야기",
                summary="잠과 건강 이야기를 한다.",
                program_mode="POST_GAME",
                content_kind="QNA",
            ),
            _episode_output(
                "episode_004",
                "me_0005",
                "me_0005",
                program_mode="BREAK",
                content_kind="BREAK_TIME",
            ),
            _episode_output(
                "episode_005",
                "me_0006",
                "me_0006",
                title="청소 이야기",
                summary="방 정리와 청소 이야기를 한다.",
                program_mode="CLOSING",
                content_kind="PERSONAL_STORY",
            ),
            _episode_output(
                "episode_006",
                "me_0007",
                "me_0008",
                title="오늘도 고마워",
                summary="시청자에게 감사 인사를 하고 방송을 마무리한다.",
                program_mode="CLOSING",
                content_kind="META_CHAT",
            ),
        ],
    )

    create = _composition_create(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
    )

    block_types = [block.block_type for block in create.blocks]
    assert block_types == ["POST_GAME", "JUST_CHATTING", "CLOSING"]
    assert create.episodes[3].visibility == "COLLAPSED"
    assert create.episodes[3].parent_block_id == "block_002"
    assert create.episodes[4].program_mode == "JUST_CHATTING"


@pytest.mark.anyio
async def test_timeline_partial_repair_splits_only_overbroad_episode() -> None:
    composer_input = _composer_input(_candidates(12))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0012",
                topics=[f"주제{i}" for i in range(1, 7)],
            )
        ],
    )
    composer = _RepairComposer(
        [
            {
                "target_episode_id": "episode_001",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0001", "me_0004", "중국집 식사 이야기"),
                    _repair_episode_output("me_0005", "me_0008", "일본어 수업 이야기"),
                    _repair_episode_output("me_0009", "me_0012", "포켓몬 추천 이야기"),
                ],
                "reason": "separate topics",
            }
        ]
    )

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
    )

    assert len(composer.requests) == 1
    assert [episode.start_micro_event_candidate_id for episode in create.episodes] == [1, 5, 9]
    assert [episode.end_micro_event_candidate_id for episode in create.episodes] == [4, 8, 12]
    assert len(create.review_flags) == 0


@pytest.mark.anyio
async def test_timeline_partial_repair_keep_preserves_episode_and_flags() -> None:
    composer_input = _composer_input(_candidates(12))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0012",
                topics=[f"주제{i}" for i in range(1, 7)],
            )
        ],
    )
    composer = _RepairComposer(
        [{"target_episode_id": "episode_001", "action": "KEEP", "replacement_episodes": []}]
    )

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
    )

    assert len(create.episodes) == 1
    assert {flag.type for flag in create.review_flags} == {"OVERBROAD_EPISODE"}


@pytest.mark.anyio
async def test_timeline_coverage_repair_fills_missing_micro_event_gap() -> None:
    composer_input = _composer_input(_candidates(4))
    output_json = _timeline_output(
        blocks=[
            _block_output(
                "block_001",
                "JUST_CHATTING",
                ["episode_001", "episode_002"],
            )
        ],
        episodes=[
            _episode_output("episode_001", "me_0001", "me_0002"),
            _episode_output("episode_002", "me_0004", "me_0004"),
        ],
    )
    composer = _RepairComposer(
        [
            {
                "target_episode_id": "episode_recovery_001",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0003", "me_0003", "missing bridge"),
                ],
                "reason": "fill missing micro-event",
            }
        ]
    )
    raw_responses = []

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
        raw_responses=raw_responses,
    )

    assert len(composer.requests) == 1
    assert composer.requests[0].target_episode_id == "episode_recovery_001"
    assert [episode.start_micro_event_candidate_id for episode in create.episodes] == [
        1,
        3,
        4,
    ]
    assert [episode.end_micro_event_candidate_id for episode in create.episodes] == [
        2,
        3,
        4,
    ]
    assert create.blocks[0].episode_ids == [
        "episode_001",
        "episode_recovery_001",
        "episode_002",
    ]
    assert raw_responses[0].operation == "repair_episode"
    assert raw_responses[0].target_episode_id == "episode_recovery_001"
    assert any(
        "coverage repair episode_recovery_001 inserted" in item
        for item in create.validation_warnings
    )


@pytest.mark.anyio
async def test_timeline_coverage_repair_rewrites_overlapping_episode_window() -> None:
    composer_input = _composer_input(_candidates(4))
    output_json = _timeline_output(
        blocks=[
            _block_output(
                "block_001",
                "JUST_CHATTING",
                ["episode_001", "episode_002"],
            )
        ],
        episodes=[
            _episode_output("episode_001", "me_0001", "me_0003"),
            _episode_output("episode_002", "me_0003", "me_0004"),
        ],
    )
    composer = _RepairComposer(
        [
            {
                "target_episode_id": "episode_001",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0001", "me_0002", "first topic"),
                    _repair_episode_output("me_0003", "me_0004", "second topic"),
                ],
                "reason": "remove overlap",
            }
        ]
    )

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
    )

    assert len(composer.requests) == 1
    assert composer.requests[0].target_episode_id == "episode_001"
    assert [episode.episode_id for episode in create.episodes] == [
        "episode_001",
        "episode_001_split_002",
    ]
    assert [episode.start_micro_event_candidate_id for episode in create.episodes] == [1, 3]
    assert [episode.end_micro_event_candidate_id for episode in create.episodes] == [2, 4]
    assert create.blocks[0].episode_ids == [
        "episode_001",
        "episode_001_split_002",
    ]


@pytest.mark.anyio
async def test_timeline_block_semantic_repair_preserves_episode_order() -> None:
    composer_input = _composer_input(_candidates(4))
    output_json = _timeline_output(
        blocks=[
            _block_output("block_001", "JUST_CHATTING", ["episode_001"]),
            _block_output("block_002", "GAMEPLAY", ["episode_003", "episode_004"]),
        ],
        episodes=[
            _episode_output("episode_001", "me_0001", "me_0001"),
            _episode_output("episode_002", "me_0002", "me_0002"),
            _episode_output("episode_003", "me_0003", "me_0003"),
            _episode_output("episode_004", "me_0004", "me_0004"),
        ],
    )
    composer = _RepairComposer([])

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
    )

    assert composer.requests == []
    assert [episode.episode_id for episode in create.episodes] == [
        "episode_001",
        "episode_002",
        "episode_003",
        "episode_004",
    ]
    assert [episode_id for block in create.blocks for episode_id in block.episode_ids] == [
        "episode_001",
        "episode_002",
        "episode_003",
        "episode_004",
    ]
    assert any(
        "block semantic repair rebuilt block refs from episode order" in item
        for item in create.validation_warnings
    )


@pytest.mark.anyio
async def test_timeline_coverage_repair_handles_more_than_three_gaps() -> None:
    composer_input = _composer_input(_candidates(8))
    output_json = _timeline_output(
        blocks=[
            _block_output(
                "block_001",
                "JUST_CHATTING",
                ["episode_001", "episode_002", "episode_003", "episode_004"],
            )
        ],
        episodes=[
            _episode_output("episode_001", "me_0001", "me_0001"),
            _episode_output("episode_002", "me_0003", "me_0003"),
            _episode_output("episode_003", "me_0005", "me_0005"),
            _episode_output("episode_004", "me_0007", "me_0007"),
        ],
    )
    composer = _RepairComposer(
        [
            {
                "target_episode_id": "episode_recovery_001",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0002", "me_0002", "missing 2"),
                ],
                "reason": "fill missing micro-event",
            },
            {
                "target_episode_id": "episode_recovery_002",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0004", "me_0004", "missing 4"),
                ],
                "reason": "fill missing micro-event",
            },
            {
                "target_episode_id": "episode_recovery_003",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0006", "me_0006", "missing 6"),
                ],
                "reason": "fill missing micro-event",
            },
            {
                "target_episode_id": "episode_recovery_004",
                "action": "SPLIT",
                "replacement_episodes": [
                    _repair_episode_output("me_0008", "me_0008", "missing 8"),
                ],
                "reason": "fill missing micro-event",
            },
        ]
    )

    create = await _composition_create_with_repairs(
        composer_input,
        _compose_result(output_json),
        task=_video_task(),
        job=_job(),
        attempt=_attempt(),
        composer=composer,
        timeout_seconds=30,
    )

    assert len(composer.requests) == 4
    assert [episode.start_micro_event_candidate_id for episode in create.episodes] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
    ]
    assert [episode.end_micro_event_candidate_id for episode in create.episodes] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
    ]


@pytest.mark.anyio
async def test_timeline_failure_stores_raw_response_only_on_failed_attempt() -> None:
    composer_input = _composer_input(_candidates(3))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001"])],
        episodes=[_episode_output("episode_001", "me_0002", "me_0003")],
    )
    composer = _ComposeAndRepairComposer(compose_output=output_json)
    pipeline_jobs = _TimelinePipelineJobsForFailure()
    video_tasks = _TimelineVideoTasksForFailure()
    events = _TimelineEvents()
    use_case = _timeline_failure_use_case(
        composer=composer,
        pipeline_jobs=pipeline_jobs,
        video_tasks=video_tasks,
        events=events,
    )

    with pytest.raises(TimelineCompositionOutputInvalid):
        await use_case._execute_job_attempt(
            _job(),
            _attempt(),
            task=_video_task(),
            composer_input=composer_input,
            timeout_seconds=30,
        )

    assert pipeline_jobs.failed_attempt_output_json is not None
    assert video_tasks.failed_task_output_json is not None
    raw_responses = pipeline_jobs.failed_attempt_output_json["rawResponses"]
    assert isinstance(raw_responses, list)
    assert len(raw_responses) == 1
    raw_response = raw_responses[0]
    assert isinstance(raw_response, dict)
    assert raw_response["operation"] == "compose_video"
    assert raw_response["threadId"] == "compose-thread"
    assert raw_response["turnId"] == "compose-turn"
    assert raw_response["rawResponseText"] == composer.compose_response_text
    assert raw_response["rawResponseLength"] == len(composer.compose_response_text)
    assert len(str(raw_response["rawResponseSha256"])) == 64
    assert pipeline_jobs.failed_attempt_output_json["failure"] == {
        "errorType": "TimelineCompositionOutputInvalid",
        "errorMessage": "Timeline episodes must cover every micro-event exactly once in order.",
        "stage": "compose_output_validation",
    }
    assert video_tasks.failed_task_output_json["rawResponseCount"] == 1
    assert "rawResponses" not in video_tasks.failed_task_output_json
    assert composer.compose_response_text not in json.dumps(video_tasks.failed_task_output_json)
    assert events.items[0].metadata_json["rawResponseCount"] == 1
    assert "rawResponses" not in events.items[0].metadata_json
    assert composer.compose_response_text not in json.dumps(events.items[0].metadata_json)


@pytest.mark.anyio
async def test_timeline_failure_stores_compose_and_repair_raw_responses() -> None:
    composer_input = _composer_input(_candidates(14))
    output_json = _timeline_output(
        blocks=[_block_output("block_001", "JUST_CHATTING", ["episode_001", "episode_002"])],
        episodes=[
            _episode_output(
                "episode_001",
                "me_0001",
                "me_0012",
                topics=[f"topic-{i}" for i in range(1, 7)],
            ),
            _episode_output("episode_002", "me_0014", "me_0014"),
        ],
    )
    repair_output: dict[str, object] = {
        "target_episode_id": "episode_001",
        "action": "SPLIT",
        "replacement_episodes": [
            _repair_episode_output("me_0001", "me_0004", "topic A"),
            _repair_episode_output("me_0005", "me_0008", "topic B"),
            _repair_episode_output("me_0009", "me_0012", "topic C"),
        ],
        "reason": "separate topics",
    }
    composer = _ComposeAndRepairComposer(
        compose_output=output_json,
        repair_outputs=[repair_output],
    )
    pipeline_jobs = _TimelinePipelineJobsForFailure()
    use_case = _timeline_failure_use_case(
        composer=composer,
        pipeline_jobs=pipeline_jobs,
        video_tasks=_TimelineVideoTasksForFailure(),
        events=_TimelineEvents(),
    )

    with pytest.raises(TimelineCompositionOutputInvalid):
        await use_case._execute_job_attempt(
            _job(),
            _attempt(),
            task=_video_task(),
            composer_input=composer_input,
            timeout_seconds=30,
        )

    assert pipeline_jobs.failed_attempt_output_json is not None
    raw_responses = pipeline_jobs.failed_attempt_output_json["rawResponses"]
    assert isinstance(raw_responses, list)
    assert [item["operation"] for item in raw_responses if isinstance(item, dict)] == [
        "compose_video",
        "repair_episode",
    ]
    repair_response = raw_responses[1]
    assert isinstance(repair_response, dict)
    assert repair_response["targetEpisodeId"] == "episode_001"
    assert repair_response["rawResponseText"] == composer.repair_response_texts[0]


def _composer_input(
    candidates: list[MicroEventCandidateRecord],
    *,
    domain_entries: list[DomainKnowledgePromptEntryRecord] | None = None,
) -> _ComposerInput:
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
        domain_entries=domain_entries or [],
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
        compose_prompt=fallback_prompt(TIMELINE_COMPOSE_PROMPT_KEY),
        repair_prompt=fallback_prompt(TIMELINE_EPISODE_REPAIR_PROMPT_KEY),
    )


def _timeline_db_prompt(
    *,
    version_id: int,
    sha: str,
    version_label: str | None = None,
    body: str | None = None,
) -> ResolvedPrompt:
    return ResolvedPrompt(
        key=TIMELINE_COMPOSE_PROMPT_KEY,
        version_id=version_id,
        version_label=version_label or f"timeline-db-v{version_id}",
        body=body or f"TIMELINE PROMPT {version_id}\n",
        body_sha256=sha,
        source="database",
    )


def _source_detail(
    candidates: list[MicroEventCandidateRecord],
) -> MicroEventExtractionDetailRecord:
    return MicroEventExtractionDetailRecord(
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
        windows=[
            MicroEventExtractionWindowRecord(
                id=1,
                video_task_id=91,
                video_id=71,
                transcript_id=47,
                window_index=1,
                start_cue_id="tr47-c000001",
                end_cue_id="tr47-c000002",
                cue_count=2,
                status="succeeded",
                carry_out_unfinished=False,
                codex_thread_id=None,
                codex_turn_id=None,
                raw_response_text=None,
                parsed_response_json=None,
                validation_error=None,
                source_job_id=12,
                source_job_attempt_id=13,
                created_at=NOW,
                updated_at=NOW,
                micro_events=candidates,
            )
        ],
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
    viewer_tags: list[str] | None = None,
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
        "viewer_tags": viewer_tags or ["META"],
        "highlight_micro_event_ids": highlights or [start_micro_event_id],
        "visibility": "DEFAULT",
    }


def _timeline_output(
    *,
    blocks: list[dict[str, object]],
    episodes: list[dict[str, object]],
    review_flags: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "video_summary": {"title": "테스트 타임라인"},
        "blocks": blocks,
        "episodes": episodes,
        "topic_clusters": [],
        "review_flags": review_flags or [],
    }


def _block_output(
    block_id: str,
    block_type: str,
    episode_ids: list[str],
) -> dict[str, object]:
    return {
        "block_id": block_id,
        "block_type": block_type,
        "title": block_type,
        "summary": block_type,
        "display_title": block_type,
        "display_summary": block_type,
        "episode_ids": episode_ids,
    }


def _compose_result(output_json: dict[str, object]) -> TimelineComposeResult:
    return TimelineComposeResult(
        thread_id="thread-1",
        turn_id="turn-1",
        status="completed",
        final_response=json.dumps(output_json),
    )


def _repair_episode_output(
    start_micro_event_id: str,
    end_micro_event_id: str,
    title: str,
) -> dict[str, object]:
    return {
        "start_micro_event_id": start_micro_event_id,
        "end_micro_event_id": end_micro_event_id,
        "program_mode": "JUST_CHATTING",
        "primary_content_kind": "PERSONAL_STORY",
        "title": title,
        "summary": title,
        "display_title": title,
        "display_summary": title,
        "topics": [title, "보조 주제"],
        "viewer_tags": ["STORY"],
        "highlight_micro_event_ids": [start_micro_event_id],
        "visibility": "DEFAULT",
    }


def _domain_entry(
    entry_id: int,
    canonical_name: str,
    *,
    prompt_policy: str,
    priority: int,
    aliases: list[DomainKnowledgePromptAliasRecord],
) -> DomainKnowledgePromptEntryRecord:
    return DomainKnowledgePromptEntryRecord(
        entry_id=entry_id,
        type_key="person",
        type_label="Person",
        canonical_name=canonical_name,
        display_name=None,
        disambiguation=None,
        detail=None,
        prompt_policy=cast(PromptPolicy, prompt_policy),
        priority=priority,
        aliases=aliases,
    )


def _domain_alias(
    surface_form: str,
    alias_kind: str,
) -> DomainKnowledgePromptAliasRecord:
    return DomainKnowledgePromptAliasRecord(
        surface_form=surface_form,
        alias_kind=cast(AliasKind, alias_kind),
        certainty="HIGH",
        apply_scope="SEARCH_AND_SUMMARY",
        language_code="ko",
        note=None,
    )


class _RepairComposer:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self._outputs = list(outputs)
        self.requests: list[TimelineEpisodeRepairRequest] = []

    async def compose(self, request: TimelineComposeRequest) -> TimelineComposeResult:
        raise AssertionError("compose should not be called by repair tests")

    async def repair_episode(
        self,
        request: TimelineEpisodeRepairRequest,
    ) -> TimelineEpisodeRepairResult:
        self.requests.append(request)
        output = self._outputs.pop(0)
        return TimelineEpisodeRepairResult(
            thread_id="repair-thread",
            turn_id="repair-turn",
            status="completed",
            final_response=json.dumps(output),
        )


class _ComposeAndRepairComposer:
    def __init__(
        self,
        *,
        compose_output: dict[str, object],
        repair_outputs: list[dict[str, object]] | None = None,
    ) -> None:
        self.compose_response_text = json.dumps(compose_output)
        self.repair_response_texts = [json.dumps(output) for output in repair_outputs or []]
        self.repair_requests: list[TimelineEpisodeRepairRequest] = []

    async def compose(self, request: TimelineComposeRequest) -> TimelineComposeResult:
        return TimelineComposeResult(
            thread_id="compose-thread",
            turn_id="compose-turn",
            status="completed",
            final_response=self.compose_response_text,
        )

    async def repair_episode(
        self,
        request: TimelineEpisodeRepairRequest,
    ) -> TimelineEpisodeRepairResult:
        self.repair_requests.append(request)
        return TimelineEpisodeRepairResult(
            thread_id="repair-thread",
            turn_id="repair-turn",
            status="completed",
            final_response=self.repair_response_texts[len(self.repair_requests) - 1],
        )


class _TimelinePipelineJobsForFailure:
    def __init__(self) -> None:
        self.failed_attempt_output_json: JsonObject | None = None

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> PipelineJobAttemptRecord:
        self.failed_attempt_output_json = output_json
        return PipelineJobAttemptRecord(
            id=attempt_id,
            job_id=12,
            attempt_no=1,
            status="failed",
            started_at=NOW,
            finished_at=NOW,
            worker_id="timeline-worker",
            error_type=error_type,
            error_message=error_message,
            output_json=output_json,
        )

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return _job()


class _TimelineVideoTasksForFailure:
    def __init__(self) -> None:
        self.failed_task_output_json: JsonObject | None = None

    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        self.failed_task_output_json = output_json
        return _video_task(task_id)

    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        self.failed_task_output_json = output_json
        return _video_task(task_id)


class _TimelineStoreForFailure:
    async def delete_composition(self, video_task_id: int) -> None:
        return None


class _TimelineEvents:
    def __init__(self) -> None:
        self.items: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.items.append(event)


def _timeline_failure_use_case(
    *,
    composer: _ComposeAndRepairComposer,
    pipeline_jobs: _TimelinePipelineJobsForFailure,
    video_tasks: _TimelineVideoTasksForFailure,
    events: _TimelineEvents,
) -> ComposeTimelineUseCase:
    return ComposeTimelineUseCase(
        videos=cast(Any, _Noop()),
        video_tasks=cast(Any, video_tasks),
        channels=cast(Any, _Noop()),
        streamers=cast(Any, _Noop()),
        domain_knowledge=cast(Any, _Noop()),
        micro_events=cast(Any, _Noop()),
        timelines=cast(Any, _TimelineStoreForFailure()),
        pipeline_jobs=cast(Any, pipeline_jobs),
        composer=cast(Any, composer),
        prompt_resolver=cast(Any, _Noop()),
        timeout_seconds=1200,
        model="gpt-5.5",
        reasoning_effort="medium",
        events=events,
    )


class _Noop:
    pass


class _TimelinePromptResolver:
    def __init__(self, requested_prompt: ResolvedPrompt) -> None:
        self._requested_prompt = requested_prompt
        self.requested_version_ids: list[int | None] = []

    async def resolve_prompt(self, prompt_key: PromptKey) -> ResolvedPrompt:
        return fallback_prompt(prompt_key)

    async def resolve_prompt_for_request(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        self.requested_version_ids.append(version_id)
        return self._requested_prompt

    async def resolve_prompt_version(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        return self._requested_prompt


class _TimelineVideoTasks:
    async def get_latest_succeeded_task_for_video(
        self,
        *,
        video_id: int,
        task_name: str,
    ) -> VideoTaskRecord | None:
        return _video_task(task_id=91)


class _TimelineMicroEvents:
    async def get_extraction(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        return _source_detail(_candidates(2))


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
