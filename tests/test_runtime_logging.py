from __future__ import annotations

import logging

from codex_sdk_cli.bootstrap.runtime_logging import configure_runtime_logging


def test_runtime_logging_suppresses_http_request_urls() -> None:
    configure_runtime_logging()

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
