"""Operation event domain exceptions."""


class OperationEventDomainError(Exception):
    """Base exception for operation event failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OperationEventPersistenceError(OperationEventDomainError):
    """Raised when operation events cannot be persisted or queried."""
