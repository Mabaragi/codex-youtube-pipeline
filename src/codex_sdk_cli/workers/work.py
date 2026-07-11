from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from codex_sdk_cli.application.work.execution import WorkExecutionEngine

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


async def run_worker_loop(
    engine_factory: Callable[[int], WorkExecutionEngine],
    *,
    concurrency: int,
    poll_interval_seconds: int,
    stop_after_one: bool = False,
    sleep: Sleep = asyncio.sleep,
) -> None:
    if concurrency < 1:
        raise ValueError("Worker concurrency must be positive.")
    await asyncio.gather(
        *(
            _run_slot(
                engine_factory(slot),
                poll_interval_seconds=poll_interval_seconds,
                stop_after_one=stop_after_one,
                sleep=sleep,
            )
            for slot in range(concurrency)
        )
    )


async def _run_slot(
    engine: WorkExecutionEngine,
    *,
    poll_interval_seconds: int,
    stop_after_one: bool,
    sleep: Sleep,
) -> None:
    recovered = await engine.recover_expired()
    if recovered:
        logger.warning("Recovered %s expired work item(s)", recovered)
    while True:
        processed = await engine.run_once()
        if stop_after_one:
            return
        if not processed:
            await sleep(float(poll_interval_seconds))
