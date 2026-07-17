from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.transcripts.errors import TranscriptPersistenceUnavailable
from codex_sdk_cli.application.transcripts.ports import (
    GeneratedCues,
    StoredTranscript,
    TranscriptCueGeneratorPort,
    TranscriptFetcherPort,
    TranscriptMetadataReaderPort,
)
from codex_sdk_cli.domains.transcript_cues.generation import (
    TranscriptCueSegmentInput,
    build_transcript_cues,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptMetadataNotFound,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptPersistenceError,
    YouTubeTranscriptStorageError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptRequest, TranscriptResponse
from codex_sdk_cli.domains.youtube_transcripts.use_cases import FetchYouTubeTranscriptUseCase
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)


class StoredYouTubeTranscriptFetcher(TranscriptFetcherPort):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client: YouTubeTranscriptPort,
        storage: YouTubeTranscriptStoragePort,
        storage_prefix: str,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._storage = storage
        self._storage_prefix = storage_prefix

    @override
    async def fetch(
        self,
        *,
        youtube_video_id: str,
        languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> StoredTranscript | None:
        try:
            async with self._session_factory() as session:
                repository = SqlAlchemyYouTubeTranscriptRepository(session)
                existing = await repository.find_transcript_metadata_for_request(
                    video_id=youtube_video_id,
                    requested_languages=languages,
                    preserve_formatting=preserve_formatting,
                )
                if existing is not None:
                    return _stored(existing, reused_existing=True)
                fetcher = FetchYouTubeTranscriptUseCase(
                    self._client,
                    self._storage,
                    repository,
                    storage_prefix=self._storage_prefix,
                )
                try:
                    result = await fetcher.execute_with_metadata(
                        TranscriptRequest(
                            video=youtube_video_id,
                            languages=list(languages),
                            preserveFormatting=preserve_formatting,
                        )
                    )
                except YouTubeTranscriptNotFound:
                    return None
                metadata = await repository.get_transcript_metadata(result.metadata.id)
                if metadata is None:
                    raise YouTubeTranscriptMetadataNotFound(
                        "Stored transcript metadata was not found."
                    )
        except YouTubeTranscriptPersistenceError as exc:
            raise TranscriptPersistenceUnavailable() from exc
        return _stored(metadata)


class YouTubeTranscriptMetadataReader(TranscriptMetadataReaderPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def get(self, transcript_id: int) -> StoredTranscript | None:
        try:
            async with self._session_factory() as session:
                metadata = await SqlAlchemyYouTubeTranscriptRepository(
                    session
                ).get_transcript_metadata(transcript_id)
        except YouTubeTranscriptPersistenceError as exc:
            raise TranscriptPersistenceUnavailable() from exc
        return _stored(metadata) if metadata is not None else None

    @override
    async def find_for_request(
        self,
        *,
        youtube_video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> StoredTranscript | None:
        try:
            async with self._session_factory() as session:
                metadata = await SqlAlchemyYouTubeTranscriptRepository(
                    session
                ).find_transcript_metadata_for_request(
                    video_id=youtube_video_id,
                    requested_languages=requested_languages,
                    preserve_formatting=preserve_formatting,
                )
        except YouTubeTranscriptPersistenceError as exc:
            raise TranscriptPersistenceUnavailable() from exc
        return _stored(metadata) if metadata is not None else None


class StoredTranscriptCueGenerator(TranscriptCueGeneratorPort):
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: YouTubeTranscriptStoragePort,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    @override
    async def generate(
        self,
        *,
        transcript_id: int,
        work_item_id: int,
        work_attempt_id: int,
    ) -> GeneratedCues:
        try:
            async with self._session_factory() as session:
                transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
                metadata = await transcripts.get_transcript_metadata(transcript_id)
                if metadata is None:
                    raise YouTubeTranscriptMetadataNotFound("Transcript metadata was not found.")
                payload = await self._storage.read_transcript(
                    YouTubeTranscriptStorageReadRequest(object_name=metadata.storage_object_name)
                )
                try:
                    content = TranscriptResponse.model_validate_json(payload)
                except ValueError as exc:
                    raise YouTubeTranscriptStorageError(
                        "Stored transcript payload is invalid."
                    ) from exc
                creates = build_transcript_cues(
                    transcript_id,
                    (
                        TranscriptCueSegmentInput(
                            text=segment.text,
                            start_seconds=segment.start,
                            duration_seconds=segment.duration,
                        )
                        for segment in content.segments
                    ),
                    source_work_item_id=work_item_id,
                    source_work_attempt_id=work_attempt_id,
                )
                records = await SqlAlchemyTranscriptCueRepository(session).replace_cues(
                    transcript_id,
                    creates,
                )
        except YouTubeTranscriptPersistenceError as exc:
            raise TranscriptPersistenceUnavailable() from exc
        return GeneratedCues(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
        )


def _stored(
    metadata: YouTubeTranscriptMetadataRecord,
    *,
    reused_existing: bool = False,
) -> StoredTranscript:
    return StoredTranscript(
        transcript_id=metadata.id,
        youtube_video_id=metadata.video_id,
        language_code=metadata.language_code,
        response_sha256=metadata.response_sha256,
        reused_existing=reused_existing,
    )
