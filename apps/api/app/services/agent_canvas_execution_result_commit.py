"""Service facade for the one Agent Canvas terminal result authority."""

from __future__ import annotations

from app.persistence.agent_canvas_result_commit_repository import (
    AgentCanvasResultCommitRepository,
)
from app.schemas.agent_canvas_runtime_authority import (
    CanvasExecutionResultCommitCommandV2,
    CanvasExecutionResultCommitReceiptV2,
    CanvasPostReadyEffectV2,
)


class AgentCanvasExecutionResultCommitService:
    def __init__(self, repository: AgentCanvasResultCommitRepository) -> None:
        self._repository = repository

    def commit(
        self,
        command: CanvasExecutionResultCommitCommandV2,
    ) -> CanvasExecutionResultCommitReceiptV2:
        return self._repository.commit(command)

    def reconcile_stale_lease_failure(
        self,
        command: CanvasExecutionResultCommitCommandV2,
    ) -> CanvasExecutionResultCommitReceiptV2 | None:
        return self._repository.reconcile_stale_lease_failure(command)

    def list_receipts(self, execution_id: str) -> tuple[CanvasExecutionResultCommitReceiptV2, ...]:
        return self._repository.list_receipts(execution_id)

    def list_post_ready_effects(self, execution_id: str) -> tuple[CanvasPostReadyEffectV2, ...]:
        return self._repository.list_post_ready_effects(execution_id)
