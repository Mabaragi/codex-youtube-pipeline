from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.constants import MICRO_EVENT_EXTRACT_PROMPT_KEY
from codex_sdk_cli.domains.prompts.exceptions import PromptConflict, PromptNotFound
from codex_sdk_cli.domains.prompts.ports import PromptVersionCreate, PromptVersionUpdate
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository


def test_prompt_repository_manages_versions_and_active_resolution(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    result = asyncio.run(_exercise_repository(database_url))

    assert result["fallback_source"] == "fallback"
    assert result["draft_status"] == "DRAFT"
    assert result["duplicate_conflict"] is True
    assert result["updated_sha"] == _sha256("draft-one-updated")
    assert result["published_status"] == "PUBLISHED"
    assert result["request_selected_body"] == "draft-one-updated"
    assert result["request_missing_not_found"] is True
    assert result["request_draft_conflict"] is True
    assert result["request_archived_conflict"] is True
    assert result["active_after_second_publish"] == "db-v2"
    assert result["cached_before_invalidate"] == "db-v1"
    assert result["resolved_after_invalidate"] == "db-v2"
    assert result["exact_queued_version_body"] == "draft-one-updated"
    assert result["active_after_rollback"] == "db-v1"
    assert result["archive_active_conflict"] is True
    assert result["archived_inactive_status"] == "ARCHIVED"
    assert result["archived_draft_status"] == "ARCHIVED"


async def _exercise_repository(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyPromptRepository(session)
            cache = PromptCache()
            resolver = PromptResolver(repository, cache=cache, ttl_seconds=60)
            fallback = await resolver.resolve_prompt(MICRO_EVENT_EXTRACT_PROMPT_KEY)

            draft = await repository.create_version(
                PromptVersionCreate(
                    prompt_key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    version_label="db-v1",
                    body="draft-one",
                    body_sha256=_sha256("draft-one"),
                    source_note="first draft",
                )
            )
            duplicate_conflict = False
            try:
                await repository.create_version(
                    PromptVersionCreate(
                        prompt_key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
                        version_label="db-v1",
                        body="duplicate",
                        body_sha256=_sha256("duplicate"),
                    )
                )
            except PromptConflict:
                duplicate_conflict = True

            updated = await repository.update_draft(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                draft.id,
                PromptVersionUpdate(
                    body="draft-one-updated",
                    body_sha256=_sha256("draft-one-updated"),
                    body_set=True,
                ),
            )
            assert updated is not None
            published = await repository.publish_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                draft.id,
            )
            assert published is not None
            cache.invalidate(MICRO_EVENT_EXTRACT_PROMPT_KEY)
            cached_before_publish = await resolver.resolve_prompt(MICRO_EVENT_EXTRACT_PROMPT_KEY)

            second = await repository.create_version(
                PromptVersionCreate(
                    prompt_key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    version_label="db-v2",
                    body="draft-two",
                    body_sha256=_sha256("draft-two"),
                )
            )
            await repository.publish_version(MICRO_EVENT_EXTRACT_PROMPT_KEY, second.id)
            active_after_second_publish = await repository.get_active_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY
            )
            cached_before_invalidate = await resolver.resolve_prompt(MICRO_EVENT_EXTRACT_PROMPT_KEY)
            cache.invalidate(MICRO_EVENT_EXTRACT_PROMPT_KEY)
            resolved_after_invalidate = await resolver.resolve_prompt(
                MICRO_EVENT_EXTRACT_PROMPT_KEY
            )
            exact_queued = await resolver.resolve_prompt_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                draft.id,
            )
            request_selected = await resolver.resolve_prompt_for_request(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                draft.id,
            )
            request_missing_not_found = False
            try:
                await resolver.resolve_prompt_for_request(
                    MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    999_999,
                )
            except PromptNotFound:
                request_missing_not_found = True
            draft_to_reject = await repository.create_version(
                PromptVersionCreate(
                    prompt_key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    version_label="db-draft-request",
                    body="draft-request",
                    body_sha256=_sha256("draft-request"),
                )
            )
            request_draft_conflict = False
            try:
                await resolver.resolve_prompt_for_request(
                    MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    draft_to_reject.id,
                )
            except PromptConflict:
                request_draft_conflict = True

            await repository.publish_version(MICRO_EVENT_EXTRACT_PROMPT_KEY, draft.id)
            active_after_rollback = await repository.get_active_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY
            )
            archive_active_conflict = False
            try:
                await repository.archive_version(MICRO_EVENT_EXTRACT_PROMPT_KEY, draft.id)
            except PromptConflict:
                archive_active_conflict = True

            archived_inactive = await repository.archive_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                second.id,
            )
            archived_draft = await repository.archive_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                draft_to_reject.id,
            )
            request_archived_conflict = False
            try:
                await resolver.resolve_prompt_for_request(
                    MICRO_EVENT_EXTRACT_PROMPT_KEY,
                    second.id,
                )
            except PromptConflict:
                request_archived_conflict = True
            assert active_after_second_publish is not None
            assert active_after_rollback is not None
            assert archived_inactive is not None
            assert archived_draft is not None
            return {
                "fallback_source": fallback.source,
                "draft_status": draft.status,
                "duplicate_conflict": duplicate_conflict,
                "updated_sha": updated.body_sha256,
                "published_status": published.status,
                "request_selected_body": request_selected.body,
                "request_missing_not_found": request_missing_not_found,
                "request_draft_conflict": request_draft_conflict,
                "request_archived_conflict": request_archived_conflict,
                "active_after_second_publish": active_after_second_publish.version_label,
                "cached_before_invalidate": cached_before_invalidate.version_label,
                "cached_before_publish": cached_before_publish.version_label,
                "resolved_after_invalidate": resolved_after_invalidate.version_label,
                "exact_queued_version_body": exact_queued.body,
                "active_after_rollback": active_after_rollback.version_label,
                "archive_active_conflict": archive_active_conflict,
                "archived_inactive_status": archived_inactive.status,
                "archived_draft_status": archived_draft.status,
            }
    finally:
        await engine.dispose()


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
