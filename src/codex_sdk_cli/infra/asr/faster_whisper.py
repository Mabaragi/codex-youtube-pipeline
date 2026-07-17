from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool
from typing_extensions import override

from codex_sdk_cli.domains.asr.exceptions import (
    AudioToolNotConfigured,
    AudioTranscriptionFailed,
)
from codex_sdk_cli.domains.asr.ports import (
    AudioTranscriberPort,
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    AudioTranscriptionSegment,
)


class FasterWhisperTranscriber(AudioTranscriberPort):
    def __init__(self) -> None:
        self._models: dict[tuple[str, str, str], Any] = {}
        self._resolved_device: str | None = None
        self._resolved_compute_type: str | None = None

    @override
    async def transcribe(
        self,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        return await run_in_threadpool(self._transcribe_sync, request)

    def _transcribe_sync(
        self,
        request: AudioTranscriptionRequest,
    ) -> AudioTranscriptionResult:
        errors: list[str] = []
        for device, compute_type in _candidate_configurations(
            request.device, request.compute_type
        ):
            try:
                return self._transcribe_with_device(
                    request,
                    device=device,
                    compute_type=compute_type,
                )
            except AudioToolNotConfigured:
                raise
            except Exception as exc:  # noqa: BLE001 - fallback needs third-party failures.
                errors.append(f"{device}/{compute_type}: {exc}")
        raise AudioTranscriptionFailed("faster-whisper transcription failed. " + " | ".join(errors))

    def _transcribe_with_device(
        self,
        request: AudioTranscriptionRequest,
        *,
        device: str,
        compute_type: str,
    ) -> AudioTranscriptionResult:
        model = self._model(request.model_size, device, compute_type)
        segments_iter, _info = model.transcribe(
            str(Path(request.audio_path)),
            language=request.language,
            beam_size=request.beam_size,
            vad_filter=request.vad_filter,
        )
        segments = tuple(
            AudioTranscriptionSegment(
                text=str(segment.text),
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
            )
            for segment in segments_iter
        )
        self._resolved_device = device
        self._resolved_compute_type = compute_type
        return AudioTranscriptionResult(
            segments=segments,
            device=device,
            compute_type=compute_type,
        )

    def _model(self, model_size: str, device: str, compute_type: str) -> Any:
        key = (model_size, device, compute_type)
        if key not in self._models:
            try:
                module = importlib.import_module("faster_whisper")
            except ImportError as exc:
                raise AudioToolNotConfigured(
                    "Python package faster-whisper is not installed."
                ) from exc
            whisper_model = module.WhisperModel
            self._models[key] = whisper_model(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        return self._models[key]


def _candidate_configurations(device: str, compute_type: str) -> tuple[tuple[str, str], ...]:
    if compute_type != "auto":
        devices = ("cuda", "cpu") if device == "auto" else (device,)
        return tuple((candidate, compute_type) for candidate in devices)
    if device == "cuda":
        return (("cuda", "float16"), ("cuda", "int8_float16"))
    if device == "cpu":
        return (("cpu", "int8"),)
    return (("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8"))
