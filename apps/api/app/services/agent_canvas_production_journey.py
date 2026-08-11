"""Deterministic policy for the persisted Agent Canvas production journey."""

from __future__ import annotations

from datetime import datetime

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2
from app.schemas.agent_canvas_production_journey import (
    FoundationJourneyItemV1,
    GuidedProductionJourneyV1,
    JourneyActionProjectionV1,
    JourneyEvidenceV1,
    JourneyPolicyContextV1,
    JourneyPolicyResultV1,
    JourneyStageV1,
)


_FOUNDATION_ORDER = ("product", "prop", "character", "scene")
_FOUNDATION_CAPABILITY: dict[str, CapabilityIdV1] = {
    "product": "product_design",
    "prop": "prop_design",
    "character": "character_design",
    "scene": "scene_design",
}
_STAGE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "intake": ("creative_goal_validated",),
    "clarification": ("clarification_completed",),
    "world_setting": (
        "world_setting_selected",
        "world_setting_deferred",
        "world_setting_excluded",
    ),
    "narrative_direction": ("narrative_direction_selected",),
    "style_lock": ("style_locked",),
    "storyboard_plan": ("storyboard_plan_accepted",),
    "storyboard_grids": ("storyboard_grids_prepared",),
    "video_segments": ("video_segments_prepared",),
    "bgm": ("bgm_prepared", "bgm_deferred", "bgm_excluded"),
    "editing_ready": ("editing_prepared",),
}


def build_foundation_queue(
    decisions: tuple[CreativeElementDecisionV2, ...],
) -> tuple[FoundationJourneyItemV1, ...]:
    by_kind = {decision.element_kind: decision for decision in decisions}
    result: list[FoundationJourneyItemV1] = []
    for kind in _FOUNDATION_ORDER:
        decision = by_kind.get(kind)
        if decision is None or decision.presence != "include":
            continue
        raw_count = decision.requirements.get("count", 1)
        count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) else 1
        count = min(max(count, 1), 32)
        source = "delegated" if decision.source == "delegated_to_agent" else "explicit_user"
        for occurrence_index in range(1, count + 1):
            result.append(
                FoundationJourneyItemV1(
                    item_id=f"foundation:{kind}:{occurrence_index}",
                    kind=kind,
                    occurrence_index=occurrence_index,
                    requirement_source=source,
                    required=decision.authority == "user",
                )
            )
    return tuple(result)


def initial_production_journey(
    decisions: tuple[CreativeElementDecisionV2, ...],
) -> GuidedProductionJourneyV1:
    return GuidedProductionJourneyV1(
        foundation_queue=build_foundation_queue(decisions),
    )


class GuidedProductionJourneyPolicyService:
    """Evaluate and apply one bounded deterministic journey transition."""

    def evaluate(self, context: JourneyPolicyContextV1) -> JourneyPolicyResultV1:
        journey = context.journey
        evidence = {
            *context.completed_evidence_kinds,
            *(item.evidence_kind for item in journey.transition_evidence),
        }
        if journey.active_action is not None:
            return self._result(journey, "wait_for_user")
        if journey.suspended_action is not None:
            return self._result(journey, "wait_for_user")
        if journey.stage == "completed":
            return self._result(journey, "complete")
        if journey.stage == "foundation_design":
            return self._foundation_action(journey)

        accepted = _STAGE_EVIDENCE.get(journey.stage, ())
        if any(item in evidence for item in accepted):
            return self._result(
                journey,
                "advance_stage",
                next_stage=self._next_stage(context),
            )
        return self._pending_action(context)

    def apply_evidence(
        self,
        context: JourneyPolicyContextV1,
        evidence: JourneyEvidenceV1,
        *,
        recorded_at: datetime | None = None,
    ) -> GuidedProductionJourneyV1:
        journey = context.journey
        if any(item.evidence_id == evidence.evidence_id for item in journey.transition_evidence):
            return journey
        if evidence.evidence_kind == "stage_failed":
            return journey.model_copy(
                update={
                    "stage_status": "failed",
                    "active_action": None,
                    "transition_evidence": (
                        *journey.transition_evidence,
                        evidence.as_transition(recorded_at=recorded_at),
                    ),
                }
            )
        if evidence.evidence_kind == "targeted_action_started":
            if journey.suspended_action is not None or evidence.action_id is None:
                raise _error("journey_action_in_progress", "A journey action is already active.")
            return journey.model_copy(
                update={
                    "suspended_action": JourneyActionProjectionV1(
                        action_id=evidence.action_id,
                        action_kind="targeted_authoring",
                        stage=journey.stage,
                        status="working",
                    ),
                    "transition_evidence": (
                        *journey.transition_evidence,
                        evidence.as_transition(recorded_at=recorded_at),
                    ),
                }
            )
        if evidence.evidence_kind == "targeted_action_finished":
            if (
                journey.suspended_action is None
                or evidence.action_id != journey.suspended_action.action_id
            ):
                raise _error("journey_evidence_invalid", "Targeted action evidence is stale.")
            return journey.model_copy(
                update={
                    "suspended_action": None,
                    "transition_evidence": (
                        *journey.transition_evidence,
                        evidence.as_transition(recorded_at=recorded_at),
                    ),
                }
            )
        if journey.stage == "foundation_design":
            return self._apply_foundation_evidence(
                context,
                evidence,
                recorded_at=recorded_at,
            )

        allowed = _STAGE_EVIDENCE.get(journey.stage, ())
        if evidence.evidence_kind not in allowed:
            raise _error(
                "journey_transition_invalid",
                "Journey evidence does not match the current stage.",
            )
        next_context = context.model_copy(
            update={
                "journey": journey.model_copy(update={"active_action": None}),
                "completed_evidence_kinds": (
                    *context.completed_evidence_kinds,
                    evidence.evidence_kind,
                ),
            }
        )
        result = self.evaluate(next_context)
        if result.action != "advance_stage" or result.next_stage is None:
            raise _error("journey_transition_invalid", "Journey cannot advance.")
        return self._advance(
            journey,
            result.next_stage,
            evidence,
            recorded_at=recorded_at,
        )

    def _apply_foundation_evidence(
        self,
        context: JourneyPolicyContextV1,
        evidence: JourneyEvidenceV1,
        *,
        recorded_at: datetime | None,
    ) -> GuidedProductionJourneyV1:
        status_by_kind = {
            "foundation_item_selected": "selected",
            "foundation_item_deferred": "deferred",
            "foundation_item_excluded": "excluded",
        }
        status = status_by_kind.get(evidence.evidence_kind)
        journey = context.journey
        cursor = journey.foundation_cursor
        if status is None or cursor is None or evidence.foundation_item_id is None:
            raise _error("journey_transition_invalid", "Foundation evidence is invalid.")
        current = journey.foundation_queue[cursor]
        if current.item_id != evidence.foundation_item_id:
            raise _error("journey_evidence_invalid", "Foundation evidence targets another item.")
        queue = list(journey.foundation_queue)
        queue[cursor] = current.model_copy(update={"status": status})
        next_cursor = next(
            (index for index in range(cursor + 1, len(queue)) if queue[index].status == "pending"),
            None,
        )
        transition = evidence.as_transition(recorded_at=recorded_at)
        if next_cursor is not None:
            queue[next_cursor] = queue[next_cursor].model_copy(update={"status": "active"})
            return journey.model_copy(
                update={
                    "foundation_queue": tuple(queue),
                    "foundation_cursor": next_cursor,
                    "active_action": None,
                    "transition_evidence": (*journey.transition_evidence, transition),
                }
            )
        advanced = journey.model_copy(
            update={"foundation_queue": tuple(queue), "foundation_cursor": None}
        )
        return self._advance(
            advanced,
            "narrative_direction",
            evidence,
            recorded_at=recorded_at,
        )

    def _next_stage(self, context: JourneyPolicyContextV1) -> JourneyStageV1:
        stage = context.journey.stage
        decisions = {item.element_kind: item.presence for item in context.element_decisions}
        if stage == "intake":
            if context.clarification_required:
                return "clarification"
            return self._first_included_stage(context)
        if stage == "clarification":
            return self._first_included_stage(context)
        if stage == "world_setting":
            return (
                "foundation_design" if context.journey.foundation_queue else "narrative_direction"
            )
        if stage == "narrative_direction":
            return "style_lock"
        if stage == "style_lock":
            return "storyboard_plan"
        if stage == "storyboard_plan":
            return "storyboard_grids"
        if stage == "storyboard_grids":
            return "video_segments"
        if stage == "video_segments":
            return "bgm" if decisions.get("audio") == "include" else "editing_ready"
        if stage == "bgm":
            return "editing_ready"
        if stage == "editing_ready":
            return "completed"
        raise _error("journey_transition_invalid", "Journey stage cannot advance.")

    def _first_included_stage(self, context: JourneyPolicyContextV1) -> JourneyStageV1:
        decisions = {item.element_kind: item.presence for item in context.element_decisions}
        if decisions.get("world_setting") == "include":
            return "world_setting"
        if context.journey.foundation_queue:
            return "foundation_design"
        return "narrative_direction"

    def _foundation_action(
        self,
        journey: GuidedProductionJourneyV1,
    ) -> JourneyPolicyResultV1:
        cursor = journey.foundation_cursor
        if cursor is None:
            cursor = next(
                (
                    index
                    for index, item in enumerate(journey.foundation_queue)
                    if item.status == "pending"
                ),
                None,
            )
        if cursor is None:
            return self._result(journey, "advance_stage", next_stage="narrative_direction")
        item = journey.foundation_queue[cursor]
        return self._result(
            journey,
            "invoke_capability",
            capability_id=_FOUNDATION_CAPABILITY[item.kind],
            foundation_item_id=item.item_id,
        )

    def _pending_action(self, context: JourneyPolicyContextV1) -> JourneyPolicyResultV1:
        capability_by_stage: dict[str, CapabilityIdV1] = {
            "world_setting": "world_setting",
            "narrative_direction": "script_authoring",
            "storyboard_plan": "storyboard_design",
            "bgm": "bgm_direction",
        }
        if context.journey.stage == "editing_ready":
            return self._result(context.journey, "prepare_editing")
        capability = capability_by_stage.get(context.journey.stage)
        if capability is not None:
            return self._result(
                context.journey,
                "invoke_capability",
                capability_id=capability,
            )
        return self._result(context.journey, "wait_for_user")

    @staticmethod
    def _advance(
        journey: GuidedProductionJourneyV1,
        next_stage: JourneyStageV1,
        evidence: JourneyEvidenceV1,
        *,
        recorded_at: datetime | None = None,
    ) -> GuidedProductionJourneyV1:
        queue = journey.foundation_queue
        cursor = journey.foundation_cursor
        if next_stage == "foundation_design" and queue:
            cursor = next(
                (index for index, item in enumerate(queue) if item.status == "pending"),
                None,
            )
            if cursor is not None:
                mutable = list(queue)
                mutable[cursor] = mutable[cursor].model_copy(update={"status": "active"})
                queue = tuple(mutable)
        return journey.model_copy(
            update={
                "stage": next_stage,
                "stage_status": "completed" if next_stage == "completed" else "ready",
                "stage_revision": journey.stage_revision + 1,
                "foundation_queue": queue,
                "foundation_cursor": cursor,
                "active_action": None,
                "transition_evidence": (
                    *journey.transition_evidence,
                    evidence.as_transition(recorded_at=recorded_at),
                ),
            }
        )

    @staticmethod
    def _result(
        journey: GuidedProductionJourneyV1,
        action: str,
        *,
        next_stage: JourneyStageV1 | None = None,
        capability_id: CapabilityIdV1 | None = None,
        foundation_item_id: str | None = None,
    ) -> JourneyPolicyResultV1:
        return JourneyPolicyResultV1.model_validate(
            {
                "action": action,
                "expected_stage_revision": journey.stage_revision,
                "next_stage": next_stage,
                "capability_id": capability_id,
                "foundation_item_id": foundation_item_id,
                "requires_model_call": False,
            }
        )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_production_journey")
