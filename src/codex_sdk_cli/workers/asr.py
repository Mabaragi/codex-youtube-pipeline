from __future__ import annotations

import asyncio
import logging
import os
import socket

from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging
from codex_sdk_cli.bootstrap.workers import WorkRuntime
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.work import run_worker_loop

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
    runtime = WorkRuntime(resolved)
    worker_id = resolved.asr_worker_id or f"asr-worker:{socket.gethostname()}:{os.getpid()}"
    logger.info("Starting ASR work engine id=%s concurrency=1", worker_id)
    try:
        await run_worker_loop(
            lambda slot: runtime.execution_engine(
                task_types=("asr_transcribe",),
                worker_id=f"{worker_id}:slot-{slot}",
            ),
            concurrency=1,
            poll_interval_seconds=resolved.asr_worker_poll_interval_seconds,
            stop_after_one=stop_after_one,
        )
    finally:
        await runtime.close()


if __name__ == "__main__":
    run()
