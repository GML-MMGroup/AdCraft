"""Canonical Specialist ownership for progressive Guidance topics."""

from __future__ import annotations

from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_creative_session import (
    AgentCanvasSpecialistNameV2,
    GuidanceTopicKindV2,
    NextGuidanceDecisionV2,
)
from app.schemas.agent_operation_contexts import GuidanceTopicOwnershipV2


TOPIC_SPECIALIST: dict[GuidanceTopicKindV2, AgentCanvasSpecialistNameV2] = {
    "creative_direction": "script_writer",
    "product": "product_designer",
    "prop": "prop_designer",
    "character": "character_designer",
    "scene": "scene_designer",
    "script": "script_writer",
    "storyboard": "storyboard_artist",
    "video": "video_director",
    "audio": "bgm_director",
}


@dataclass(frozen=True, slots=True)
class GuidanceOwnerResolution:
    decision: NextGuidanceDecisionV2
    supplied_specialist_name: AgentCanvasSpecialistNameV2 | None
    resolved_specialist_name: AgentCanvasSpecialistNameV2 | None
    corrected: bool


class GuidanceOwnerResolver:
    """Replace model-supplied ownership with deterministic platform policy."""

    def resolve(self, decision: NextGuidanceDecisionV2) -> GuidanceOwnerResolution:
        if decision.action != "propose_topic":
            return GuidanceOwnerResolution(decision, None, None, False)
        expected = TOPIC_SPECIALIST.get(decision.topic_kind)
        if expected is None:
            raise V2PersistenceError(
                "guidance_decision_invalid",
                "The proposed topic has no registered Specialist owner.",
                stage="guidance_owner_resolver",
            )
        supplied = decision.specialist_name
        canonical = decision.model_copy(update={"specialist_name": expected})
        return GuidanceOwnerResolution(
            canonical,
            supplied,
            expected,
            supplied != expected,
        )


def topic_ownership_projection() -> tuple[GuidanceTopicOwnershipV2, ...]:
    """Return the complete bounded ownership projection in registry order."""

    return tuple(
        GuidanceTopicOwnershipV2(
            topic_kind=topic_kind,
            specialist_name=specialist_name,
        )
        for topic_kind, specialist_name in TOPIC_SPECIALIST.items()
    )
