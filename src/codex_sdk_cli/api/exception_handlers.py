from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from codex_sdk_cli.domains.codex.exceptions import CodexDomainError, CodexRuntimeError
from codex_sdk_cli.domains.external_api_calls.exceptions import ExternalApiCallDomainError
from codex_sdk_cli.domains.pipeline_jobs.exceptions import (
    PipelineJobDomainError,
    PipelineJobNotFound,
    PipelineJobPersistenceError,
    PipelineJobRetryNotAllowed,
)
from codex_sdk_cli.domains.streamers.exceptions import (
    ChannelNotFound,
    StreamerDomainError,
    StreamerHasChannels,
    StreamerNotFound,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    InvalidYouTubeChannelHandle,
    YouTubeDataChannelNotFound,
    YouTubeDataConfigurationError,
    YouTubeDataDomainError,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    InvalidYouTubeVideo,
    YouTubeTranscriptDomainError,
    YouTubeTranscriptForbidden,
    YouTubeTranscriptMetadataNotFound,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptPersistenceError,
    YouTubeTranscriptStorageError,
    YouTubeTranscriptUpstreamError,
)


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CodexDomainError)
    async def codex_domain_error_handler(
        _request: Request,
        exc: CodexDomainError,
    ) -> JSONResponse:
        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(exc, CodexRuntimeError)
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(StreamerDomainError)
    async def streamer_domain_error_handler(
        _request: Request,
        exc: StreamerDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, (StreamerNotFound, ChannelNotFound)):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, StreamerHasChannels):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, StreamerPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(ExternalApiCallDomainError)
    async def external_api_call_domain_error_handler(
        _request: Request,
        exc: ExternalApiCallDomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": exc.message},
        )

    @app.exception_handler(PipelineJobDomainError)
    async def pipeline_job_domain_error_handler(
        _request: Request,
        exc: PipelineJobDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, PipelineJobNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, PipelineJobRetryNotAllowed):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, PipelineJobPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(YouTubeDataDomainError)
    async def youtube_data_domain_error_handler(
        _request: Request,
        exc: YouTubeDataDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, YouTubeDataChannelNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, YouTubeDataConfigurationError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif isinstance(exc, YouTubeDataUpstreamError):
            status_code = status.HTTP_502_BAD_GATEWAY
        elif isinstance(exc, InvalidYouTubeChannelHandle):
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(YouTubeTranscriptDomainError)
    async def youtube_domain_error_handler(
        _request: Request,
        exc: YouTubeTranscriptDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, (YouTubeTranscriptNotFound, YouTubeTranscriptMetadataNotFound)):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, YouTubeTranscriptForbidden):
            status_code = status.HTTP_403_FORBIDDEN
        elif isinstance(exc, YouTubeTranscriptUpstreamError):
            status_code = status.HTTP_502_BAD_GATEWAY
        elif isinstance(
            exc,
            (YouTubeTranscriptStorageError, YouTubeTranscriptPersistenceError),
        ):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif isinstance(exc, InvalidYouTubeVideo):
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(ValidationError)
    async def pydantic_validation_error_handler(
        _request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.errors(include_url=False)},
        )
