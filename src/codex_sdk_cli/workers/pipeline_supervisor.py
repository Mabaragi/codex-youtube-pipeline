from __future__ import annotations

import asyncio
import logging
import os
import socket

from codex_sdk_cli.application.automation.use_cases import RunPipelineSupervisorUseCase
from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging
from codex_sdk_cli.infra.automation.repository import (
    SqlAlchemyAutomationRepository,
    SqlAlchemySafeRemediator,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)


def run() -> None:
    configure_runtime_logging()
    asyncio.run(run_worker())


async def run_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
) -> None:
    resolved = settings or CliSettings()
    if not resolved.pipeline_supervisor_enabled:
        return
    worker_id = resolved.pipeline_supervisor_id or (
        f"pipeline-supervisor:{socket.gethostname()}:{os.getpid()}"
    )
    engine = create_database_engine(resolved.database_url, echo=resolved.database_echo)
    session_factory = create_session_factory(engine)
    repository = SqlAlchemyAutomationRepository(session_factory)
    use_case = RunPipelineSupervisorUseCase(
        reader=repository,
        incidents=repository,
        remediator=SqlAlchemySafeRemediator(session_factory),
    )
    logger.info("Starting pipeline supervisor id=%s", worker_id)
    try:
        while True:
            try:
                result = await use_case.execute_once()
                logger.info("Pipeline supervisor tick completed id=%s result=%s", worker_id, result)
            except Exception:
                logger.exception("Pipeline supervisor tick failed id=%s", worker_id)
            if stop_after_one:
                return
            await asyncio.sleep(resolved.pipeline_supervisor_poll_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    run()
