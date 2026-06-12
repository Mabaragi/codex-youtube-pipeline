from __future__ import annotations


class CodexDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidCodexRequest(CodexDomainError):
    """Raised when an API request cannot become a Codex operation."""


class CodexRuntimeError(CodexDomainError):
    """Raised when the Codex runtime or SDK boundary fails."""
