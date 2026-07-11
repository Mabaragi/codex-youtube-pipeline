from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from codex_sdk_cli.application.work.execution import WorkExecutionEngine, WorkRunResult

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WorkCooldownPolicy:
    delay_seconds: int = 0
    exempt_outcome_codes: frozenset[str] = frozenset()

    def delay_for(self, result: WorkRunResult) -> float:
        if result.cooldown_seconds_override is not None:
            return float(result.cooldown_seconds_override)
        if not result.processed or result.outcome_code in self.exempt_outcome_codes:
            return 0.0
        return float(self.delay_seconds)


async def run_worker_loop(
    engine_factory: Callable[[int], WorkExecutionEngine],
    *,
    concurrency: int,
    poll_interval_seconds: int,
    cooldown_policy: WorkCooldownPolicy | None = None,
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
                cooldown_policy=cooldown_policy or WorkCooldownPolicy(),
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
    cooldown_policy: WorkCooldownPolicy,
    stop_after_one: bool,
    sleep: Sleep,
) -> None:
    recovered = await engine.recover_expired()
    if recovered:
        logger.warning("Recovered %s expired work item(s)", recovered)
    while True:
        result = await engine.run_once_with_result()
        if stop_after_one:
            return
        cooldown_seconds = cooldown_policy.delay_for(result)
        if cooldown_seconds:
            await sleep(cooldown_seconds)
        elif not result.processed:
            await sleep(float(poll_interval_seconds))
