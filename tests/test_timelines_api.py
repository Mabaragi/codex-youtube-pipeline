from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueRequest,
    TimelinePatchRequest,
)
from tests.support.legacy_api import create_legacy_app as create_app


def test_timeline_compose_openapi_paths_and_aliases() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/video-tasks/timeline-compose/enqueue"]["post"]["tags"] == [
        "timelines"
    ]
    assert schema["paths"]["/videos/{video_id}/timelines/latest"]["get"]["tags"] == [
        "timelines"
    ]
    assert schema["paths"]["/videos/{video_id}/timelines/{video_task_id}"]["get"][
        "tags"
    ] == ["timelines"]
    assert schema["paths"]["/videos/{videoId}/timelines/{videoTaskId}/patch"]["post"][
        "tags"
    ] == ["timelines"]
    assert schema["paths"]["/videos/{videoId}/timelines/{videoTaskId}/patch"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/TimelinePatchResponse"
    )
    patch_schema = schema["components"]["schemas"]["TimelinePatchResponse"]
    assert "publishSummary" in patch_schema["properties"]
    operation_schema = schema["components"]["schemas"]["TimelinePatchOperationRequest"]
    assert "edit_micro_event_copy" in operation_schema["properties"]["operation"]["enum"]
    assert "edit_topic_cluster_copy" in operation_schema["properties"]["operation"]["enum"]
    assert "targetMicroEventCandidateId" in operation_schema["properties"]
    assert "expectedEpisodeId" in operation_schema["properties"]
    assert "targetTopicId" in operation_schema["properties"]
    operation_result_schema = schema["components"]["schemas"][
        "TimelinePatchOperationResultResponse"
    ]
    assert "changedMicroEventCandidateIds" in operation_result_schema["properties"]
    assert "changedTopicIds" in operation_result_schema["properties"]
    assert schema["paths"]["/video-tasks/timeline-compose/enqueue"]["post"][
        "responses"
    ]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/TimelineComposeEnqueueResponse"
    )
    episode_schema = schema["components"]["schemas"]["TimelineEpisodeResponse"]
    viewer_tag_enum = episode_schema["properties"]["viewerTags"]["items"]["enum"]
    assert "QNA" in viewer_tag_enum
    review_schema = schema["components"]["schemas"]["TimelineReviewFlagResponse"]
    review_flag_enum = review_schema["properties"]["type"]["enum"]
    assert "OVERBROAD_EPISODE" in review_flag_enum
    assert "OVERBROAD_MICRO_EVENT" in review_flag_enum

    request = TimelineComposeEnqueueRequest.model_validate(
        {
            "target": "current_filters",
            "channelId": 1,
            "taskStatus": "succeeded",
            "limit": 5,
            "retryFailed": True,
            "regenerateSucceeded": False,
            "copyStyle": "LIGHT_FANDOM_V1",
            "model": "gpt-5.4",
            "reasoningEffort": "high",
        }
    )

    assert request.channel_id == 1
    assert request.task_status == "succeeded"
    assert request.retry_failed is True
    assert request.reasoning_effort == "high"


def test_timeline_patch_request_validation() -> None:
    request = TimelinePatchRequest.model_validate(
        {
            "dryRun": False,
            "instruction": "Split after the selected episode.",
            "operations": [
                {
                    "operation": "split_block_after_episode",
                    "anchorEpisodeId": "episode_001",
                    "newBlock": {"displayTitle": "Next scene"},
                },
                {
                    "operation": "edit_display_copy",
                    "targetType": "block",
                    "targetId": "block_002",
                    "displaySummary": "A lighter display summary",
                },
                {
                    "operation": "edit_micro_event_copy",
                    "targetMicroEventCandidateId": 123,
                    "expectedEpisodeId": "episode_002",
                    "event": "The streamer cries over the scene.",
                },
                {
                    "operation": "edit_topic_cluster_copy",
                    "targetTopicId": "topic_001",
                    "displayLabel": "Crying reaction flow",
                    "summary": "The topic summary highlights the crying reaction.",
                },
            ],
            "publish": {"enabled": True, "schemaVersion": 1},
        }
    )

    assert request.dry_run is False
    assert request.operations[0].anchor_episode_id == "episode_001"
    assert request.operations[1].target_type == "block"
    assert request.operations[2].target_micro_event_candidate_id == 123
    assert request.operations[2].expected_episode_id == "episode_002"
    assert request.operations[3].target_topic_id == "topic_001"
    assert request.operations[3].display_label == "Crying reaction flow"
    assert request.publish is not None
    assert request.publish.enabled is True

    with pytest.raises(ValidationError, match="publish.enabled requires dryRun=false"):
        TimelinePatchRequest.model_validate(
            {
                "dryRun": True,
                "operations": [
                    {
                        "operation": "edit_display_copy",
                        "targetType": "video",
                        "displayTitle": "Title",
                    }
                ],
                "publish": {"enabled": True},
            }
        )

    with pytest.raises(ValidationError, match="requires targetId"):
        TimelinePatchRequest.model_validate(
            {
                "operations": [
                    {
                        "operation": "edit_display_copy",
                        "targetType": "episode",
                        "displaySummary": "Summary",
                    }
                ]
            }
        )

    with pytest.raises(ValidationError, match="requires event"):
        TimelinePatchRequest.model_validate(
            {
                "operations": [
                    {
                        "operation": "edit_micro_event_copy",
                        "targetMicroEventCandidateId": 123,
                    }
                ]
            }
        )

    with pytest.raises(ValidationError, match="requires displayLabel or summary"):
        TimelinePatchRequest.model_validate(
            {
                "operations": [
                    {
                        "operation": "edit_topic_cluster_copy",
                        "targetTopicId": "topic_001",
                    }
                ]
            }
        )
