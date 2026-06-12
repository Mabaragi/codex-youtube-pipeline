from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.settings import CliSettings


@lru_cache
def get_settings() -> CliSettings:
    return CliSettings()


async def get_codex_runtime(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> CodexRuntimePort:
    return CodexRuntimeClient(settings)


SettingsDep = Annotated[CliSettings, Depends(get_settings)]
CodexRuntimeDep = Annotated[CodexRuntimePort, Depends(get_codex_runtime)]
