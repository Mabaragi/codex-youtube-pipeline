from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ErrorKind(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UPSTREAM = "upstream"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    code: str
    message: str
    kind: ErrorKind
    details: dict[str, object] = field(default_factory=dict)


class ApplicationError(Exception):
    """Stable application error that entrypoints can map to transport semantics."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        kind: ErrorKind,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.descriptor = ErrorDescriptor(
            code=code,
            message=message,
            kind=kind,
            details=details or {},
        )

