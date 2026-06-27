from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from codex_sdk_cli.domains.channels.exceptions import (
    ChannelAlreadyExists,
    ChannelDomainError,
    ChannelNotFound,
    ChannelPersistenceError,
)
from codex_sdk_cli.domains.codex.exceptions import CodexDomainError, CodexRuntimeError
from codex_sdk_cli.domains.domain_knowledge.exceptions import (
    DomainKnowledgeConflict,
    DomainKnowledgeDomainError,
    DomainKnowledgeNotFound,
    DomainKnowledgePersistenceError,
)
from codex_sdk_cli.domains.external_api_calls.exceptions import ExternalApiCallDomainError
from codex_sdk_cli.domains.micro_events.exceptions import (
    MicroEventDomainError,
    MicroEventExtractionNotFound,
    MicroEventExtractionPersistenceError,
    MicroEventExtractionPreconditionFailed,
)
from codex_sdk_cli.domains.operation_events.exceptions import OperationEventDomainError
from codex_sdk_cli.domains.ops.exceptions import OpsDomainError, OpsVideoNotFound
from codex_sdk_cli.domains.pipeline_jobs.exceptions import (
    PipelineJobDomainError,
    PipelineJobNotFound,
    PipelineJobPersistenceError,
    PipelineJobRetryNotAllowed,
)
from codex_sdk_cli.domains.prompts.exceptions import (
    PromptConflict,
    PromptDomainError,
    PromptNotFound,
    PromptPersistenceError,
)
from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerDomainError,
    StreamerHasChannels,
    StreamerNotFound,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.timelines.exceptions import (
    TimelineCompositionNotFound,
    TimelineCompositionPersistenceError,
    TimelineCompositionPreconditionFailed,
    TimelineDomainError,
)
from codex_sdk_cli.domains.transcript_cues.exceptions import (
    TranscriptCueDomainError,
    TranscriptCuePersistenceError,
)
from codex_sdk_cli.domains.video_tasks.exceptions import (
    TranscriptCollectAlreadyRunning,
    VideoTaskDomainError,
    VideoTaskNotFound,
    VideoTaskPersistenceError,
    VideoTaskRetryNotAllowed,
)
from codex_sdk_cli.domains.videos.exceptions import (
    ChannelMissingYouTubeId,
    VideoAlreadyExists,
    VideoDomainError,
    VideoNotFound,
    VideoPersistenceError,
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
        if isinstance(exc, StreamerNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, StreamerHasChannels):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, StreamerPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(ChannelDomainError)
    async def channel_domain_error_handler(
        _request: Request,
        exc: ChannelDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, ChannelNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, ChannelAlreadyExists):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, ChannelPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(DomainKnowledgeDomainError)
    async def domain_knowledge_domain_error_handler(
        _request: Request,
        exc: DomainKnowledgeDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, DomainKnowledgeNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, DomainKnowledgeConflict):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, DomainKnowledgePersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(PromptDomainError)
    async def prompt_domain_error_handler(
        _request: Request,
        exc: PromptDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, PromptNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, PromptConflict):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, PromptPersistenceError):
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

    @app.exception_handler(OpsDomainError)
    async def ops_domain_error_handler(
        _request: Request,
        exc: OpsDomainError,
    ) -> JSONResponse:
        if isinstance(exc, OpsVideoNotFound):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": exc.message},
            )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": exc.message},
        )

    @app.exception_handler(OperationEventDomainError)
    async def operation_event_domain_error_handler(
        _request: Request,
        exc: OperationEventDomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": exc.message},
        )

    @app.exception_handler(VideoDomainError)
    async def video_domain_error_handler(
        _request: Request,
        exc: VideoDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, VideoNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, VideoAlreadyExists):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, VideoPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif isinstance(exc, ChannelMissingYouTubeId):
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(MicroEventDomainError)
    async def micro_event_domain_error_handler(
        _request: Request,
        exc: MicroEventDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, MicroEventExtractionNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, MicroEventExtractionPreconditionFailed):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, MicroEventExtractionPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(TimelineDomainError)
    async def timeline_domain_error_handler(
        _request: Request,
        exc: TimelineDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, TimelineCompositionNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, TimelineCompositionPreconditionFailed):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, TimelineCompositionPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(VideoTaskDomainError)
    async def video_task_domain_error_handler(
        _request: Request,
        exc: VideoTaskDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, VideoTaskNotFound):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, (VideoTaskRetryNotAllowed, TranscriptCollectAlreadyRunning)):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, VideoTaskPersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(TranscriptCueDomainError)
    async def transcript_cue_domain_error_handler(
        _request: Request,
        exc: TranscriptCueDomainError,
    ) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, TranscriptCuePersistenceError):
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

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
