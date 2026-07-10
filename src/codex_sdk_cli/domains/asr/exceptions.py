from __future__ import annotations


class AudioTranscriptionError(Exception):
    """Base error for audio transcription experiments."""


class AudioToolNotConfigured(AudioTranscriptionError):
    """Required local audio tool is missing."""


class AudioDownloadFailed(AudioTranscriptionError):
    """Audio download failed."""


class AudioProbeFailed(AudioTranscriptionError):
    """Audio duration probing failed."""


class AudioChunkFailed(AudioTranscriptionError):
    """Audio chunk creation failed."""


class AudioTranscriptionFailed(AudioTranscriptionError):
    """ASR model execution failed."""


class AudioTranscriptionOutputInvalid(AudioTranscriptionError):
    """ASR output could not be stored as a useful transcript."""
