from __future__ import annotations

import asyncio
import os
import socket

from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging
from codex_sdk_cli.bootstrap.workers import WorkRuntime
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.work import run_worker_loop


def run() -> None:
    configure_runtime_logging()
    asyncio.run(run_worker())


async def run_worker(*, settings: CliSettings | None = None, stop_after_one: bool = False) -> None:
    resolved = settings or CliSettings()
    runtime = WorkRuntime(resolved)
    worker_id = (
        resolved.archive_publish_worker_id
        or f"archive-publish-worker:{socket.gethostname()}:{os.getpid()}"
    )
    try:
        await run_worker_loop(
            lambda slot: runtime.execution_engine(
                task_types=("archive_publish",), worker_id=f"{worker_id}:{slot}"
            ),
            concurrency=1,
            poll_interval_seconds=resolved.archive_publish_worker_poll_interval_seconds,
            stop_after_one=stop_after_one,
        )
    finally:
        await runtime.close()


if __name__ == "__main__":
    run()
