from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueRequest,
    TimelinePatchRequest,
)


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
            ],
            "publish": {"enabled": True, "schemaVersion": 1},
        }
    )

    assert request.dry_run is False
    assert request.operations[0].anchor_episode_id == "episode_001"
    assert request.operations[1].target_type == "block"
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
