from __future__ import annotations

import subprocess
import sys


def test_timeline_worker_import_registers_video_task_fk_targets() -> None:
    script = (
        "from codex_sdk_cli.infra.database.base import Base\n"
        "import codex_sdk_cli.workers.timelines\n"
        "assert 'youtube_transcripts' in Base.metadata.tables\n"
        "assert 'video_tasks' in Base.metadata.tables\n"
    )

    subprocess.run([sys.executable, "-c", script], check=True)
