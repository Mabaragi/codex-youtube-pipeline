from __future__ import annotations

import re

from fastapi import status

from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishArtifactInvalid,
    ArchivePublishConfigurationError,
    ArchivePublishDomainError,
    ArchivePublishPersistenceError,
    ArchivePublishPreconditionFailed,
    ArchivePublishStorageError,
)
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
from codex_sdk_cli.domains.publication.exceptions import (
    PublicationCatalogPublishError,
    PublicationConnectionConfigurationError,
    PublicationConnectionNotFoundError,
    PublicationError,
    PublicationObjectStoreError,
)
from codex_sdk_cli.domains.publication_config.exceptions import (
    PublishConfigurationConflict,
    PublishConfigurationDomainError,
    PublishConfigurationNotFound,
    PublishConfigurationPersistenceError,
)
from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerDomainError,
    StreamerHasChannels,
    StreamerNotFound,
    StreamerPersistenceError,
    StreamerPublishProfileCutoverRequired,
    StreamerPublishProfileUnavailable,
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
    VideoTaskCancelNotAllowed,
    VideoTaskDomainError,
    VideoTaskNotFound,
    VideoTaskPersistenceError,
    VideoTaskRetryNotAllowed,
)
from codex_sdk_cli.domains.videos.exceptions import (
    VideoAlreadyExists,
    VideoDomainError,
    VideoNotFound,
    VideoPersistenceError,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataConfigurationError,
    YouTubeDataDomainError,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptDomainError,
    YouTubeTranscriptForbidden,
    YouTubeTranscriptMetadataNotFound,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptPersistenceError,
    YouTubeTranscriptStorageError,
    YouTubeTranscriptUpstreamError,
)

DOMAIN_ERROR_TYPES: tuple[type[Exception], ...] = (
    ArchivePublishDomainError,
    ChannelDomainError,
    CodexDomainError,
    DomainKnowledgeDomainError,
    ExternalApiCallDomainError,
    MicroEventDomainError,
    OperationEventDomainError,
    OpsDomainError,
    PipelineJobDomainError,
    PromptDomainError,
    PublicationError,
    PublishConfigurationDomainError,
    StreamerDomainError,
    TimelineDomainError,
    TranscriptCueDomainError,
    VideoTaskDomainError,
    VideoDomainError,
    YouTubeDataDomainError,
    YouTubeTranscriptDomainError,
)

_NOT_FOUND_ERRORS = (
    ChannelNotFound,
    DomainKnowledgeNotFound,
    MicroEventExtractionNotFound,
    OpsVideoNotFound,
    PipelineJobNotFound,
    PromptNotFound,
    PublicationConnectionNotFoundError,
    PublishConfigurationNotFound,
    StreamerNotFound,
    StreamerPublishProfileUnavailable,
    TimelineCompositionNotFound,
    VideoTaskNotFound,
    VideoNotFound,
    YouTubeDataChannelNotFound,
    YouTubeTranscriptMetadataNotFound,
    YouTubeTranscriptNotFound,
)
_CONFLICT_ERRORS = (
    ArchivePublishArtifactInvalid,
    ArchivePublishPreconditionFailed,
    ChannelAlreadyExists,
    DomainKnowledgeConflict,
    MicroEventExtractionPreconditionFailed,
    PipelineJobRetryNotAllowed,
    PromptConflict,
    PublishConfigurationConflict,
    StreamerHasChannels,
    StreamerPublishProfileCutoverRequired,
    TimelineCompositionPreconditionFailed,
    TranscriptCollectAlreadyRunning,
    VideoAlreadyExists,
    VideoTaskCancelNotAllowed,
    VideoTaskRetryNotAllowed,
)
_UNAVAILABLE_ERRORS = (
    ArchivePublishConfigurationError,
    ArchivePublishPersistenceError,
    ArchivePublishStorageError,
    ChannelPersistenceError,
    DomainKnowledgePersistenceError,
    ExternalApiCallDomainError,
    MicroEventExtractionPersistenceError,
    OperationEventDomainError,
    PipelineJobPersistenceError,
    PromptPersistenceError,
    PublicationConnectionConfigurationError,
    PublicationObjectStoreError,
    PublishConfigurationPersistenceError,
    StreamerPersistenceError,
    TimelineCompositionPersistenceError,
    TranscriptCuePersistenceError,
    VideoPersistenceError,
    VideoTaskPersistenceError,
    YouTubeDataConfigurationError,
    YouTubeTranscriptPersistenceError,
    YouTubeTranscriptStorageError,
)
_UPSTREAM_ERRORS = (
    CodexRuntimeError,
    PublicationCatalogPublishError,
    YouTubeDataUpstreamError,
    YouTubeTranscriptUpstreamError,
)


def domain_error_status(exc: Exception) -> int:
    if isinstance(exc, _NOT_FOUND_ERRORS):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, YouTubeTranscriptForbidden):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, _CONFLICT_ERRORS):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, _UPSTREAM_ERRORS):
        return status.HTTP_502_BAD_GATEWAY
    if isinstance(exc, _UNAVAILABLE_ERRORS):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, OpsDomainError):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_400_BAD_REQUEST


def domain_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.replace("YouTube", "Youtube")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def domain_error_message(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    return message if isinstance(message, str) and message else str(exc)
