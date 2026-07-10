from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from codex_sdk_cli.cli import main
from codex_sdk_cli.domains.asr.exceptions import AudioTranscriptionOutputInvalid
from codex_sdk_cli.domains.asr.ports import (
    AudioChunkerPort,
    AudioTranscriberPort,
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    AudioTranscriptionSegment,
    YouTubeAudioDownloaderPort,
)
from codex_sdk_cli.domains.asr.use_cases import (
    FasterWhisperTranscribeRequest,
    FasterWhisperTranscribeResult,
    TranscribeYouTubeAudioUseCase,
)
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueCreate,
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
    TranscriptCueSummaryRecord,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
    YouTubeTranscriptStorageSaveRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptResponse,
    TranscriptSegmentResponse,
    TranscriptStorageResponse,
)

VIDEO_ID = "dQw4w9WgXcQ"
NOW = datetime(2026, 7, 1, tzinfo=UTC)


def test_faster_whisper_use_case_stores_transcript_and_cues() -> None:
    fakes = _Fakes(duration_seconds=100.0)
    fakes.transcriber.responses = [
        AudioTranscriptionResult(
            segments=(
                AudioTranscriptionSegment("첫 구간", 0.5, 2.0),
                AudioTranscriptionSegment("경계 전", 59.0, 60.0),
            ),
            device="cpu",
            compute_type="int8",
        ),
        AudioTranscriptionResult(
            segments=(
                AudioTranscriptionSegment("겹침 제거", 1.0, 2.0),
                AudioTranscriptionSegment("두 번째 구간", 4.0, 6.0),
            ),
            device="cpu",
            compute_type="int8",
        ),
    ]

    result = asyncio.run(
        fakes.use_case.execute(
            FasterWhisperTranscribeRequest(
                video=f"https://www.youtube.com/watch?v={VIDEO_ID}",
                model_size="small",
                language="ko",
                device="cpu",
                compute_type="int8",
                chunk_minutes=1,
                overlap_seconds=3,
            )
        )
    )

    assert result.youtube_video_id == VIDEO_ID
    assert result.transcript_id == 1
    assert result.segment_count == 3
    assert result.cue_count == 3
    assert result.device == "cpu"
    assert result.compute_type == "int8"
    assert result.storage_object_name.startswith(
        "youtube/transcripts/asr/faster-whisper/small/2026/07/01/"
    )
    assert fakes.downloader.temp_dir is not None
    assert not fakes.downloader.temp_dir.exists()
    assert fakes.chunker.created_chunks == [(0.0, 63.0), (57.0, 43.0)]
    assert [segment.text for segment in result.transcript.segments] == [
        "첫 구간",
        "경계 전",
        "두 번째 구간",
    ]
    assert [segment.start for segment in result.transcript.segments] == [0.5, 59.0, 61.0]
    assert fakes.repository.records[0].requested_languages == (
        "ko",
        "asr:faster-whisper-small",
    )
    assert [cue.cue_id for cue in fakes.cues.records] == [
        "tr1-c000001",
        "tr1-c000002",
        "tr1-c000003",
    ]
    assert [cue.source_job_id for cue in fakes.cues.records] == [None, None, None]
    stored_payload = json.loads(fakes.storage.saves[0].payload.decode("utf-8"))
    assert TranscriptResponse.model_validate(stored_payload).video_id == VIDEO_ID


def test_faster_whisper_use_case_rejects_empty_output_and_removes_temp() -> None:
    fakes = _Fakes(duration_seconds=10.0)
    fakes.transcriber.responses = [
        AudioTranscriptionResult(
            segments=(AudioTranscriptionSegment("   ", 0.0, 1.0),),
            device="cpu",
            compute_type="int8",
        )
    ]

    with pytest.raises(AudioTranscriptionOutputInvalid):
        asyncio.run(
            fakes.use_case.execute(
                FasterWhisperTranscribeRequest(
                    video=VIDEO_ID,
                    chunk_minutes=1,
                    device="cpu",
                    compute_type="int8",
                )
            )
        )

    assert fakes.downloader.temp_dir is not None
    assert not fakes.downloader.temp_dir.exists()
    assert fakes.storage.saves == []
    assert fakes.cues.records == []


def test_asr_transcribe_cli_outputs_summary_and_optional_transcript_file(
    tmp_path: Path,
) -> None:
    transcript = _transcript_response()
    captured_requests: list[FasterWhisperTranscribeRequest] = []

    async def fake_runner(
        request: FasterWhisperTranscribeRequest,
    ) -> FasterWhisperTranscribeResult:
        captured_requests.append(request)
        return FasterWhisperTranscribeResult(
            youtube_video_id=VIDEO_ID,
            transcript_id=7,
            segment_count=1,
            cue_count=1,
            storage_object_name="youtube/transcripts/asr/object.json",
            model_size=request.model_size,
            device="cpu",
            compute_type="int8",
            duration_seconds=10.0,
            elapsed_seconds=1.25,
            transcript=transcript,
        )

    output_path = tmp_path / "transcript.json"
    result = CliRunner().invoke(
        main,
        [
            "asr",
            "transcribe",
            "--device",
            "cpu",
            "--compute-type",
            "int8",
            "--chunk-minutes",
            "5",
            "--output",
            str(output_path),
            VIDEO_ID,
        ],
        obj={"asr_transcribe_runner": fake_runner},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["youtubeVideoId"] == VIDEO_ID
    assert payload["transcriptId"] == 7
    assert payload["modelSize"] == "turbo"
    assert payload["device"] == "cpu"
    assert captured_requests == [
        FasterWhisperTranscribeRequest(
            video=VIDEO_ID,
            model_size="turbo",
            language="ko",
            device="cpu",
            compute_type="int8",
            chunk_minutes=5,
            overlap_seconds=3,
            beam_size=5,
            vad_filter=True,
            keep_temp=False,
        )
    ]
    assert json.loads(output_path.read_text(encoding="utf-8"))["videoId"] == VIDEO_ID


class FakeDownloader(YouTubeAudioDownloaderPort):
    def __init__(self) -> None:
        self.temp_dir: Path | None = None

    async def download_audio(self, *, video_id: str, output_dir: Path) -> Path:
        self.temp_dir = output_dir
        audio_path = output_dir / f"{video_id}.webm"
        audio_path.write_bytes(b"audio")
        return audio_path


class FakeChunker(AudioChunkerPort):
    def __init__(self, duration_seconds: float) -> None:
        self.duration_seconds = duration_seconds
        self.created_chunks: list[tuple[float, float]] = []

    async def probe_duration_seconds(self, audio_path: Path) -> float:
        return self.duration_seconds

    async def create_chunk(
        self,
        *,
        audio_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> Path:
        self.created_chunks.append((start_seconds, duration_seconds))
        del audio_path
        output_path.write_bytes(b"chunk")
        return output_path


class FakeTranscriber(AudioTranscriberPort):
    def __init__(self) -> None:
        self.requests: list[AudioTranscriptionRequest] = []
        self.responses: list[AudioTranscriptionResult] = []

    async def transcribe(
        self,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return AudioTranscriptionResult(segments=(), device="cpu", compute_type="int8")


class FakeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self) -> None:
        self.saves: list[YouTubeTranscriptStorageSaveRequest] = []

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        return TranscriptStorageLocation(
            bucket="raw",
            object_name=object_name,
            uri=f"s3://raw/{object_name}",
        )

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        self.saves.append(request)
        return self.location_for(request.object_name)

    async def read_transcript(
        self,
        request: YouTubeTranscriptStorageReadRequest,
    ) -> bytes:
        raise NotImplementedError


class FakeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.records: list[YouTubeTranscriptRecord] = []

    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
        self.records.append(record)
        return YouTubeTranscriptMetadataRecord(
            id=len(self.records),
            video_id=record.video_id,
            language=record.language,
            language_code=record.language_code,
            is_generated=record.is_generated,
            requested_languages=record.requested_languages,
            preserve_formatting=record.preserve_formatting,
            storage_bucket=record.storage_bucket,
            storage_object_name=record.storage_object_name,
            storage_uri=record.storage_uri,
            response_sha256=record.response_sha256,
            segment_count=record.segment_count,
            text_length=record.text_length,
            notes=None,
            created_at=NOW,
            updated_at=NOW,
        )

    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        return []

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        return False


class FakeCueRepository(TranscriptCueRepositoryPort):
    def __init__(self) -> None:
        self.records: list[TranscriptCueRecord] = []

    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        self.records = [
            TranscriptCueRecord(
                id=index,
                transcript_id=transcript_id,
                cue_id=cue.cue_id,
                cue_index=cue.cue_index,
                text=cue.text,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                duration_ms=cue.duration_ms,
                source_segment_index=cue.source_segment_index,
                source_job_id=cue.source_job_id,
                source_job_attempt_id=cue.source_job_attempt_id,
                created_at=NOW,
                updated_at=NOW,
            )
            for index, cue in enumerate(cues, start=1)
        ]
        return self.records

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        return [record for record in self.records if record.transcript_id == transcript_id]

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = await self.list_cues(transcript_id)
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=None,
        )


@dataclass(slots=True)
class _Fakes:
    downloader: FakeDownloader
    chunker: FakeChunker
    transcriber: FakeTranscriber
    storage: FakeTranscriptStorage
    repository: FakeTranscriptRepository
    cues: FakeCueRepository
    use_case: TranscribeYouTubeAudioUseCase

    def __init__(self, *, duration_seconds: float) -> None:
        self.downloader = FakeDownloader()
        self.chunker = FakeChunker(duration_seconds)
        self.transcriber = FakeTranscriber()
        self.storage = FakeTranscriptStorage()
        self.repository = FakeTranscriptRepository()
        self.cues = FakeCueRepository()
        self.use_case = TranscribeYouTubeAudioUseCase(
            downloader=self.downloader,
            chunker=self.chunker,
            transcriber=self.transcriber,
            storage=self.storage,
            transcripts=self.repository,
            cues=self.cues,
            storage_prefix="youtube/transcripts",
            date_provider=lambda: date(2026, 7, 1),
            monotonic=_fake_monotonic(),
        )


def _transcript_response() -> TranscriptResponse:
    return TranscriptResponse(
        videoId=VIDEO_ID,
        language="Korean",
        languageCode="ko",
        isGenerated=True,
        text="hello",
        segments=[TranscriptSegmentResponse(text="hello", start=0.0, duration=1.0)],
        storage=TranscriptStorageResponse(
            bucket="raw",
            objectName="youtube/transcripts/asr/object.json",
            uri="s3://raw/youtube/transcripts/asr/object.json",
        ),
    )


def _fake_monotonic():
    values = iter([10.0, 12.5])

    def monotonic() -> float:
        return next(values)

    return monotonic
