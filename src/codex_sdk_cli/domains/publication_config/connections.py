from __future__ import annotations

import re
from typing import Literal

PublicationConnectionKind = Literal[
    "s3_compatible_object",
    "http_catalog",
    "sql_catalog",
]

_SAFE_CONNECTION_REF = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}", re.ASCII)


def is_safe_connection_ref(value: str) -> bool:
    """Return whether a value is a registry identifier rather than connection material."""
    return _SAFE_CONNECTION_REF.fullmatch(value) is not None
