"""SQLite-backed authority boundary for legacy V1 workflow routes."""

from __future__ import annotations

from typing import Protocol

from app.persistence.errors import V2PersistenceError


class WorkflowMembershipRepository(Protocol):
    """Minimal read-only contract needed to classify workflow ownership."""

    def exists(self, workflow_id: str) -> bool: ...


class V1WorkflowAuthorityError(RuntimeError):
    """Bounded public failure raised before a V1 workflow operation starts."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"code": code, "message": message}


class V1WorkflowAuthorityBoundary:
    """Reject V1 operations when SQLite owns an Agent Canvas workflow."""

    def __init__(self, workflows: WorkflowMembershipRepository) -> None:
        self._workflows = workflows

    def assert_legacy_workflow(self, workflow_id: str) -> None:
        try:
            is_agent_canvas = self._workflows.exists(workflow_id)
        except V2PersistenceError as exc:
            raise V1WorkflowAuthorityError(
                503,
                "workflow_authority_unavailable",
                "Workflow authority could not be determined.",
            ) from exc
        if is_agent_canvas:
            raise V1WorkflowAuthorityError(
                422,
                "unsupported_workflow_schema_version",
                "Use /api/v2 for Agent Canvas workflows.",
            )
