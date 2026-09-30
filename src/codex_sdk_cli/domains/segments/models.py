from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

SegmentCategory = Literal["chat", "game", "sing", "watch", "cafe", "setup", "asmr", "other"]
TAXONOMY_VERSION = "v1.6"
POLICY_VERSION = "v1"
SEGMENT_TASK = "segment_classify"
SEGMENT_TASK_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class EpisodeRange:
    episode_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class SegmentSource:
    video_id: int
    timeline_work_item_id: int
    composition_id: int
    payload: dict[str, object]
    episodes: tuple[EpisodeRange, ...]
    empty: bool = False

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.payload)


def fingerprint(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


class SegmentClassificationError(RuntimeError):
    error_code = "segments.invalid_output"


class SegmentSourceChangedError(SegmentClassificationError):
    error_code = "segments.source_changed"
