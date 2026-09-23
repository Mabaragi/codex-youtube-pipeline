from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_sdk_cli.domains.transcript_cues.generation import (
    TranscriptCueSegmentInput,
    build_transcript_cues,
)
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRecord
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptFetchResult
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptResponse,
    TranscriptStorageResponse,
)

from .files import FileWindowCheckpoints, RunLock, file_sha256, read_json, write_json


class LocalRunStore:
    def create_plan(
        self,
        *,
        output_root: Path,
        video_id: str,
        plan_hash: str,
        plan: dict[str, object],
        caption: YouTubeTranscriptFetchResult | None,
    ) -> Path:
        run_dir = output_root.resolve() / video_id / plan_hash[:16]
        with self.lock(run_dir):
            path = run_dir / "plan.json"
            if path.exists():
                if read_json(path) != plan:
                    raise ValueError("Existing run directory contains another plan.")
                return run_dir
            if caption is not None:
                self._save_caption(run_dir, caption)
            write_json(path, plan)
            self.save_manifest(
                run_dir,
                {
                    "schemaVersion": 1,
                    "planHash": plan_hash,
                    "videoId": video_id,
                    "status": "planned",
                    "stage": "planned",
                    "createdAt": datetime.now(UTC).isoformat(),
                    "completedAt": None,
                    "timelineSha256": None,
                    "error": None,
                },
            )
        return run_dir

    def _save_caption(self, run_dir: Path, caption: YouTubeTranscriptFetchResult) -> None:
        path = run_dir / "inputs" / "transcript.json"
        response = TranscriptResponse(
            videoId=caption.video_id,
            language=caption.language,
            languageCode=caption.language_code,
            isGenerated=caption.is_generated,
            text="\n".join(segment.text for segment in caption.segments),
            segments=[asdict(segment) for segment in caption.segments],
            storage=TranscriptStorageResponse(
                bucket="local", objectName="inputs/transcript.json", uri=path.resolve().as_uri()
            ),
        )
        write_json(path, response.model_dump(mode="json", by_alias=True))
        self.save_cues(run_dir, response)

    def save_cues(self, run_dir: Path, transcript: TranscriptResponse) -> None:
        creates = build_transcript_cues(
            1,
            (
                TranscriptCueSegmentInput(
                    text=segment.text,
                    start_seconds=segment.start,
                    duration_seconds=segment.duration,
                )
                for segment in transcript.segments
            ),
        )
        now = datetime.now(UTC)
        records = [
            TranscriptCueRecord(**asdict(cue), id=index, created_at=now, updated_at=now)
            for index, cue in enumerate(creates, start=1)
        ]
        write_json(run_dir / "inputs" / "cues.json", records)

    def load_plan(self, plan_path: Path) -> dict[str, Any]:
        return read_json(plan_path.resolve())

    def load_manifest(self, run_dir: Path) -> dict[str, Any]:
        return read_json(run_dir / "manifest.json")

    def save_manifest(self, run_dir: Path, manifest: dict[str, object]) -> None:
        write_json(run_dir / "manifest.json", manifest)

    def lock(self, run_dir: Path) -> RunLock:
        return RunLock(run_dir / ".run.lock")

    def transcript_exists(self, run_dir: Path) -> bool:
        return (run_dir / "inputs" / "transcript.json").is_file() and (
            run_dir / "inputs" / "cues.json"
        ).is_file()

    def micro_exists(self, run_dir: Path) -> bool:
        return (run_dir / "micro-events.json").is_file()

    def load_micro(self, run_dir: Path) -> dict[str, object]:
        return read_json(run_dir / "micro-events.json")

    def save_micro(self, run_dir: Path, result: dict[str, object]) -> None:
        write_json(run_dir / "micro-events.json", result)

    def save_timeline(self, run_dir: Path, result: dict[str, object]) -> str:
        path = run_dir / "timeline.json"
        write_json(path, result)
        return file_sha256(path)

    def snapshot_artifact_hashes(self, run_dir: Path) -> dict[str, str]:
        return {
            path.relative_to(run_dir).as_posix(): file_sha256(path)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name not in {".run.lock", "manifest.json"}
        }

    def status(self, run_dir: Path) -> dict[str, object]:
        manifest = self.load_manifest(run_dir)
        return {
            "runDir": str(run_dir.resolve()),
            "videoId": manifest["videoId"],
            "status": manifest["status"],
            "stage": manifest["stage"],
            "completedMicroWindows": len(FileWindowCheckpoints(run_dir).completed()),
            "completedAsrChunks": len(list((run_dir / "checkpoints" / "asr").glob("chunk-*.json"))),
            "timelinePath": (
                str((run_dir / "timeline.json").resolve())
                if (run_dir / "timeline.json").exists()
                else None
            ),
            "error": manifest.get("error"),
        }

    def verify(self, run_dir: Path) -> dict[str, object]:
        manifest = self.load_manifest(run_dir)
        if manifest["status"] != "succeeded":
            raise ValueError("Run is not complete.")
        path = run_dir / "timeline.json"
        if not path.is_file() or file_sha256(path) != manifest.get("timelineSha256"):
            raise ValueError("Timeline file is missing or its digest differs.")
        recorded = manifest.get("artifactSha256")
        if not isinstance(recorded, dict) or recorded != self.snapshot_artifact_hashes(run_dir):
            raise ValueError("A run artifact is missing, changed, or unexpected.")
        timeline = read_json(path)
        if timeline.get("video", {}).get("youtubeVideoId") != manifest["videoId"]:
            raise ValueError("Timeline video identity differs from the plan.")
        micro_items = timeline.get("microEvents", [])
        micro_ids = {item["sourceCandidateId"] for item in micro_items}
        if len(micro_ids) != len(micro_items) or len({item["id"] for item in micro_items}) != len(
            micro_items
        ):
            raise ValueError("Timeline has duplicate micro-event identifiers.")
        _verify_references(timeline, micro_ids)
        return {
            "runDir": str(run_dir.resolve()),
            "videoId": manifest["videoId"],
            "status": "succeeded",
            "timelinePath": str(path.resolve()),
            "timelineSha256": manifest["timelineSha256"],
            "microEventCount": len(micro_ids),
            "episodeCount": len(timeline.get("timeline", {}).get("episodes", [])),
        }


def _verify_references(timeline: dict[str, Any], micro_ids: set[int]) -> None:
    body = timeline.get("timeline", {})
    episodes = body.get("episodes", [])
    episode_ids = {item["episodeId"] for item in episodes}
    block_ids = {item["blockId"] for item in body.get("blocks", [])}
    _verify_episode_references(episodes, block_ids, micro_ids)
    _verify_group_references(body, episode_ids, micro_ids)


def _verify_episode_references(
    episodes: list[dict[str, Any]], block_ids: set[str], micro_ids: set[int]
) -> None:
    for episode in episodes:
        if episode.get("parentBlockId") not in block_ids:
            raise ValueError("Episode references a missing block.")
        if episode.get("startMicroEventCandidateId") not in micro_ids:
            raise ValueError("Episode references a missing starting micro-event.")
        if episode.get("endMicroEventCandidateId") not in micro_ids:
            raise ValueError("Episode references a missing ending micro-event.")
        if not set(episode.get("highlightMicroEventCandidateIds", [])).issubset(micro_ids):
            raise ValueError("Episode highlights reference missing micro-events.")


def _verify_group_references(
    body: dict[str, Any], episode_ids: set[str], micro_ids: set[int]
) -> None:
    for block in body.get("blocks", []):
        if not set(block.get("episodeIds", [])).issubset(episode_ids):
            raise ValueError("Block references a missing episode.")
    for topic in body.get("topicClusters", []):
        if not set(topic.get("episodeIds", [])).issubset(episode_ids):
            raise ValueError("Topic cluster references a missing episode.")
    for flag in body.get("reviewFlags", []):
        for key in ("startMicroEventCandidateId", "endMicroEventCandidateId"):
            reference = flag.get(key)
            if reference is not None and reference not in micro_ids:
                raise ValueError("Review flag references a missing micro-event.")
