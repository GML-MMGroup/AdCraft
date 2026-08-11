"""Isolated deterministic preparation for one visible Agent Canvas Draft."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    CharacterDesignAssetContentV2,
    DesignAssetContentV2,
    SceneBoardPanelV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VideoSegmentContentV2,
    VisualStyleContractV2,
)
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingCoreV2,
    WorldSettingDocumentV2,
)


RolePromptAuthor = Callable[
    [CanvasNodeV2, StageAuthoringContextV1],
    tuple[str, dict[str, object]],
]


class NodePromptPreparationService:
    """Prepare one Draft without invoking media execution or copying sibling prompts."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        *,
        role_prompt_author: RolePromptAuthor | None = None,
    ) -> None:
        self._workflows = workflows
        self._role_prompt_author = role_prompt_author

    def prepare(
        self,
        workflow_id: str,
        node_id: str,
        *,
        operation_id: str,
        context: StageAuthoringContextV1,
    ) -> CanvasNodeV2:
        current = self._workflows.get_node(workflow_id, node_id)
        if (
            current.prompt_preparation.status == "ready"
            and current.prompt_preparation.operation_id == operation_id
        ):
            return current
        snapshot_digest = context_digest(context)
        working = self._transition(
            current,
            NodePromptPreparationV1(
                status="working",
                operation_id=operation_id,
                attempt_no=current.prompt_preparation.attempt_no + 1,
                context_snapshot_id=snapshot_digest,
                updated_at=_now(),
            ),
        )
        try:
            compiled = _compile_deterministic(working, context)
            if compiled is None:
                if self._role_prompt_author is None:
                    raise ValueError("stage_content_mismatch")
                compiled = self._role_prompt_author(working, context)
            prompt, structured_content = compiled
            digest = sha256(prompt.encode("utf-8")).hexdigest()
            ready = working.model_copy(
                update={
                    "generation_prompt": prompt,
                    "structured_content": structured_content,
                    "status": "ready" if working.node_type == "text" else working.status,
                    "metadata": {
                        **working.metadata,
                        "prompt_context_digest": snapshot_digest,
                        "prompt_digest": digest,
                    },
                    "revision": working.revision + 1,
                    "updated_at": _now(),
                    "prompt_preparation": NodePromptPreparationV1(
                        status="ready",
                        operation_id=operation_id,
                        attempt_no=working.prompt_preparation.attempt_no,
                        context_snapshot_id=snapshot_digest,
                        prompt_digest=digest,
                        updated_at=_now(),
                    ),
                }
            )
            return self._persist(working, ready)
        except Exception as error:
            failed = working.model_copy(
                update={
                    "revision": working.revision + 1,
                    "updated_at": _now(),
                    "prompt_preparation": NodePromptPreparationV1(
                        status="failed",
                        operation_id=operation_id,
                        attempt_no=working.prompt_preparation.attempt_no,
                        context_snapshot_id=snapshot_digest,
                        error=CanvasNodeErrorV2(
                            code="prompt_preparation_failed",
                            message="Node prompt preparation failed.",
                            retryable=True,
                        ),
                        updated_at=_now(),
                    ),
                }
            )
            self._persist(working, failed)
            raise error

    def _transition(
        self,
        current: CanvasNodeV2,
        preparation: NodePromptPreparationV1,
    ) -> CanvasNodeV2:
        next_node = current.model_copy(
            update={
                "revision": current.revision + 1,
                "updated_at": _now(),
                "prompt_preparation": preparation,
            }
        )
        return self._persist(current, next_node)

    def _persist(self, current: CanvasNodeV2, next_node: CanvasNodeV2) -> CanvasNodeV2:
        workflow = self._workflows.get_workflow(current.workflow_id)
        return self._workflows.update_node_prompt_preparation(
            next_node,
            expected_node_revision=current.revision,
            expected_workflow_revision=workflow.revision,
        )


def _compile_deterministic(
    node: CanvasNodeV2,
    context: StageAuthoringContextV1,
) -> tuple[str, dict[str, object]] | None:
    selected = context.selected_concept
    summary = (node.summary_prompt or (selected.public_summary if selected else "")).strip()
    decisions = " ".join(selected.key_decisions if selected else ())
    style = _style(context)
    base = f"{summary} {decisions}".strip()
    if node.creative_role in {"product", "prop"}:
        kind = str(node.structured_content.get("asset_kind", "main"))
        prompt = f"Create one {kind.replace('_', ' ')} advertising design asset. {base}"
        return prompt, DesignAssetContentV2(
            subject_identity=summary,
            design_summary=base,
            style=style,
            negative_constraints=("text", "labels", "watermarks"),
        ).model_dump(mode="json")
    if node.creative_role == "character":
        kind = str(node.structured_content.get("character_asset_kind", "identity_master"))
        safety = (
            "Detailed semi-realistic advertising illustration, recognizable facial and wardrobe "
            "identity, clean neutral background, no labels, captions, typography, watermarks, "
            "or layout annotations, not a photograph and not photorealistic."
        )
        if kind == "turnaround":
            safety += (
                " Use the required Character Main reference to preserve the same identity, face, "
                "hairstyle, wardrobe, palette, proportions, and style in front, side, and back views."
            )
        prompt = f"{safety} {base}"
        return prompt, CharacterDesignAssetContentV2(
            subject_identity=summary,
            design_summary=base,
            style=style,
            negative_constraints=("photorealistic human", "text", "identity drift"),
            character_asset_kind=kind,
        ).model_dump(mode="json")
    if node.creative_role == "scene":
        panels = tuple(
            SceneBoardPanelV2(
                panel_index=index,
                view_or_zone=f"Environment view {index}",
                spatial_description=f"Distinct spatial study {index} for {summary}",
                lighting_material_detail=f"Consistent lighting and material study {index}",
            )
            for index in range(1, 10)
        )
        prompt = f"Create one text-free 3x3 environment reference board. {base}"
        return prompt, SceneDesignBoardContentV2(
            scene_identity=summary,
            environment_summary=base,
            layout="Nine distinct views of one coherent environment.",
            lighting="Consistent commercial lighting across every view.",
            materials="Preserve the accepted material palette across every view.",
            time_of_day="Use the accepted narrative time of day.",
            style=style,
            panels=panels,
        ).model_dump(mode="json")
    if node.creative_role == "script":
        content = (
            f"Narrative direction: {summary}\n\n"
            f"Scene progression and product moments: {decisions}\n\n"
            "Develop editable action, dialogue or voiceover, product moments, and intended "
            "timing. Keep detailed shot composition and rendering instructions for later stages."
        )
        return content, {"content": content}
    if node.creative_role == "storyboard_sequence":
        panels = tuple(
            StoryboardPanelV2(
                panel_index=index,
                beat=f"Narrative beat {index}: {summary}",
                composition=f"Distinct composition {index}",
                camera=f"Camera setup {index}",
                subject_action=f"Ordered action {index}",
                continuity_from_previous=(
                    "Opening state" if index == 1 else f"Continue from panel {index - 1}"
                ),
            )
            for index in range(1, 10)
        )
        prompt = f"Create one text-free 3x3 storyboard grid with panels 1 through 9. {base}"
        return prompt, StoryboardGridContentV2(
            sequence_summary=summary,
            narrative_goal=decisions,
            style=style,
            panels=panels,
        ).model_dump(mode="json")
    if node.creative_role == "storyboard_video":
        duration = min(15.0, float(node.parameters.get("duration_seconds", 5)))
        prompt = (
            "Use the complete bound storyboard grid as the primary ordered reference. Lock the "
            "opening frame to panel 1 and follow panels 1 through 9. Preserve dialogue, voice "
            "style, ambience, and action effects; generate no background music. " + base
        )
        return prompt, VideoSegmentContentV2(
            segment_summary=summary,
            duration_seconds=duration,
            storyboard_content="Follow the complete matching grid from panel 1 through panel 9.",
            dialogue="Use only dialogue required by the accepted narrative.",
            voice_style="Preserve the accepted performance direction.",
            environment_sound="Use scene-consistent ambience.",
            action_effects="Use synchronized product and movement effects.",
            negative_constraints="No background music and no identity drift.",
        ).model_dump(mode="json")
    if node.creative_role == "bgm":
        duration = float(node.parameters.get("duration_seconds", 30))
        prompt = f"Create instrumental-only advertising music with no vocals or lyrics. {base}"
        return prompt, BgmContentV2(
            music_summary=summary,
            duration_seconds=duration,
            pace="Follow the accepted narrative pace.",
            energy_curve="Build and resolve with the advertisement structure.",
            instrumentation="Instrumental commercial arrangement.",
            mood=decisions,
        ).model_dump(mode="json")
    if node.creative_role in {"general_image", "general_video", "general_audio"}:
        media_kind = node.creative_role.removeprefix("general_")
        prompt = f"Create one focused {media_kind} asset. {base}"
        return prompt, dict(node.structured_content)
    if node.creative_role == "world_setting":
        content = f"{summary}\n\nWorld rules and visual continuity: {decisions}"
        rules = tuple(selected.key_decisions if selected else ())
        return content, WorldSettingDocumentV2(
            content=content,
            core=WorldSettingCoreV2(
                premise=summary,
                era_and_place=(rules[0] if rules else summary),
                world_rules=rules,
                visual_continuity=rules,
            ),
            authoring_provenance=WorldSettingAuthoringProvenanceV2(
                source_proposal_id=str(
                    node.parameters.get("source_proposal_id") or "progressive-authoring"
                ),
                source_option_id=str(
                    node.parameters.get("source_option_id")
                    or (selected.option_id if selected else "selected-concept")
                ),
                materialization_run_id=(
                    node.prompt_preparation.operation_id or "prompt-preparation"
                ),
            ),
        ).model_dump(mode="json")
    return None


def _style(context: StageAuthoringContextV1) -> VisualStyleContractV2:
    if context.style_projection:
        return VisualStyleContractV2(
            style_prompt=context.style_projection,
            source="video_skill",
        )
    return VisualStyleContractV2(
        style_prompt="Detailed semi-realistic advertising illustration",
        source="platform_default",
    )


def context_digest(context: StageAuthoringContextV1) -> str:
    payload = json.dumps(
        context.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)
