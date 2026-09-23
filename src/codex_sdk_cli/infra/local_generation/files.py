from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from codex_sdk_cli.domains.asr.ports import (
    AudioChunkCheckpoint,
    AudioChunkCheckpointPort,
    AudioTranscriptionSegment,
)
from codex_sdk_cli.domains.codex_usage.ports import CodexUsageCreate, CodexUsageRecorderPort
from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent, LlmTraceRecorderPort
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueCreate, TranscriptCueRecord
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRecord,
    YouTubeTranscriptStorageReadRequest,
    YouTubeTranscriptStorageSaveRequest,
)


def jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    raise TypeError(f"Cannot serialize {type(value).__name__}.")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(jsonable(value), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RunLock:
    """Hold an OS file lock for one local generation directory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: Any = None

    def __enter__(self) -> RunLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self._path.stat().st_size == 0:
                    self._file.write(b"\0")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            self._file = None
            raise RuntimeError("A run is already active in this directory.") from exc
        return self

    def __exit__(self, *_args: object) -> None:
        if self._file is None:
            return
        if os.name == "nt":
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None


class FileTranscriptStorage:
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "inputs" / "transcript.json"
        self._object_name: str | None = None

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        self._object_name = object_name
        return TranscriptStorageLocation(
            bucket="local", object_name=object_name, uri=self._path.resolve().as_uri()
        )

    async def save_transcript(
        self, request: YouTubeTranscriptStorageSaveRequest
    ) -> TranscriptStorageLocation:
        location = self.location_for(request.object_name)
        write_json(self._path, json.loads(request.payload))
        return location

    async def read_transcript(self, request: YouTubeTranscriptStorageReadRequest) -> bytes:
        if self._object_name is not None and request.object_name != self._object_name:
            raise ValueError("Unexpected transcript object name.")
        return self._path.read_bytes()


class FileTranscriptRepository:
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "inputs" / "transcript-metadata.json"

    async def save_transcript_record(
        self, record: YouTubeTranscriptRecord
    ) -> YouTubeTranscriptMetadataRecord:
        now = datetime.now(UTC)
        metadata = YouTubeTranscriptMetadataRecord(
            id=1,
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
            created_at=now,
            updated_at=now,
        )
        write_json(self._path, metadata)
        return metadata


class FileCueRepository:
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "inputs" / "cues.json"

    async def replace_cues(
        self, transcript_id: int, cues: list[TranscriptCueCreate]
    ) -> list[TranscriptCueRecord]:
        now = datetime.now(UTC)
        records = [
            TranscriptCueRecord(**asdict(cue), id=index, created_at=now, updated_at=now)
            for index, cue in enumerate(cues, start=1)
            if cue.transcript_id == transcript_id
        ]
        write_json(self._path, records)
        return records


class FileAsrCheckpoints(AudioChunkCheckpointPort):
    def __init__(self, run_dir: Path) -> None:
        self._directory = run_dir / "checkpoints" / "asr"

    async def load(self, chunk_index: int) -> AudioChunkCheckpoint | None:
        path = self._directory / f"chunk-{chunk_index:05d}.json"
        if not path.is_file():
            return None
        data = read_json(path)
        return AudioChunkCheckpoint(
            chunk_index=int(data["chunk_index"]),
            segments=tuple(AudioTranscriptionSegment(**item) for item in data["segments"]),
            device=str(data["device"]),
            compute_type=str(data["compute_type"]),
        )

    async def save(self, checkpoint: AudioChunkCheckpoint) -> None:
        write_json(self._directory / f"chunk-{checkpoint.chunk_index:05d}.json", checkpoint)


class FileWindowCheckpoints:
    def __init__(self, run_dir: Path) -> None:
        self._directory = run_dir / "checkpoints" / "micro"

    async def write(self, *, window_index: int, payload: dict[str, object], status: str) -> None:
        write_json(
            self._directory / f"window-{window_index:05d}.json",
            {"status": status, "payload": payload},
        )

    def completed(self) -> list[dict[str, Any]]:
        return [
            cast(dict[str, Any], data["payload"])
            for path in sorted(self._directory.glob("window-*.json"))
            if (data := read_json(path)).get("status") == "succeeded"
        ]


class FileUsageRecorder(CodexUsageRecorderPort):
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "usage.jsonl"
        self._lock = asyncio.Lock()

    async def record_usage(self, usage: CodexUsageCreate) -> None:
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(jsonable(usage), ensure_ascii=False) + "\n")


class FileTraceRecorder(LlmTraceRecorderPort):
    def __init__(self, run_dir: Path) -> None:
        self._directory = run_dir / "traces"
        self._lock = asyncio.Lock()
        self._index = len(list(self._directory.glob("*.json")))

    async def record_event(self, event: LlmTraceEvent) -> None:
        async with self._lock:
            self._index += 1
            write_json(self._directory / f"{self._index:06d}.json", event)
