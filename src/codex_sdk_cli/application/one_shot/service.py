from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptNotFound
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptFetchResult
from codex_sdk_cli.domains.youtube_transcripts.use_cases import normalize_video_id

from .ports import (
    ActivePromptSourcePort,
    LocalAsrPort,
    LocalGenerationPort,
    OneShotStorePort,
    RunOptions,
    TranscriptLookupPort,
    VideoLookupPort,
    VideoMetadata,
)


class OneShotError(Exception):
    def __init__(self, code: str, message: str, *, exit_code: int = 4) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(message)


class OneShotTimelineService:
    def __init__(
        self,
        *,
        videos: VideoLookupPort,
        captions: TranscriptLookupPort,
        prompts: ActivePromptSourcePort,
        asr: LocalAsrPort,
        generation: LocalGenerationPort,
        store: OneShotStorePort,
    ) -> None:
        self._videos = videos
        self._captions = captions
        self._prompts = prompts
        self._asr = asr
        self._generation = generation
        self._store = store

    async def plan(
        self, *, video_id: str, output_root: Path, options: RunOptions
    ) -> dict[str, object]:
        video_id = normalize_video_id(video_id)
        _validate_options(options)
        video = await self._videos.lookup(video_id)
        caption: YouTubeTranscriptFetchResult | None = None
        if options.transcript_mode != "asr":
            try:
                caption = await self._captions.fetch(video_id, options.languages)
                if not caption.segments:
                    raise YouTubeTranscriptNotFound("YouTube transcript has no segments.")
            except YouTubeTranscriptNotFound:
                if options.transcript_mode == "youtube":
                    raise OneShotError(
                        "NO_TRANSCRIPT", "No YouTube transcript is available."
                    ) from None
        prompt_records = await self._prompts.resolve()
        transcript_source = "youtube" if caption is not None else "asr"
        segment_count = len(caption.segments) if caption is not None else None
        last_end = (
            max((segment.start + segment.duration for segment in caption.segments), default=0)
            if caption is not None
            else video.duration_seconds
        )
        window_count = max(1, math.ceil(last_end / (options.window_minutes * 60)))
        plan: dict[str, object] = {
            "schemaVersion": 1,
            "video": _video_json(video),
            "options": asdict(options),
            "transcriptSource": transcript_source,
            "captionSha256": _caption_hash(caption) if caption is not None else None,
            "prompts": {key: _prompt_json(prompt) for key, prompt in prompt_records.items()},
            "estimatedMicroWindows": window_count,
            "estimatedAsrChunks": (
                max(1, -(-video.duration_seconds // (options.asr_chunk_minutes * 60)))
                if transcript_source == "asr"
                else 0
            ),
        }
        plan_hash = _digest(plan)
        run_dir = self._store.create_plan(
            output_root=output_root,
            video_id=video_id,
            plan_hash=plan_hash,
            plan={**plan, "planHash": plan_hash},
            caption=caption,
        )
        return {
            "planPath": str((run_dir / "plan.json").resolve()),
            "runDir": str(run_dir.resolve()),
            "planHash": plan_hash,
            "videoId": video_id,
            "transcriptSource": transcript_source,
            "captionSegments": segment_count,
            "estimatedMicroWindows": window_count,
            "estimatedAsrChunks": plan["estimatedAsrChunks"],
            "prompts": {
                key: {"versionId": prompt.version_id, "sha256": prompt.body_sha256}
                for key, prompt in prompt_records.items()
            },
        }

    async def run(self, *, plan_path: Path, confirm_plan_hash: str) -> dict[str, object]:
        plan = self._store.load_plan(plan_path)
        _validate_plan(plan, confirm_plan_hash)
        if self._store.load_manifest(plan_path.parent)["status"] == "succeeded":
            return self._store.verify(plan_path.parent)
        current = await self._prompts.resolve()
        for key, saved in plan["prompts"].items():
            active = current[key]
            if active.version_id != saved["versionId"] or active.body_sha256 != saved["bodySha256"]:
                raise OneShotError("PROMPT_CHANGED", "An active prompt changed. Create a new plan.")
        return await self._execute(plan_path.parent, plan, resume=False)

    async def resume(self, *, run_dir: Path) -> dict[str, object]:
        plan = self._store.load_plan(run_dir / "plan.json")
        _validate_plan(plan, str(plan["planHash"]))
        return await self._execute(run_dir, plan, resume=True)

    def status(self, *, run_dir: Path) -> dict[str, object]:
        return self._store.status(run_dir)

    def verify(self, *, run_dir: Path) -> dict[str, object]:
        return self._store.verify(run_dir)

    async def _execute(
        self, run_dir: Path, plan: dict[str, Any], *, resume: bool
    ) -> dict[str, object]:
        with self._store.lock(run_dir):
            manifest = self._store.load_manifest(run_dir)
            if manifest["status"] == "succeeded":
                return self._store.verify(run_dir)
            if resume and manifest["status"] == "planned":
                raise OneShotError("RUN_NOT_STARTED", "Use run to start this plan.")
            if not resume and manifest["status"] != "planned":
                raise OneShotError("RESUME_REQUIRED", "Use resume for an interrupted run.")
            manifest.update(status="running", stage="transcript", error=None)
            self._store.save_manifest(run_dir, manifest)
            try:
                if plan["transcriptSource"] == "asr" and not self._store.transcript_exists(run_dir):
                    await self._asr.transcribe(
                        youtube_video_id=str(plan["video"]["youtubeVideoId"]),
                        run_dir=run_dir,
                        options=RunOptions(**plan["options"]),
                    )
                manifest.update(stage="micro")
                self._store.save_manifest(run_dir, manifest)
                if self._store.micro_exists(run_dir):
                    micro = self._store.load_micro(run_dir)
                else:
                    micro = await self._generation.generate_micro(run_dir=run_dir, resume=resume)
                    self._store.save_micro(run_dir, micro)
                manifest.update(stage="timeline")
                self._store.save_manifest(run_dir, manifest)
                timeline = await self._generation.generate_timeline(run_dir=run_dir, micro=micro)
                timeline_sha256 = self._store.save_timeline(run_dir, timeline)
                manifest.update(
                    status="succeeded",
                    stage="complete",
                    completedAt=_now(),
                    timelineSha256=timeline_sha256,
                    artifactSha256=self._store.snapshot_artifact_hashes(run_dir),
                )
                self._store.save_manifest(run_dir, manifest)
                return self._store.verify(run_dir)
            except Exception as exc:
                manifest.update(status="failed", error={"type": type(exc).__name__})
                self._store.save_manifest(run_dir, manifest)
                raise


def _validate_options(options: RunOptions) -> None:
    if options.transcript_mode not in {"auto", "youtube", "asr"}:
        raise OneShotError("INVALID_OPTIONS", "Invalid transcript mode.", exit_code=2)
    if (
        not options.languages
        or options.window_minutes < 1
        or not 0 <= options.overlap_minutes < options.window_minutes
    ):
        raise OneShotError("INVALID_OPTIONS", "Invalid languages or window settings.", exit_code=2)
    if options.asr_chunk_minutes < 1 or options.micro_window_concurrency < 1:
        raise OneShotError("INVALID_OPTIONS", "Invalid ASR or concurrency settings.", exit_code=2)
    if options.asr_device not in {"cuda", "cpu"}:
        raise OneShotError("INVALID_OPTIONS", "Select CUDA or CPU for ASR.", exit_code=2)


def _validate_plan(plan: dict[str, Any], confirmed_hash: str) -> None:
    expected = plan.get("planHash")
    if (
        not isinstance(expected, str)
        or _digest({k: v for k, v in plan.items() if k != "planHash"}) != expected
    ):
        raise OneShotError("PLAN_TAMPERED", "Plan content does not match its hash.")
    if confirmed_hash != expected:
        raise OneShotError("PLAN_HASH_MISMATCH", "Confirmation hash does not match the plan.")


def _caption_hash(caption: YouTubeTranscriptFetchResult) -> str:
    return _digest(
        {
            "language": caption.language,
            "languageCode": caption.language_code,
            "isGenerated": caption.is_generated,
            "segments": [asdict(segment) for segment in caption.segments],
        }
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _video_json(video: VideoMetadata) -> dict[str, object]:
    data = asdict(video)
    return {
        "youtubeVideoId": data["youtube_video_id"],
        "title": data["title"],
        "description": data["description"],
        "publishedAt": data["published_at"].isoformat(),
        "duration": data["duration"],
        "durationSeconds": data["duration_seconds"],
        "thumbnailUrl": data["thumbnail_url"],
        "channelId": data["channel_id"],
        "channelName": data["channel_name"],
        "isEmbeddable": data["is_embeddable"],
    }


def _prompt_json(prompt: ResolvedPrompt) -> dict[str, object]:
    return {
        "key": prompt.key,
        "versionId": prompt.version_id,
        "versionLabel": prompt.version_label,
        "body": prompt.body,
        "bodySha256": prompt.body_sha256,
        "source": prompt.source,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
