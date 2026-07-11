from __future__ import annotations

import asyncio
import os
import socket

from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging
from codex_sdk_cli.bootstrap.workers import WorkRuntime
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.work import WorkCooldownPolicy, run_worker_loop


def run_transcript() -> None:
    configure_runtime_logging()
    asyncio.run(run_transcript_worker())


def run_transcript_cue() -> None:
    configure_runtime_logging()
    asyncio.run(run_transcript_cue_worker())


async def run_transcript_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
) -> None:
    resolved = settings or CliSettings()
    await _run(
        settings=resolved,
        task_type="transcript_collect",
        concurrency=resolved.transcript_collect_concurrency_limit,
        poll_interval_seconds=resolved.transcript_worker_poll_interval_seconds,
        configured_worker_id=resolved.transcript_worker_id,
        cooldown_policy=WorkCooldownPolicy(
            delay_seconds=resolved.transcript_collect_delay_seconds,
            exempt_outcome_codes=frozenset({"no_transcript"}),
        ),
        stop_after_one=stop_after_one,
    )


async def run_transcript_cue_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
) -> None:
    resolved = settings or CliSettings()
    await _run(
        settings=resolved,
        task_type="transcript_cue_generate",
        concurrency=resolved.transcript_cue_generate_concurrency_limit,
        poll_interval_seconds=resolved.transcript_cue_worker_poll_interval_seconds,
        configured_worker_id=resolved.transcript_cue_worker_id,
        cooldown_policy=WorkCooldownPolicy(),
        stop_after_one=stop_after_one,
    )


async def _run(
    *,
    settings: CliSettings,
    task_type: str,
    concurrency: int,
    poll_interval_seconds: int,
    configured_worker_id: str | None,
    cooldown_policy: WorkCooldownPolicy,
    stop_after_one: bool,
) -> None:
    runtime = WorkRuntime(settings)
    worker_prefix = configured_worker_id or (
        f"{task_type}-worker:{socket.gethostname()}:{os.getpid()}"
    )
    try:
        await run_worker_loop(
            lambda slot: runtime.execution_engine(
                task_types=(task_type,),
                worker_id=f"{worker_prefix}:{slot}",
            ),
            concurrency=concurrency,
            poll_interval_seconds=poll_interval_seconds,
            cooldown_policy=cooldown_policy,
            stop_after_one=stop_after_one,
        )
    finally:
        await runtime.close()
