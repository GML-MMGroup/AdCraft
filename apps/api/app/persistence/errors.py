"""Typed errors raised by V2 persistence services."""

from __future__ import annotations


class V2PersistenceError(RuntimeError):
    """Represents a structured V2 persistence failure."""

    def __init__(self, code: str, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage

    def safe_details(self) -> dict[str, str]:
        """Return bounded details suitable for controlled diagnostics."""

        details = {"code": self.code, "message": str(self)}
        if self.stage:
            details["stage"] = self.stage
        return details
