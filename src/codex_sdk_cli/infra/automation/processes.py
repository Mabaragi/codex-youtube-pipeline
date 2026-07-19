from __future__ import annotations

import asyncio
import os
import platform as platform_module
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psutil
from typing_extensions import override

from codex_sdk_cli.domains.automation.ports import (
    ManagedProcess,
    ManagedProcessInventory,
    ManagedProcessReaderPort,
    ManagedProcessState,
)


@dataclass(frozen=True, slots=True)
class ManagedProcessDefinition:
    name: str
    role: str
    command_marker: str
    source: str = "pid_file"


_MANAGED_PROCESSES = (
    ManagedProcessDefinition("api", "api", "codex_sdk_cli.api.main:app", "current_process"),
    ManagedProcessDefinition("transcript-worker", "worker", "run_transcript"),
    ManagedProcessDefinition("transcript-cue-worker", "worker", "run_transcript_cue"),
    ManagedProcessDefinition("asr-worker", "worker", "codex_sdk_cli.workers.asr"),
    ManagedProcessDefinition(
        "micro-event-worker", "worker", "codex_sdk_cli.workers.micro_events"
    ),
    ManagedProcessDefinition(
        "timeline-compose-worker", "worker", "codex_sdk_cli.workers.timelines"
    ),
    ManagedProcessDefinition(
        "workflow-coordinator", "coordinator", "codex_sdk_cli.workers.workflow_coordinator"
    ),
    ManagedProcessDefinition(
        "pipeline-supervisor", "supervisor", "codex_sdk_cli.workers.pipeline_supervisor"
    ),
    ManagedProcessDefinition(
        "pipeline-scheduler", "scheduler", "codex_sdk_cli.workers.pipeline_scheduler"
    ),
    ManagedProcessDefinition(
        "video-availability-worker",
        "worker",
        "codex_sdk_cli.workers.video_availability",
    ),
    ManagedProcessDefinition("ops-ui", "ui", "ops-ui"),
)

ProcessFactory = Callable[[int], psutil.Process]


class PsutilManagedProcessReader(ManagedProcessReaderPort):
    def __init__(
        self,
        *,
        pid_dir: Path,
        repository_root: Path,
        process_factory: ProcessFactory = psutil.Process,
        current_pid: Callable[[], int] = os.getpid,
        host_name: Callable[[], str] = socket.gethostname,
        platform_name: Callable[[], str] = platform_module.platform,
    ) -> None:
        self._pid_dir = pid_dir.resolve()
        self._repository_root = repository_root.resolve()
        self._process_factory = process_factory
        self._current_pid = current_pid
        self._host_name = host_name
        self._platform_name = platform_name

    @override
    async def read(self, *, observed_at: datetime) -> ManagedProcessInventory:
        return await asyncio.to_thread(self._read_sync, observed_at)

    def _read_sync(self, observed_at: datetime) -> ManagedProcessInventory:
        items = tuple(self._inspect(definition) for definition in _MANAGED_PROCESSES)
        return ManagedProcessInventory(
            observed_at=observed_at,
            host_name=self._host_name(),
            platform=self._platform_name(),
            items=items,
        )

    def _inspect(self, definition: ManagedProcessDefinition) -> ManagedProcess:
        pid = self._read_pid(definition)
        if pid is None:
            return _process_result(definition, state="stopped", detail_code="pid_file_missing")
        if pid < 1:
            return _process_result(
                definition,
                state="unreadable",
                detail_code="pid_file_invalid",
            )
        try:
            process = self._process_factory(pid)
            command_line = process.cmdline()
            cwd = Path(process.cwd()).resolve()
            started_at = datetime.fromtimestamp(process.create_time(), tz=UTC)
        except psutil.NoSuchProcess:
            return _process_result(
                definition,
                state="stale_pid",
                pid=pid,
                detail_code="process_not_found",
            )
        except (psutil.AccessDenied, PermissionError, OSError):
            return _process_result(
                definition,
                state="unreadable",
                pid=pid,
                detail_code="process_access_denied",
            )
        if definition.command_marker.lower() not in _command_text(command_line):
            return _process_result(
                definition,
                state="identity_mismatch",
                pid=pid,
                started_at=started_at,
                detail_code="command_marker_mismatch",
            )
        if not _is_within(cwd, self._repository_root) and not _command_references_root(
            command_line,
            self._repository_root,
        ):
            return _process_result(
                definition,
                state="identity_mismatch",
                pid=pid,
                started_at=started_at,
                detail_code="repository_path_mismatch",
            )
        return _process_result(
            definition,
            state="running",
            pid=pid,
            started_at=started_at,
        )

    def _read_pid(self, definition: ManagedProcessDefinition) -> int | None:
        if definition.source == "current_process":
            return self._current_pid()
        path = self._pid_dir / f"{definition.name}.pid"
        if not path.is_file():
            return None
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0


def _command_text(parts: Sequence[str]) -> str:
    return " ".join(parts).lower()


def _command_references_root(parts: Sequence[str], root: Path) -> bool:
    for part in parts:
        candidate_text = part.strip().strip('"')
        if not candidate_text:
            continue
        candidate = Path(candidate_text)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if _is_within(resolved, root):
            return True
    return False


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _process_result(
    definition: ManagedProcessDefinition,
    *,
    state: ManagedProcessState,
    pid: int | None = None,
    started_at: datetime | None = None,
    detail_code: str | None = None,
) -> ManagedProcess:
    return ManagedProcess(
        name=definition.name,
        role=definition.role,
        state=state,
        pid=pid,
        started_at=started_at,
        source=definition.source,
        detail_code=detail_code,
    )
