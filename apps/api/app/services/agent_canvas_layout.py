"""Independent position-only authoring for Agent Canvas."""

from __future__ import annotations

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas import (
    CanvasLayoutPatchRequestV2,
    CanvasLayoutPatchResponseV2,
)


class AgentCanvasLayoutService:
    """Persist one atomic layout batch without semantic authoring changes."""

    def __init__(self, workflows: AgentCanvasWorkflowRepository) -> None:
        self._workflows = workflows

    def update_layout(
        self,
        workflow_id: str,
        request: CanvasLayoutPatchRequestV2,
    ) -> CanvasLayoutPatchResponseV2:
        return self._workflows.update_layout(
            workflow_id,
            positions={
                position.node_id: (position.x, position.y) for position in request.positions
            },
            expected_layout_revision=request.expected_layout_revision,
        )
