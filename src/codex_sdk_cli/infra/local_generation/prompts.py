from __future__ import annotations

from sqlalchemy import text

from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
    PromptKey,
)
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.settings import CliSettings

PROMPT_KEYS = (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)


class ReadOnlyActivePrompts:
    def __init__(self, settings: CliSettings) -> None:
        self._settings = settings

    async def resolve(self) -> dict[PromptKey, ResolvedPrompt]:
        engine = create_database_engine(self._settings.database_url, echo=False)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    )
                resolver = PromptResolver(
                    SqlAlchemyPromptRepository(session),
                    cache=PromptCache(),
                    ttl_seconds=0,
                )
                prompts = {key: await resolver.resolve_prompt(key) for key in PROMPT_KEYS}
                for key in (MICRO_EVENT_EXTRACT_PROMPT_KEY, TIMELINE_COMPOSE_PROMPT_KEY):
                    if prompts[key].source != "database":
                        raise RuntimeError(f"No active database prompt exists for {key}.")
                return prompts
        finally:
            await engine.dispose()
