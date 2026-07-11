from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable

from codex_sdk_cli.bootstrap.workers import WorkRuntime
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_coordinator())


async def run_coordinator(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
    sleep: Sleep = asyncio.sleep,
) -> None:
    resolved = settings or CliSettings()
    runtime = WorkRuntime(resolved)
    worker_id = resolved.workflow_coordinator_id or (
        f"workflow-coordinator:{socket.gethostname()}:{os.getpid()}"
    )
    coordinator = runtime.workflow_coordinator(worker_id=worker_id)
    try:
        recovered_work, recovered_workflows = await coordinator.recover_expired()
        if recovered_work or recovered_workflows:
            logger.warning(
                "Recovered %s work item(s) and %s workflow(s)",
                recovered_work,
                recovered_workflows,
            )
        while True:
            await coordinator.run_once()
            if stop_after_one:
                return
            await sleep(float(resolved.workflow_coordinator_poll_interval_seconds))
    finally:
        await runtime.close()
