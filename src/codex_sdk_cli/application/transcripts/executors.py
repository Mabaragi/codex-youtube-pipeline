from __future__ import annotations

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)

from .ports import TranscriptCueGeneratorPort, TranscriptFetcherPort


class TranscriptCollectExecutor(WorkExecutorPort):
    def __init__(self, fetcher: TranscriptFetcherPort) -> None:
        self._fetcher = fetcher

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        input_json = context.work_item.input_json
        video_id = _required_int(input_json, "videoId")
        youtube_video_id = _required_str(input_json, "youtubeVideoId")
        languages = _required_str_tuple(input_json, "languages")
        preserve_formatting = _required_bool(input_json, "preserveFormatting")
        stored = await self._fetcher.fetch(
            youtube_video_id=youtube_video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
        )
        if stored is None:
            return WorkExecutionResult(
                output_json={
                    "videoId": video_id,
                    "youtubeVideoId": youtube_video_id,
                    "reason": "no_transcript",
                },
                outcome_code="no_transcript",
            )
        return WorkExecutionResult(
            output_json={
                "videoId": video_id,
                "youtubeVideoId": youtube_video_id,
                "transcriptId": stored.transcript_id,
                "languageCode": stored.language_code,
                "responseSha256": stored.response_sha256,
                "reusedExisting": stored.reused_existing,
            },
            output_transcript_id=stored.transcript_id,
            cooldown_seconds_override=0 if stored.reused_existing else None,
        )


class TranscriptCueGenerateExecutor(WorkExecutorPort):
    def __init__(self, generator: TranscriptCueGeneratorPort) -> None:
        self._generator = generator

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        transcript_id = _required_int(context.work_item.input_json, "transcriptId")
        generated = await self._generator.generate(
            transcript_id=transcript_id,
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
        )
        return WorkExecutionResult(
            output_json={
                "transcriptId": generated.transcript_id,
                "cueCount": generated.cue_count,
                "firstCueId": generated.first_cue_id,
                "lastCueId": generated.last_cue_id,
            },
            output_transcript_id=generated.transcript_id,
        )


def _required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer.")


def _required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"{key} must be a non-empty string.")


def _required_bool(values: dict[str, object], key: str) -> bool:
    value = values.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be a boolean.")


def _required_str_tuple(values: dict[str, object], key: str) -> tuple[str, ...]:
    value = values.get(key)
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise ValueError(f"{key} must be a non-empty string list.")
