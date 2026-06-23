from __future__ import annotations


class DomainKnowledgeDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DomainKnowledgeNotFound(DomainKnowledgeDomainError):
    """Requested domain knowledge row does not exist."""


class DomainKnowledgeConflict(DomainKnowledgeDomainError):
    """Domain knowledge row conflicts with an existing row."""


class DomainKnowledgePersistenceError(DomainKnowledgeDomainError):
    """Domain knowledge persistence failed."""
