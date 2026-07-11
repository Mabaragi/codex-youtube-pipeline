from __future__ import annotations

import logging


def configure_runtime_logging(*, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
