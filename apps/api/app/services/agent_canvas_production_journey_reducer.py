"""Pure reducer for committed fixed-journey materialization evidence."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationJourneyEventV1,
    StageMaterializedJourneyEventV1,
    TargetedActionCompletedJourneyEventV1,
)
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV2,
    JourneyElementDecisionV2,
    JourneyEvidenceV2,
)
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
)


class GuidedProductionJourneyReducer:
    """Reduce one committed event without accessing persistence or providers."""

    def __init__(
        self,
        policy: GuidedProductionJourneyPolicyService | None = None,
    ) -> None:
        self._policy = policy or GuidedProductionJourneyPolicyService()

    def reduce(
        self,
        current: GuidedProductionJourneyV2,
        event: MaterializationJourneyEventV1 | None,
        *,
        element_decisions: tuple[JourneyElementDecisionV2, ...] = (),
    ) -> GuidedProductionJourneyV2:
        if event is None:
            return current
        if any(item.evidence_id == event.evidence_id for item in current.transition_evidence):
            return current
        if current.stage == "completed":
            raise _error(
                "journey_terminal_conflict",
                "A terminal journey cannot accept materialization evidence.",
            )

        evidence = self._evidence(current, event)
        updated = self._policy.apply_evidence(
            current,
            evidence,
            recorded_at=event.recorded_at,
        )
        if (
            isinstance(event, StageMaterializedJourneyEventV1)
            and event.evidence_kind == "storyboard_plan_accepted"
        ):
            if not event.storyboard_draft_preparation_queued:
                raise _error(
                    "journey_evidence_invalid",
                    "Storyboard plan evidence requires queued Storyboard Grid Draft preparation.",
                )
            return updated.model_copy(update={"stage_status": "working"})
        return updated

    @staticmethod
    def _evidence(
        current: GuidedProductionJourneyV2,
        event: MaterializationJourneyEventV1,
    ) -> JourneyEvidenceV2:
        if isinstance(event, TargetedActionCompletedJourneyEventV1):
            return JourneyEvidenceV2(
                evidence_id=event.evidence_id,
                evidence_kind="targeted_action_finished",
                source_id=event.source_id,
                action_id=event.action_id,
                stage=current.stage,
                stage_revision=current.stage_revision,
            )
        if isinstance(event, StageMaterializedJourneyEventV1):
            action = current.active_action
            if (
                action is None
                or action.stage != current.stage
                or action.stage_revision != current.stage_revision
            ):
                raise _error(
                    "journey_stage_action_mismatch",
                    "Materialization evidence does not match the current stage action.",
                )
            return JourneyEvidenceV2(
                evidence_id=event.evidence_id,
                evidence_kind=event.evidence_kind,
                source_id=event.source_id,
                occurrence_id=event.occurrence_id,
                stage=current.stage,
                stage_revision=current.stage_revision,
            )
        raise _error(
            "journey_evidence_invalid",
            "Materialization journey event is unsupported.",
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="materialization_journey_reducer")
