from __future__ import annotations

import asyncio
import logging
import os
import socket

from codex_sdk_cli.bootstrap.workers import WorkRuntime
from codex_sdk_cli.infra.database import models as database_models
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.work import run_worker_loop

logger = logging.getLogger(__name__)


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


async def run_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
) -> None:
    resolved = settings or CliSettings()
    _ = database_models.__all__
    runtime = WorkRuntime(resolved)
    worker_id = _worker_id(resolved)
    logger.info(
        "Starting micro-event work engine id=%s concurrency=%s",
        worker_id,
        resolved.micro_event_extract_concurrency_limit,
    )
    try:
        await run_worker_loop(
            lambda slot: runtime.execution_engine(
                task_types=("micro_event_extract",),
                worker_id=f"{worker_id}:slot-{slot}",
            ),
            concurrency=resolved.micro_event_extract_concurrency_limit,
            poll_interval_seconds=resolved.micro_event_worker_poll_interval_seconds,
            stop_after_one=stop_after_one,
        )
    finally:
        await runtime.close()


def _worker_id(settings: CliSettings) -> str:
    return settings.micro_event_worker_id or (
        f"micro-event-worker:{socket.gethostname()}:{os.getpid()}"
    )
