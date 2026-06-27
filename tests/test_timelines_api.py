from __future__ import annotations

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest


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
