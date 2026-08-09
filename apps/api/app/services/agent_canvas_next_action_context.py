"""SQLite-authoritative capability policy context assembly."""

from __future__ import annotations

from app.schemas.agent_canvas import AgentCanvasWorkflowV2
from app.schemas.agent_canvas_capabilities import CapabilityPolicyContextV1
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.services.agent_canvas_capability_policy import (
    derive_capability_requirement_facts,
)


_ROLE_CAPABILITIES: dict[str, CapabilityIdV1] = {
    "world_setting": "world_setting",
    "product": "product_design",
    "prop": "prop_design",
    "character": "character_design",
    "scene": "scene_design",
    "script": "script_authoring",
    "storyboard_sequence": "storyboard_design",
    "storyboard_video": "video_direction",
    "bgm": "bgm_direction",
}


def assemble_capability_policy_context(
    *,
    workflow: AgentCanvasWorkflowV2,
    session: GuidedSessionStateV2,
    open_proposal_capabilities: tuple[CapabilityIdV1, ...] = (),
    active_materialization_capabilities: tuple[CapabilityIdV1, ...] = (),
    targeted_capability: CapabilityIdV1 | None = None,
    is_new_guided_production: bool = False,
) -> CapabilityPolicyContextV1:
    """Derive policy facts from canonical Nodes, session decisions, and topics."""

    completed = tuple(
        dict.fromkeys(
            _ROLE_CAPABILITIES[node.creative_role]
            for node in workflow.nodes
            if node.creative_role in _ROLE_CAPABILITIES
        )
    )
    requirements = derive_capability_requirement_facts(session.element_decisions)
    deferred = tuple(
        dict.fromkeys(topic.capability_id for topic in session.topics if topic.status == "deferred")
    )
    topic_excluded = tuple(
        dict.fromkeys(topic.capability_id for topic in session.topics if topic.status == "excluded")
    )
    excluded = tuple(dict.fromkeys((*requirements.excluded, *topic_excluded)))
    return CapabilityPolicyContextV1(
        is_new_guided_production=is_new_guided_production,
        world_setting_selected="world_setting" in completed,
        targeted_capability=targeted_capability,
        completed_capabilities=completed,
        excluded_capabilities=excluded,
        open_proposal_capabilities=tuple(dict.fromkeys(open_proposal_capabilities)),
        active_materialization_capabilities=tuple(
            dict.fromkeys(active_materialization_capabilities)
        ),
        deferred_capabilities=deferred,
        required_capabilities=requirements.required,
    )
