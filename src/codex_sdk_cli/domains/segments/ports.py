from typing import Protocol


class SegmentPublicationReaderPort(Protocol):
    async def load(self, input_json: dict[str, object]) -> dict[str, object]:
        """Validate pinned classification and timeline, then return public fields."""
