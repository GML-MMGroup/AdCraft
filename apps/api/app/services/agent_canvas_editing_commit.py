"""Terminal commit service for Agent Canvas Editing exports."""

from __future__ import annotations

from app.persistence.agent_canvas_editing_commit_repository import (
    AgentCanvasEditingExportCommitRepository,
)
from app.schemas.agent_canvas_editing_authority import (
    EditingExportCommitCommandV2,
    EditingExportCommitReceiptV2,
)


class AgentCanvasEditingExportCommitService:
    """Expose the single terminal authority boundary to orchestration."""

    def __init__(self, repository: AgentCanvasEditingExportCommitRepository) -> None:
        self._repository = repository

    def commit(
        self,
        command: EditingExportCommitCommandV2,
    ) -> EditingExportCommitReceiptV2:
        return self._repository.commit(command)

    def receipt_for_export(self, export_id: str) -> EditingExportCommitReceiptV2:
        return self._repository.receipt_for_export(export_id)
