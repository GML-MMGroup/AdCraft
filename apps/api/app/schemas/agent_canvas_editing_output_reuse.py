"""Contracts for reusing a terminal Editing Export on the Agent Canvas."""

from __future__ import annotations

from app.schemas.agent_canvas import (
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetV2,
    _AgentCanvasModel,
)


class EditingExportOutputReuseRequestV2(_AgentCanvasModel):
    export_id: str
    title: str | None = None
    position: CanvasPositionV2


class EditingExportOutputReuseResponseV2(_AgentCanvasModel):
    workflow_id: str
    revision: int
    layout_revision: int
    node: CanvasNodeV2
    binding: CanvasBindingV2
    asset: ProjectAssetV2
    events_cursor: int
    replayed: bool = False
