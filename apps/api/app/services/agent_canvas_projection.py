"""Rebuildable filesystem projection for SQLite-backed Agent Canvas workflows."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas import AgentCanvasWorkflowV2


class AgentCanvasProjectionService:
    """Write projections from SQLite without ever reading them as authoring input."""

    def __init__(
        self,
        data_dir: Path,
        repository: AgentCanvasWorkflowRepository,
    ) -> None:
        self._data_dir = data_dir
        self._repository = repository

    def rebuild(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        workflow = self._repository.get_workflow(workflow_id)
        destination = self._data_dir / "v2" / "workflows" / workflow_id / "workflow.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".workflow-{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                workflow.model_dump_json(indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return workflow
