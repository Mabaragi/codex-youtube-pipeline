from __future__ import annotations


class PromptDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PromptNotFound(PromptDomainError):
    """Prompt or prompt version was not found."""


class PromptConflict(PromptDomainError):
    """Prompt operation conflicts with existing state."""


class PromptInvalid(PromptDomainError):
    """Prompt request is invalid for the current state."""


class PromptPersistenceError(PromptDomainError):
    """Prompt persistence failed."""
