"""Conservative reclamation for superseded Agent Canvas Editing outputs."""

from __future__ import annotations

from app.persistence.agent_canvas_editing_repository import (
    AgentCanvasEditingExportRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.services.agent_canvas_assets import AgentCanvasAssetService


class SupersededExportReclamationService:
    """Delete only superseded export assets with no live canvas reference."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        exports: AgentCanvasEditingExportRepository,
        assets: AgentCanvasAssetService,
    ) -> None:
        self._workflows = workflows
        self._exports = exports
        self._assets = assets

    def list_eligible(self, workflow_id: str, node_id: str) -> tuple[str, ...]:
        current = self._workflows.get_node(workflow_id, node_id).output_asset_id
        candidates = []
        for export in self._exports.list_completed(workflow_id, node_id):
            asset_id = export.output_asset_id
            if (
                asset_id is not None
                and asset_id != current
                and not self._workflows.asset_is_referenced(asset_id)
            ):
                candidates.append(asset_id)
        return tuple(dict.fromkeys(candidates))

    def reclaim(self, workflow_id: str, node_id: str, asset_id: str) -> bool:
        if asset_id not in self.list_eligible(workflow_id, node_id):
            return False
        self._assets.delete_asset(asset_id)
        return True
