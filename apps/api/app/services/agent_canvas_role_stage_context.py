"""Select storyboard/video guidance by the target, using immutable style authority."""

from collections.abc import Callable

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_creative_session import CreativeDirectionSnapshotV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_stage_authoring_context import combined_style_guidance


StyleSnapshotLoader = Callable[[str], CreativeDirectionSnapshotV2]
_TARGET_GUIDANCE = {
    "storyboard_grid": ("storyboard", "agent/skills/video_agent_storyboard_design/SKILL.md"),
    "video_segment": ("video", "agent/skills/video_agent_video_direction/SKILL.md"),
}


def scope_role_stage_context(
    context: StageAuthoringContextV1,
    role_variant: str,
    *,
    snapshot_loader: StyleSnapshotLoader | None = None,
) -> StageAuthoringContextV1:
    """Never pass image-only advice through to a Video authoring operation."""
    target = _TARGET_GUIDANCE.get(role_variant)
    if target is None:
        return context
    role, skill_ref = target
    guidance = context.style_guidance
    if context.internal_skill_ref == skill_ref and (guidance is None or guidance.role == role):
        return context
    snapshot_id = context.style_snapshot_id or (
        guidance.creative_direction_snapshot_id if guidance is not None else None
    )
    if snapshot_id is not None and snapshot_loader is not None:
        snapshot = snapshot_loader(snapshot_id)
        if snapshot.snapshot_id != snapshot_id or snapshot.workflow_id != context.workflow_id:
            raise V2PersistenceError(
                "node_prompt_context_stale",
                "Role guidance does not belong to the frozen Workflow style snapshot.",
                stage="node_prompt_preparation",
            )
        guidance = CreativeDirectionService().resolve_style_context(snapshot, role)
    elif guidance is not None and guidance.role != role:
        guidance = guidance.model_copy(
            update={"role": role, "role_guidance": None, "role_guidance_digest": None}
        )
    return context.model_copy(
        update={
            "internal_skill_ref": skill_ref,
            "style_guidance": guidance,
            "style_projection": combined_style_guidance(guidance.model_dump())
            if guidance
            else None,
        }
    )
