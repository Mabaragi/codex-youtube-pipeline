from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable

from codex_sdk_cli.bootstrap.scheduler import PipelineSchedulerRuntime
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


async def run_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
    sleep: Sleep = asyncio.sleep,
) -> None:
    resolved = settings or CliSettings()
    worker_id = _worker_id(resolved)
    if not resolved.pipeline_scheduler_enabled:
        logger.info("Pipeline scheduler is disabled id=%s", worker_id)
        return

    runtime = PipelineSchedulerRuntime(resolved, worker_id=worker_id)
    logger.info("Starting pipeline scheduler id=%s", worker_id)
    try:
        use_case = runtime.use_case()
        while True:
            try:
                result = await use_case.execute_once()
                logger.info(
                    "Pipeline scheduler tick completed id=%s channels=%s "
                    "processed=%s skipped=%s failed=%s",
                    worker_id,
                    result.channel_count,
                    result.processed_channel_count,
                    result.skipped_channel_count,
                    result.failed_channel_count,
                )
            except Exception:
                logger.exception("Pipeline scheduler tick failed id=%s", worker_id)
            if stop_after_one:
                return
            await sleep(resolved.pipeline_scheduler_poll_interval_seconds)
    finally:
        await runtime.close()


def _worker_id(settings: CliSettings) -> str:
    return settings.pipeline_scheduler_id or (
        f"pipeline-scheduler:{socket.gethostname()}:{os.getpid()}"
    )


if __name__ == "__main__":
    run()
