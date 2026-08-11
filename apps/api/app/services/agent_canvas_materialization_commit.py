"""Canonical service boundary for one Agent Canvas materialization commit."""

from __future__ import annotations

from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationOutcomeV1,
    MaterializationPlanV1,
    materialization_plan_digest,
)
from app.services.agent_canvas_production_journey_reducer import (
    GuidedProductionJourneyReducer,
)


class AgentCanvasMaterializationCommitService:
    """Validate and commit one immutable materialization plan."""

    def __init__(
        self,
        repository: AgentCanvasMaterializationRepository,
        reducer: GuidedProductionJourneyReducer,
    ) -> None:
        self._repository = repository
        self._reducer = reducer

    def commit(self, plan: MaterializationPlanV1) -> MaterializationOutcomeV1:
        if materialization_plan_digest(plan) != plan.payload_digest:
            raise V2PersistenceError(
                "materialization_payload_invalid",
                "Materialization plan digest is invalid.",
                stage="materialization_commit",
            )
        return self._repository.commit(plan, reducer=self._reducer)

    def get_completed_outcome(
        self,
        materialization_id: str,
        action_turn_id: str,
    ) -> MaterializationOutcomeV1 | None:
        return self._repository.get_completed_outcome(materialization_id, action_turn_id)
