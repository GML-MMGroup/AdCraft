"""Workflow validation and policy for Agent Canvas execution settings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.persistence.agent_canvas_execution_settings_repository import (
    AgentCanvasExecutionSettingsRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_execution_settings import (
    AgentExecutionSettingsPatchV2,
    AgentExecutionSettingsV2,
)


class AgentCanvasExecutionSettingsService:
    """Validate Agent Canvas ownership before reading or changing settings."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        settings: AgentCanvasExecutionSettingsRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if workflows.database is not settings.database:
            raise ValueError("Workflow and execution settings must share one database.")
        self._workflows = workflows
        self._settings = settings
        self._clock = clock

    def get_or_create(self, workflow_id: str) -> AgentExecutionSettingsV2:
        self._require_agent_canvas(workflow_id)
        return self._settings.get_or_create_manual(workflow_id, now=self._clock())

    def update(
        self,
        workflow_id: str,
        request: AgentExecutionSettingsPatchV2,
        *,
        expected_revision: int,
    ) -> AgentExecutionSettingsV2:
        self._require_agent_canvas(workflow_id)
        self._settings.get_or_create_manual(workflow_id, now=self._clock())
        return self._settings.update(
            workflow_id,
            media_execution_mode=request.media_execution_mode,
            expected_revision=expected_revision,
            now=self._clock(),
        )

    def _require_agent_canvas(self, workflow_id: str) -> None:
        try:
            self._workflows.get_workflow(workflow_id)
        except V2PersistenceError as error:
            if error.code == "workflow_not_found" and self._settings.is_structured_workflow(
                workflow_id
            ):
                raise V2PersistenceError(
                    "workflow_not_agent_canvas",
                    "Workflow is not an Agent Canvas workflow.",
                    stage="agent_canvas_execution_settings",
                ) from error
            raise
