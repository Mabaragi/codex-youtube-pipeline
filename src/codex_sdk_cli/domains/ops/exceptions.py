from __future__ import annotations


class OpsDomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OpsPersistenceError(OpsDomainError):
    pass


class OpsVideoNotFound(OpsDomainError):
    pass
