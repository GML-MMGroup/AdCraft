"""Deterministic policy for the persisted Agent Canvas production journey."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV2,
    JourneyActionProjectionV2,
    JourneyElementDecisionV2,
    JourneyEvidenceV2,
    JourneyPolicyContextV2,
    JourneyPolicyResultV2,
    JourneyStageV2,
)


@dataclass(frozen=True, slots=True)
class FixedJourneyStageDescriptorV2:
    stage: JourneyStageV2
    successor: JourneyStageV2 | None
    capability_id: CapabilityIdV1 | None
    optional: bool
    element_kind: str | None
    evidence_kinds: tuple[str, ...]


FIXED_JOURNEY_STAGE_DESCRIPTORS: dict[JourneyStageV2, FixedJourneyStageDescriptorV2] = {
    "intake": FixedJourneyStageDescriptorV2(
        "intake",
        "world_view",
        None,
        False,
        None,
        ("creative_goal_validated", "clarification_completed"),
    ),
    "world_view": FixedJourneyStageDescriptorV2(
        "world_view",
        "product",
        "world_setting",
        True,
        "world_setting",
        ("world_view_selected", "world_view_delegated", "world_view_excluded"),
    ),
    "product": FixedJourneyStageDescriptorV2(
        "product",
        "props",
        "product_design",
        False,
        "product",
        ("product_materialized", "product_delegated"),
    ),
    "props": FixedJourneyStageDescriptorV2(
        "props",
        "character",
        "prop_design",
        True,
        "prop",
        ("props_materialized", "props_delegated", "props_excluded"),
    ),
    "character": FixedJourneyStageDescriptorV2(
        "character",
        "scene",
        "character_design",
        True,
        "character",
        ("character_materialized", "character_delegated", "character_excluded"),
    ),
    "scene": FixedJourneyStageDescriptorV2(
        "scene",
        "narrative_direction",
        "scene_design",
        False,
        "scene",
        ("scene_materialized", "scene_delegated"),
    ),
    "narrative_direction": FixedJourneyStageDescriptorV2(
        "narrative_direction",
        "style_lock",
        "script_authoring",
        False,
        "narrative_direction",
        ("narrative_direction_accepted",),
    ),
    "style_lock": FixedJourneyStageDescriptorV2(
        "style_lock",
        "storyboard_plan",
        "script_authoring",
        False,
        "style_lock",
        ("style_lock_accepted",),
    ),
    "storyboard_plan": FixedJourneyStageDescriptorV2(
        "storyboard_plan",
        "storyboard_grids",
        "script_authoring",
        False,
        "storyboard_plan",
        ("storyboard_plan_accepted",),
    ),
    "storyboard_grids": FixedJourneyStageDescriptorV2(
        "storyboard_grids",
        "videos",
        "storyboard_design",
        False,
        "storyboard",
        ("storyboard_grids_prepared",),
    ),
    "videos": FixedJourneyStageDescriptorV2(
        "videos",
        "bgm",
        "video_direction",
        False,
        "video",
        ("videos_prepared",),
    ),
    "bgm": FixedJourneyStageDescriptorV2(
        "bgm",
        "editing",
        "bgm_direction",
        True,
        "audio",
        ("bgm_prepared", "bgm_delegated", "bgm_excluded"),
    ),
    "editing": FixedJourneyStageDescriptorV2(
        "editing",
        "completed",
        None,
        False,
        None,
        ("editing_prepared", "editing_export_completed"),
    ),
    "completed": FixedJourneyStageDescriptorV2(
        "completed", None, None, False, None, ()
    ),
}


def initial_production_journey(
    decisions: tuple[CreativeElementDecisionV2, ...],
) -> GuidedProductionJourneyV2:
    """Create the clean-cut fixed journey without constructing hidden stage topology."""

    occurrences: list[JourneyElementDecisionV2] = []
    by_kind: dict[str, int] = {}
    for decision in decisions:
        count_value = decision.requirements.get("count", 1)
        count = (
            count_value
            if isinstance(count_value, int) and not isinstance(count_value, bool)
            else 1
        )
        count = min(max(count, 1), 32)
        for _ in range(count):
            occurrence_index = by_kind.get(decision.element_kind, 0) + 1
            by_kind[decision.element_kind] = occurrence_index
            occurrences.append(
                JourneyElementDecisionV2(
                    decision_id=f"decision:{decision.element_kind}:{occurrence_index}",
                    element_kind=decision.element_kind,
                    occurrence_id=f"occurrence:{decision.element_kind}:{occurrence_index}",
                    occurrence_index=occurrence_index,
                    outcome={
                        "include": "include",
                        "exclude": "exclude",
                        "unspecified": "unresolved",
                    }[decision.presence],
                    source=(
                        "delegated"
                        if decision.source == "delegated_to_agent"
                        else "user"
                    ),
                    source_revision=1,
                    requirements=decision.requirements,
                )
            )
    return GuidedProductionJourneyV2(decisions=tuple(occurrences))


def parse_production_journey(payload: str) -> GuidedProductionJourneyV2:
    """Read only the clean-cut journey policy from persisted JSON."""

    try:
        return GuidedProductionJourneyV2.model_validate_json(payload)
    except ValidationError as error:
        code = (
            "journey_policy_unsupported"
            if "fixed_ad_production_v1" in payload
            else "journey_state_invalid"
        )
        raise _error(code, "Persisted journey authority is not supported.") from error


class GuidedProductionJourneyPolicyService:
    """Apply the closed fixed-ad stage table without model or runtime dependencies."""

    def evaluate(
        self,
        context: JourneyPolicyContextV2 | GuidedProductionJourneyV2,
    ) -> JourneyPolicyResultV2:
        journey = context.journey if isinstance(context, JourneyPolicyContextV2) else context
        descriptor = FIXED_JOURNEY_STAGE_DESCRIPTORS[journey.stage]
        if journey.stage == "completed":
            return _result(journey, "complete")
        if journey.active_action is not None or journey.suspended_action is not None:
            return _result(journey, "wait_for_user")
        if journey.stage == "editing":
            return _result(journey, "prepare_editing")
        if descriptor.capability_id is None:
            return _result(journey, "wait_for_user")
        occurrence_id = journey.active_occurrence_id or self._next_occurrence(
            journey, descriptor
        )
        return _result(
            journey,
            "invoke_capability",
            capability_id=descriptor.capability_id,
            occurrence_id=occurrence_id,
        )

    def apply_evidence(
        self,
        context: JourneyPolicyContextV2 | GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
        *,
        recorded_at: datetime | None = None,
    ) -> GuidedProductionJourneyV2:
        journey = context.journey if isinstance(context, JourneyPolicyContextV2) else context
        if any(item.evidence_id == evidence.evidence_id for item in journey.transition_evidence):
            return journey
        self._require_current_evidence(journey, evidence)
        if evidence.evidence_kind == "stage_failed":
            return self._record_without_advancing(
                journey,
                evidence,
                recorded_at=recorded_at,
                stage_status="failed",
                active_action=None,
            )
        if evidence.evidence_kind == "targeted_action_started":
            return self._start_targeted_action(journey, evidence, recorded_at=recorded_at)
        if evidence.evidence_kind == "targeted_action_finished":
            return self._finish_targeted_action(journey, evidence, recorded_at=recorded_at)

        descriptor = FIXED_JOURNEY_STAGE_DESCRIPTORS[journey.stage]
        if evidence.evidence_kind not in descriptor.evidence_kinds:
            if str(evidence.evidence_kind).endswith("_excluded") and not descriptor.optional:
                raise _error(
                    "journey_stage_exclusion_not_allowed",
                    "The current fixed journey stage cannot be excluded.",
                )
            raise _error(
                "journey_stage_action_mismatch",
                "Journey evidence does not match the current stage.",
            )
        if descriptor.successor is None:
            raise _error("journey_stage_action_mismatch", "Journey stage cannot advance.")

        decisions = self._apply_occurrence_outcome(journey, evidence)
        if evidence.occurrence_id is not None and self._has_unresolved_occurrence(
            decisions, descriptor
        ):
            transition = evidence.as_transition(
                stage=journey.stage,
                stage_revision=journey.stage_revision,
                recorded_at=recorded_at,
            )
            return journey.model_copy(
                update={
                    "decisions": decisions,
                    "active_occurrence_id": self._next_occurrence_from(
                        decisions, descriptor
                    ),
                    "active_action": None,
                    "transition_evidence": (*journey.transition_evidence, transition),
                }
            )

        transition = evidence.as_transition(
            stage=journey.stage,
            stage_revision=journey.stage_revision,
            recorded_at=recorded_at,
        )
        return journey.model_copy(
            update={
                "stage": descriptor.successor,
                "stage_status": (
                    "completed" if descriptor.successor == "completed" else "ready"
                ),
                "stage_revision": journey.stage_revision + 1,
                "decisions": decisions,
                "active_occurrence_id": None,
                "active_action": None,
                "transition_evidence": (*journey.transition_evidence, transition),
            }
        )

    @staticmethod
    def _require_current_evidence(
        journey: GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
    ) -> None:
        if evidence.stage is not None and evidence.stage != journey.stage:
            raise _error("journey_stage_action_mismatch", "Evidence targets another stage.")
        if (
            evidence.stage_revision is not None
            and evidence.stage_revision != journey.stage_revision
        ):
            raise _error(
                "journey_stage_action_mismatch",
                "Evidence targets another stage revision.",
            )

    def _start_targeted_action(
        self,
        journey: GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
        *,
        recorded_at: datetime | None,
    ) -> GuidedProductionJourneyV2:
        if (
            evidence.action_id is None
            or journey.active_action is None
            or journey.suspended_action is not None
        ):
            raise _error("journey_action_in_progress", "A journey action cannot be suspended.")
        targeted = JourneyActionProjectionV2(
            action_id=evidence.action_id,
            action_kind="targeted_authoring",
            stage=journey.stage,
            stage_revision=journey.stage_revision,
            status="working",
            occurrence_id=evidence.occurrence_id,
        )
        return self._record_without_advancing(
            journey,
            evidence,
            recorded_at=recorded_at,
            active_action=targeted,
            suspended_action=journey.active_action,
        )

    def _finish_targeted_action(
        self,
        journey: GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
        *,
        recorded_at: datetime | None,
    ) -> GuidedProductionJourneyV2:
        if (
            journey.active_action is None
            or journey.active_action.action_id != evidence.action_id
            or journey.suspended_action is None
        ):
            raise _error("journey_stage_action_mismatch", "Targeted action evidence is stale.")
        return self._record_without_advancing(
            journey,
            evidence,
            recorded_at=recorded_at,
            active_action=journey.suspended_action,
            suspended_action=None,
        )

    @staticmethod
    def _record_without_advancing(
        journey: GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
        *,
        recorded_at: datetime | None,
        **updates: object,
    ) -> GuidedProductionJourneyV2:
        transition = evidence.as_transition(
            stage=journey.stage,
            stage_revision=journey.stage_revision,
            recorded_at=recorded_at,
        )
        return journey.model_copy(
            update={
                **updates,
                "transition_evidence": (*journey.transition_evidence, transition),
            }
        )

    @staticmethod
    def _apply_occurrence_outcome(
        journey: GuidedProductionJourneyV2,
        evidence: JourneyEvidenceV2,
    ) -> tuple[JourneyElementDecisionV2, ...]:
        if evidence.occurrence_id is None:
            return journey.decisions
        outcome = (
            "exclude"
            if str(evidence.evidence_kind).endswith("_excluded")
            else "delegate"
            if str(evidence.evidence_kind).endswith("_delegated")
            else "include"
        )
        found = False
        updated: list[JourneyElementDecisionV2] = []
        for decision in journey.decisions:
            if decision.occurrence_id == evidence.occurrence_id:
                found = True
                updated.append(decision.model_copy(update={"outcome": outcome}))
            else:
                updated.append(decision)
        if not found:
            raise _error(
                "journey_stage_action_mismatch",
                "Evidence targets an unknown journey occurrence.",
            )
        return tuple(updated)

    @staticmethod
    def _has_unresolved_occurrence(
        decisions: tuple[JourneyElementDecisionV2, ...],
        descriptor: FixedJourneyStageDescriptorV2,
    ) -> bool:
        return any(
            item.element_kind == descriptor.element_kind and item.outcome == "unresolved"
            for item in decisions
        )

    @staticmethod
    def _next_occurrence_from(
        decisions: tuple[JourneyElementDecisionV2, ...],
        descriptor: FixedJourneyStageDescriptorV2,
    ) -> str | None:
        return next(
            (
                item.occurrence_id
                for item in decisions
                if item.element_kind == descriptor.element_kind
                and item.outcome == "unresolved"
            ),
            None,
        )

    def _next_occurrence(
        self,
        journey: GuidedProductionJourneyV2,
        descriptor: FixedJourneyStageDescriptorV2,
    ) -> str | None:
        return self._next_occurrence_from(journey.decisions, descriptor)


def _result(
    journey: GuidedProductionJourneyV2,
    action: str,
    *,
    capability_id: CapabilityIdV1 | None = None,
    occurrence_id: str | None = None,
) -> JourneyPolicyResultV2:
    return JourneyPolicyResultV2.model_validate(
        {
            "action": action,
            "expected_stage_revision": journey.stage_revision,
            "capability_id": capability_id,
            "occurrence_id": occurrence_id,
            "requires_model_call": False,
        }
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_production_journey")
