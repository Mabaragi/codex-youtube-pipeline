from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging
from codex_sdk_cli.bootstrap.video_availability import VideoAvailabilityRuntime
from codex_sdk_cli.domains.video_availability.use_cases import (
    ProcessVideoAvailabilityCandidatesResult,
)
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]


class VideoAvailabilityWorkerRuntime(Protocol):
    async def cleanup(self) -> int: ...

    async def process_once(self) -> ProcessVideoAvailabilityCandidatesResult: ...

    async def close(self) -> None: ...


def run() -> None:
    configure_runtime_logging()
    asyncio.run(run_worker())


async def run_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
    sleep: Sleep = asyncio.sleep,
    monotonic: Monotonic = time.monotonic,
    runtime: VideoAvailabilityWorkerRuntime | None = None,
) -> None:
    resolved = settings or CliSettings()
    worker_id = resolved.archive_video_availability_worker_id or (
        f"video-availability:{socket.gethostname()}:{os.getpid()}"
    )
    if not resolved.archive_video_availability_enabled:
        logger.info("Video availability worker is disabled id=%s", worker_id)
        return

    resolved_runtime = runtime or VideoAvailabilityRuntime(resolved, worker_id=worker_id)
    logger.info("Starting video availability worker id=%s", worker_id)
    last_cleanup = monotonic()
    try:
        try:
            recovered = await resolved_runtime.cleanup()
            logger.info(
                "Video availability cleanup completed id=%s recovered=%s",
                worker_id,
                recovered,
            )
        except Exception:
            logger.exception("Video availability startup cleanup failed id=%s", worker_id)
            last_cleanup -= resolved.archive_video_availability_cleanup_interval_seconds

        while True:
            try:
                result = await resolved_runtime.process_once()
                if result.claimed_count:
                    logger.info(
                        "Video availability batch completed id=%s claimed=%s "
                        "available=%s unavailable=%s retry=%s",
                        worker_id,
                        result.claimed_count,
                        result.available_count,
                        result.unavailable_count,
                        result.retry_count,
                    )
            except Exception:
                logger.exception("Video availability batch failed id=%s", worker_id)

            if stop_after_one:
                return
            now = monotonic()
            if (
                now - last_cleanup
                >= resolved.archive_video_availability_cleanup_interval_seconds
            ):
                try:
                    recovered = await resolved_runtime.cleanup()
                    logger.info(
                        "Video availability cleanup completed id=%s recovered=%s",
                        worker_id,
                        recovered,
                    )
                except Exception:
                    logger.exception("Video availability cleanup failed id=%s", worker_id)
                else:
                    last_cleanup = now
            await sleep(float(resolved.archive_video_availability_poll_interval_seconds))
    finally:
        await resolved_runtime.close()


if __name__ == "__main__":
    run()
