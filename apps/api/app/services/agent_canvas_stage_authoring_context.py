"""Bound one capability Materialization context to one authoring stage."""

from __future__ import annotations

from app.schemas.agent_canvas_conversation import ConceptOptionRecordV2
from app.schemas.agent_canvas_creative_session import CreativeGoalV2, ProposedDraftReferenceV2
from app.schemas.agent_canvas_materialization import CapabilityMaterializationContextV1
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1


_SKILL_REFS = {
    "world_setting": "agent/skills/video_agent_world_setting/SKILL.md",
    "product_design": "agent/skills/video_agent_product_design/SKILL.md",
    "prop_design": "agent/skills/video_agent_prop_design/SKILL.md",
    "character_design": "agent/skills/video_agent_character_design/SKILL.md",
    "scene_design": "agent/skills/video_agent_scene_design/SKILL.md",
    "script_authoring": "agent/skills/video_agent_script_authoring/SKILL.md",
    "storyboard_design": "agent/skills/video_agent_storyboard_design/SKILL.md",
    "video_direction": "agent/skills/video_agent_video_direction/SKILL.md",
    "bgm_direction": "agent/skills/video_agent_bgm_direction/SKILL.md",
    "quick_media": "agent/skills/video_agent_quick_media/SKILL.md",
}

_OUTPUT_KINDS = {
    "world_setting": "text",
    "script_authoring": "script",
    "product_design": "image",
    "prop_design": "image",
    "character_design": "image",
    "scene_design": "image",
    "storyboard_design": "image",
    "video_direction": "video",
    "bgm_direction": "audio",
    "quick_media": "image",
}


def stage_authoring_context_from_materialization(
    context: CapabilityMaterializationContextV1,
    *,
    session_id: str,
    session_revision: int,
    stage: JourneyStageV2,
    occurrence_id: str | None,
    references: tuple[ProposedDraftReferenceV2, ...],
) -> StageAuthoringContextV1:
    """Drop private capability context fields before preparing one visible Draft."""

    style = context.style_projection
    style_projection = next(
        (
            value.strip()
            for key in ("role_guidance", "global_guidance", "summary")
            if isinstance((value := style.get(key)), str) and value.strip()
        ),
        None,
    )
    style_snapshot_id = style.get("creative_direction_snapshot_id")
    if not isinstance(style_snapshot_id, str) or not style_snapshot_id.strip():
        style_snapshot_id = None
    selected = context.selected_option
    return StageAuthoringContextV1(
        workflow_id=context.workflow_id,
        session_id=session_id,
        session_revision=session_revision,
        stage=stage,
        occurrence_id=occurrence_id,
        creative_goal=CreativeGoalV2(
            requested_output=_OUTPUT_KINDS[context.capability_id],
            delivery_scope="draft",
            summary=context.creative_goal,
            explicit_constraints=context.explicit_constraints,
        ),
        requirement_facts={
            **context.explicit_constraints,
            **context.capability_facts,
        },
        selected_concept=ConceptOptionRecordV2(
            option_id=selected.option_id,
            title=selected.title,
            public_summary=selected.public_summary,
            key_decisions=tuple(getattr(selected, "key_decisions", ())),
        ),
        style_snapshot_id=style_snapshot_id,
        internal_skill_ref=_SKILL_REFS[context.capability_id],
        style_projection=style_projection,
        video_representation_mode=(
            style.get("video_representation_mode")
            if style.get("video_representation_mode")
            in {
                "illustrated",
                "illustration_to_live_action",
            }
            else None
        ),
        video_representation_source_id=(
            style.get("video_representation_source_id")
            if isinstance(style.get("video_representation_source_id"), str)
            else None
        ),
        references=references,
    )
