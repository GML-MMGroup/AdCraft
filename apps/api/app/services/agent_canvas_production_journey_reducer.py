"""Pure journey reduction for one Agent Canvas materialization commit."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationJourneyEventV1,
    StageMaterializedJourneyEventV1,
    TargetedActionCompletedJourneyEventV1,
)
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV1,
    JourneyElementDecisionV1,
    JourneyEvidenceV1,
    JourneyPolicyContextV1,
)
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
)


class GuidedProductionJourneyReducer:
    """Return the deterministic journey produced by a materialization event."""

    def __init__(self, policy: GuidedProductionJourneyPolicyService | None = None) -> None:
        self._policy = policy or GuidedProductionJourneyPolicyService()

    def reduce(
        self,
        current: GuidedProductionJourneyV1,
        event: MaterializationJourneyEventV1 | None,
        *,
        element_decisions: tuple[JourneyElementDecisionV1, ...] = (),
    ) -> GuidedProductionJourneyV1:
        if event is None:
            return current
        if any(
            evidence.evidence_id == event.evidence_id for evidence in current.transition_evidence
        ):
            return current
        if current.stage == "completed":
            raise _error(
                "journey_transition_invalid",
                "A terminal journey cannot accept materialization evidence.",
            )

        evidence = self._evidence(current, event)
        updated = self._policy.apply_evidence(
            JourneyPolicyContextV1(
                journey=current,
                element_decisions=element_decisions,
            ),
            evidence,
            recorded_at=event.recorded_at,
        )
        if isinstance(event, StageMaterializedJourneyEventV1) and (
            event.evidence_kind == "storyboard_plan_accepted"
        ):
            if not event.runnable_storyboard_draft:
                raise _error(
                    "journey_evidence_invalid",
                    "Storyboard plan evidence requires a runnable Storyboard Grid Draft.",
                )
            return updated.model_copy(update={"stage_status": "waiting_user"})
        return updated

    @staticmethod
    def _evidence(
        current: GuidedProductionJourneyV1,
        event: MaterializationJourneyEventV1,
    ) -> JourneyEvidenceV1:
        if isinstance(event, TargetedActionCompletedJourneyEventV1):
            return JourneyEvidenceV1(
                evidence_id=event.evidence_id,
                evidence_kind="targeted_action_finished",
                source_id=event.source_id,
                action_id=event.action_id,
            )

        if isinstance(event, StageMaterializedJourneyEventV1):
            action = current.active_action
            if action is None or action.stage != current.stage:
                raise _error(
                    "journey_evidence_invalid",
                    "Materialization evidence does not match the current stage action.",
                )
            if (
                current.stage == "foundation_design"
                and action.foundation_item_id != event.foundation_item_id
            ):
                raise _error(
                    "journey_evidence_invalid",
                    "Foundation evidence targets another item.",
                )
            return JourneyEvidenceV1(
                evidence_id=event.evidence_id,
                evidence_kind=event.evidence_kind,
                source_id=event.source_id,
                foundation_item_id=event.foundation_item_id,
            )

        raise _error(
            "journey_evidence_invalid",
            "Materialization journey event is unsupported.",
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="materialization_journey_reducer")
