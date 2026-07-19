from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing_extensions import override

from codex_sdk_cli.domains.video_availability.exceptions import (
    VideoAvailabilityInboxError,
)
from codex_sdk_cli.domains.video_availability.ports import (
    VideoAvailabilityCandidate,
    VideoAvailabilityCandidateInboxPort,
    VideoAvailabilityResolution,
)


class _CandidatePayload(BaseModel):
    candidate_id: int | str = Field(alias="candidateId")
    lease_token: str = Field(alias="leaseToken")
    environment: str
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _ClaimResponse(BaseModel):
    candidates: list[_CandidatePayload]

    model_config = ConfigDict(extra="ignore")


class VideoAvailabilityCandidateClient(VideoAvailabilityCandidateInboxPort):
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str,
        admin_token: str,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        }

    @override
    async def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> tuple[VideoAvailabilityCandidate, ...]:
        payload = await self._post_json(
            "/claim",
            {
                "workerId": worker_id,
                "limit": limit,
                "leaseSeconds": lease_seconds,
            },
        )
        try:
            response = _ClaimResponse.model_validate(payload)
        except ValidationError as exc:
            raise VideoAvailabilityInboxError(
                "Availability claim response was invalid."
            ) from exc
        return tuple(
            VideoAvailabilityCandidate(
                candidate_id=item.candidate_id,
                lease_token=item.lease_token,
                environment=item.environment,
                video_id=item.video_id,
                youtube_video_id=item.youtube_video_id,
            )
            for item in response.candidates
        )

    @override
    async def resolve(
        self,
        resolutions: tuple[VideoAvailabilityResolution, ...],
    ) -> None:
        if not resolutions:
            return
        await self._post_json(
            "/resolve",
            {
                "results": [
                    {
                        "candidateId": item.candidate_id,
                        "leaseToken": item.lease_token,
                        "outcome": item.outcome,
                        "reason": item.reason,
                        "checkedAt": item.checked_at.isoformat(),
                    }
                    for item in resolutions
                ]
            },
        )

    @override
    async def cleanup(self) -> int:
        payload = await self._post_json("/cleanup", {})
        for key in ("recoveredCount", "cleanedCount", "updatedCount"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return 0

    async def _post_json(self, path: str, body: dict[str, object]) -> dict[str, Any]:
        try:
            response = await self._http_client.post(
                f"{self._base_url}{path}",
                headers=self._headers,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise VideoAvailabilityInboxError(
                "Availability inbox request failed."
            ) from exc
        if not response.is_success:
            raise VideoAvailabilityInboxError(
                f"Availability inbox returned HTTP {response.status_code}: "
                f"{_response_message(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoAvailabilityInboxError(
                "Availability inbox response was not JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise VideoAvailabilityInboxError(
                "Availability inbox response was invalid."
            )
        return payload


def _response_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"][:300]
    return str(payload)[:300]
