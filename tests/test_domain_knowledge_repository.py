from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainEntryAliasCreate,
    DomainEntryAliasUpdate,
    DomainEntryCreate,
    DomainEntryListQuery,
    DomainEntryStreamerLinkCreate,
    DomainEntryTypeCreate,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.domain_knowledge.repository import SqlAlchemyDomainKnowledgeRepository
from codex_sdk_cli.infra.streamers.repository import StreamerModel


def test_domain_knowledge_repository_manages_entries_and_prompt_scope(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    result = asyncio.run(_exercise_repository(database_url))

    assert result == {
        "seed_has_person": True,
        "same_type_reused": True,
        "created_type_key": "사람-이름",
        "entry_streamer_count": 1,
        "entry_alias_count": 1,
        "streamer_scoped_names": ["전역 용어", "테스트 인물"],
        "all_active_count": 2,
        "prompt_names": ["전역 용어", "테스트 인물"],
        "updated_alias_apply_scope": "DISPLAY_ALLOWED",
        "deleted_alias": True,
    }


async def _exercise_repository(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamer_id = await _create_streamer(session)
            repository = SqlAlchemyDomainKnowledgeRepository(session)
            seed_types = await repository.list_types()
            created_type = await repository.get_or_create_type(
                DomainEntryTypeCreate(key=None, label="사람 이름")
            )
            same_type = await repository.get_or_create_type(
                DomainEntryTypeCreate(key=None, label="  사람   이름  ")
            )
            global_type = await repository.get_or_create_type(
                DomainEntryTypeCreate(key="term", label="Term")
            )
            entry = await repository.create_entry(
                DomainEntryCreate(
                    type_id=created_type.id,
                    canonical_name="테스트 인물",
                    detail="테스트 인물에 대한 설명",
                    prompt_policy="AUTO_ON_MATCH",
                    priority=50,
                    streamer_links=[DomainEntryStreamerLinkCreate(streamer_id=streamer_id)],
                    aliases=[
                        DomainEntryAliasCreate(
                            surface_form="테인",
                            alias_kind="ASR_ERROR",
                            certainty="HIGH",
                            apply_scope="SEARCH_AND_SUMMARY",
                        )
                    ],
                )
            )
            await repository.create_entry(
                DomainEntryCreate(
                    type_id=global_type.id,
                    canonical_name="전역 용어",
                    detail="모든 스트리머에 적용되는 전역 설명",
                    prompt_policy="ALWAYS_FOR_SCOPED_STREAMER",
                    priority=80,
                )
            )
            await repository.create_entry(
                DomainEntryCreate(
                    type_id=global_type.id,
                    canonical_name="비활성 용어",
                    detail="prompt에 들어가면 안 되는 설명",
                    prompt_policy="DISABLED",
                    priority=90,
                    is_active=False,
                )
            )
            streamer_scoped = await repository.list_entries(
                DomainEntryListQuery(streamer_id=streamer_id, active=True)
            )
            all_active = await repository.list_entries(DomainEntryListQuery(active=True))
            prompt_entries = await repository.list_prompt_entries_for_streamer(streamer_id)
            alias = entry.aliases[0]
            updated_alias = await repository.update_alias(
                alias.id,
                DomainEntryAliasUpdate(apply_scope="DISPLAY_ALLOWED"),
            )
            deleted_alias = await repository.delete_alias(alias.id)
            return {
                "seed_has_person": any(item.key == "person" for item in seed_types),
                "same_type_reused": created_type.id == same_type.id,
                "created_type_key": created_type.key,
                "entry_streamer_count": len(entry.streamers),
                "entry_alias_count": len(entry.aliases),
                "streamer_scoped_names": sorted(item.canonical_name for item in streamer_scoped),
                "all_active_count": len(all_active),
                "prompt_names": sorted(item.canonical_name for item in prompt_entries),
                "updated_alias_apply_scope": (
                    updated_alias.apply_scope if updated_alias is not None else None
                ),
                "deleted_alias": deleted_alias,
            }
    finally:
        await engine.dispose()


async def _create_streamer(session: AsyncSession) -> int:
    streamer = StreamerModel(name="Streamer")
    session.add(streamer)
    await session.commit()
    await session.refresh(streamer)
    return streamer.id
