"""Application services for Agent Canvas Decision Bundles."""

from __future__ import annotations

from app.persistence.agent_canvas_decision_bundle_repository import (
    AgentCanvasDecisionBundleRepository,
)
from app.schemas.agent_canvas_decision_bundles import DecisionBundleDraftV1, DecisionBundleV1


class DecisionBundleAuthoringService:
    """Publish one validated model-authored questionnaire without canvas mutation."""

    def __init__(self, repository: AgentCanvasDecisionBundleRepository) -> None:
        self._repository = repository

    def author(
        self,
        *,
        workflow_id: str,
        conversation_id: str,
        source_turn_id: str,
        draft: DecisionBundleDraftV1,
    ) -> DecisionBundleV1:
        return self._repository.publish(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            source_turn_id=source_turn_id,
            draft=DecisionBundleDraftV1.model_validate(draft),
        )
