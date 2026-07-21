from hashlib import sha256
from typing import Any

from app.schemas.workflow_v2 import (
    WorkflowEdgeV2,
    WorkflowItemV2,
    WorkflowNodeV2,
    WorkflowSlotV2,
    WorkflowV2PlanFromPromptRequest,
)
from app.schemas.workflow_v2_planning import (
    V2BgmBrief,
    V2CharacterBrief,
    V2ExpertBriefPlan,
    V2ProductBrief,
    V2SceneBrief,
    V2ScriptPlan,
)
from app.services.v2_item_identity_specs import (
    V2ItemIdentitySpecBuilder,
    identity_metadata,
    render_identity_slot_prompt,
    slot_identity_metadata,
)


DEFAULT_V2_NODE_IDS = (
    "script",
    "product-generation",
    "character-generation",
    "scene-generation",
    "bgm",
    "storyboard",
    "final-composition",
)

DISPLAY_EDGES = (
    ("script", "product-generation"),
    ("script", "character-generation"),
    ("script", "scene-generation"),
    ("script", "bgm"),
    ("product-generation", "storyboard"),
    ("character-generation", "storyboard"),
    ("scene-generation", "storyboard"),
    ("storyboard", "final-composition"),
    ("bgm", "final-composition"),
)


class V2WorkflowPlanner:
    def build_default_nodes(
        self,
        workflow_id: str,
        request: WorkflowV2PlanFromPromptRequest,
        script_plan: V2ScriptPlan,
        expert_brief_plan: V2ExpertBriefPlan,
    ) -> list[WorkflowNodeV2]:
        return build_default_nodes(workflow_id, request, script_plan, expert_brief_plan)

    def build_display_edges(self, workflow_id: str) -> list[WorkflowEdgeV2]:
        return build_display_edges(workflow_id)


def build_default_nodes(
    workflow_id: str,
    request: WorkflowV2PlanFromPromptRequest,
    script_plan: V2ScriptPlan,
    expert_brief_plan: V2ExpertBriefPlan,
) -> list[WorkflowNodeV2]:
    product_items = [product_item(brief, script_plan) for brief in expert_brief_plan.product_briefs]
    character_items = [
        character_item(brief, script_plan) for brief in expert_brief_plan.character_briefs
    ]
    character_not_applicable = not character_items
    scene_items = [scene_item(brief, script_plan) for brief in expert_brief_plan.scene_briefs]
    return [
        WorkflowNodeV2(
            node_id="script",
            node_type="script",
            title="Script",
            status="completed",
            position={"x": 0, "y": 0},
            items=[
                WorkflowItemV2(
                    item_id="script-1",
                    node_id="script",
                    item_type="script",
                    display_name="Script",
                    description=script_plan.script_title,
                    item_prompt=(
                        f"{script_plan.script_title}. Tone: {script_plan.tone}. "
                        f"Scenes: {len(script_plan.scenes)}, shots: {len(script_plan.shots)}."
                    ),
                    status="completed",
                    metadata={
                        "script_text": script_plan.script_text,
                        "script_brief_id": script_plan.script_brief_id,
                        "script_version_id": script_plan.script_version_id,
                        "script_plan_version": script_plan.script_plan_version,
                        "materializer_mode": script_plan.materializer_mode,
                        "model_id": script_plan.model_id,
                        "selected_skill_ids": list(script_plan.selected_skill_ids),
                        "selected_skill_paths": list(script_plan.selected_skill_paths),
                        "skill_context_warnings": list(script_plan.skill_context_warnings),
                        "quality_notes": list(script_plan.quality_notes),
                        "materializer_version": script_plan.materializer_version,
                    },
                )
            ],
            metadata={"workflow_id": workflow_id},
        ),
        WorkflowNodeV2(
            node_id="product-generation",
            node_type="product-generation",
            title="Product Generation",
            status="ready",
            position={"x": 320, "y": -180},
            items=product_items,
            metadata={"workflow_id": workflow_id},
        ),
        WorkflowNodeV2(
            node_id="character-generation",
            node_type="character-generation",
            title="Character Generation",
            status="completed" if character_not_applicable else "ready",
            position={"x": 320, "y": 0},
            items=character_items,
            metadata={
                "workflow_id": workflow_id,
                **(
                    {
                        "execution_disposition": "not_applicable",
                        "reason_code": "no_character_required",
                    }
                    if character_not_applicable
                    else {}
                ),
            },
        ),
        WorkflowNodeV2(
            node_id="scene-generation",
            node_type="scene-generation",
            title="Scene Generation",
            status="ready",
            position={"x": 320, "y": 180},
            items=scene_items,
            metadata={"workflow_id": workflow_id},
        ),
        WorkflowNodeV2(
            node_id="bgm",
            node_type="bgm",
            title="BGM",
            status="ready",
            position={"x": 320, "y": 360},
            items=[bgm_item(expert_brief_plan.bgm_brief, script_plan, request)],
            metadata={"workflow_id": workflow_id},
        ),
        WorkflowNodeV2(
            node_id="storyboard",
            node_type="storyboard",
            title="Storyboard",
            status="not_ready",
            position={"x": 680, "y": 0},
            items=[],
            metadata={"not_ready_reason": "requires_visual_reference_bundles"},
        ),
        WorkflowNodeV2(
            node_id="final-composition",
            node_type="final-composition",
            title="Final Composition",
            status="not_ready",
            position={"x": 1040, "y": 0},
            items=[],
            metadata={"not_ready_reason": "requires_storyboard_video_segments_and_bgm"},
        ),
    ]


def build_display_edges(workflow_id: str) -> list[WorkflowEdgeV2]:
    return [
        WorkflowEdgeV2(
            edge_id=f"{source}->{target}",
            source_node_id=source,
            target_node_id=target,
            edge_kind="display_flow",
            metadata={"workflow_id": workflow_id},
        )
        for source, target in DISPLAY_EDGES
    ]


def product_item(brief: V2ProductBrief, script_plan: V2ScriptPlan) -> WorkflowItemV2:
    item_id = brief.item_id
    metadata = _brief_metadata(brief, script_plan, "product")
    metadata.update(identity_metadata(V2ItemIdentitySpecBuilder().build_product(brief)))
    main_prompt = _identity_slot_prompt(metadata, "product", "product_main_image", brief)
    multi_prompt = _identity_slot_prompt(metadata, "product", "product_multi_view_grid", brief)
    metadata["asset_prompts"] = {
        **dict(metadata.get("asset_prompts") or {}),
        "product_main_image": main_prompt,
        "product_multi_view_grid": multi_prompt,
    }
    return WorkflowItemV2(
        item_id=item_id,
        node_id="product-generation",
        item_type="product",
        display_name=brief.display_name,
        description=brief.description,
        item_prompt=brief.item_prompt,
        status="empty",
        metadata=metadata,
        slots=[
            build_slot(
                node_id="product-generation",
                item_id=item_id,
                slot_type="product_main_image",
                media_type="image",
                status="empty",
                prompt=main_prompt,
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "product",
                    "product_main_image",
                    prompt=main_prompt,
                    item_metadata=metadata,
                ),
            ),
            build_slot(
                node_id="product-generation",
                item_id=item_id,
                slot_type="product_multi_view_grid",
                media_type="image",
                status="blocked",
                prompt=multi_prompt,
                dependency_slot_ids=[f"{item_id}:product_main_image"],
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "product",
                    "product_multi_view_grid",
                    prompt=multi_prompt,
                    item_metadata=metadata,
                ),
            ),
        ],
    )


def character_item(brief: V2CharacterBrief, script_plan: V2ScriptPlan) -> WorkflowItemV2:
    item_id = brief.item_id
    metadata = _brief_metadata(brief, script_plan, "character")
    metadata.update(identity_metadata(V2ItemIdentitySpecBuilder().build_character(brief)))
    main_prompt = _identity_slot_prompt(metadata, "character", "character_main_image", brief)
    three_prompt = _identity_slot_prompt(metadata, "character", "character_three_view", brief)
    metadata["asset_prompts"] = {
        **dict(metadata.get("asset_prompts") or {}),
        "character_main_image": main_prompt,
        "character_three_view": three_prompt,
    }
    return WorkflowItemV2(
        item_id=item_id,
        node_id="character-generation",
        item_type="character",
        display_name=brief.display_name,
        description=brief.description,
        item_prompt=brief.item_prompt,
        status="empty",
        metadata=metadata,
        slots=[
            build_slot(
                node_id="character-generation",
                item_id=item_id,
                slot_type="character_main_image",
                media_type="image",
                status="empty",
                prompt=main_prompt,
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "character",
                    "character_main_image",
                    prompt=main_prompt,
                    item_metadata=metadata,
                ),
            ),
            build_slot(
                node_id="character-generation",
                item_id=item_id,
                slot_type="character_three_view",
                media_type="image",
                status="blocked",
                prompt=three_prompt,
                dependency_slot_ids=[f"{item_id}:character_main_image"],
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "character",
                    "character_three_view",
                    prompt=three_prompt,
                    item_metadata=metadata,
                ),
            ),
        ],
    )


def scene_item(brief: V2SceneBrief, script_plan: V2ScriptPlan) -> WorkflowItemV2:
    item_id = brief.item_id
    metadata = _brief_metadata(brief, script_plan, "scene")
    metadata.update(identity_metadata(V2ItemIdentitySpecBuilder().build_scene(brief)))
    main_prompt = _identity_slot_prompt(metadata, "scene", "scene_main_image", brief)
    multi_prompt = _identity_slot_prompt(metadata, "scene", "scene_multi_view_grid", brief)
    metadata["asset_prompts"] = {
        **dict(metadata.get("asset_prompts") or {}),
        "scene_main_image": main_prompt,
        "scene_multi_view_grid": multi_prompt,
    }
    return WorkflowItemV2(
        item_id=item_id,
        node_id="scene-generation",
        item_type="scene",
        display_name=brief.display_name,
        description=brief.description,
        item_prompt=brief.item_prompt,
        status="empty",
        metadata=metadata,
        slots=[
            build_slot(
                node_id="scene-generation",
                item_id=item_id,
                slot_type="scene_main_image",
                media_type="image",
                status="empty",
                prompt=main_prompt,
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "scene",
                    "scene_main_image",
                    prompt=main_prompt,
                    item_metadata=metadata,
                ),
            ),
            build_slot(
                node_id="scene-generation",
                item_id=item_id,
                slot_type="scene_multi_view_grid",
                media_type="image",
                status="blocked",
                prompt=multi_prompt,
                dependency_slot_ids=[f"{item_id}:scene_main_image"],
                metadata=_slot_brief_metadata(
                    brief,
                    script_plan,
                    "scene",
                    "scene_multi_view_grid",
                    prompt=multi_prompt,
                    item_metadata=metadata,
                ),
            ),
        ],
    )


def bgm_item(
    brief: V2BgmBrief,
    script_plan: V2ScriptPlan,
    request: WorkflowV2PlanFromPromptRequest,
) -> WorkflowItemV2:
    item_id = brief.item_id
    status = "skipped" if request.audio_mode == "none" else "empty"
    return WorkflowItemV2(
        item_id=item_id,
        node_id="bgm",
        item_type="bgm",
        display_name=brief.display_name,
        description=brief.description,
        item_prompt=brief.item_prompt,
        status=status,
        metadata=_brief_metadata(brief, script_plan, "bgm"),
        slots=[
            build_slot(
                node_id="bgm",
                item_id=item_id,
                slot_type="bgm_audio",
                media_type="audio",
                status=status,
                prompt=_slot_prompt(brief, "bgm_audio"),
                required=True,
                metadata=_slot_brief_metadata(brief, script_plan, "bgm", "bgm_audio"),
            )
        ],
    )


def build_slot(
    *,
    node_id: str,
    item_id: str,
    slot_type: str,
    media_type: Any,
    status: Any,
    prompt: str,
    dependency_slot_ids: list[str] | None = None,
    required: bool = True,
    metadata: dict[str, Any] | None = None,
) -> WorkflowSlotV2:
    return WorkflowSlotV2(
        slot_id=f"{item_id}:{slot_type}",
        node_id=node_id,
        item_id=item_id,
        slot_type=slot_type,
        media_type=media_type,
        required=required,
        status=status,
        slot_prompt=prompt,
        system_suggested_prompt=prompt,
        dependency_slot_ids=dependency_slot_ids or [],
        metadata=metadata or {},
    )


def _brief_metadata(brief: Any, script_plan: V2ScriptPlan, brief_kind: str) -> dict[str, Any]:
    metadata = {
        "source_script_brief_id": script_plan.script_brief_id,
        "source_script_version_id": script_plan.script_version_id,
        "source_scene_ids": list(brief.source_scene_ids),
        "source_shot_ids": list(brief.source_shot_ids),
        "brief_kind": brief_kind,
        "item_source": "expert_brief",
        "creative_brief": getattr(brief, "creative_brief", None) or brief.item_prompt,
        "asset_prompts": dict(getattr(brief, "asset_prompts", {}) or brief.slot_prompts),
        "specialist_quality_audit": dict(getattr(brief, "specialist_quality_audit", {}) or {}),
        "source_skill_ids": list(getattr(brief, "source_skill_ids", [])),
        "source_skill_paths": list(getattr(brief, "source_skill_paths", [])),
        "brief_builder_version": getattr(brief, "brief_builder_version", None),
    }
    brief_metadata = dict(getattr(brief, "metadata", {}) or {})
    metadata.update(brief_metadata)
    if brief_kind in {"product", "character", "scene"}:
        metadata.setdefault("source_inventory_item_id", brief.item_id)
    return metadata


def _slot_brief_metadata(
    brief: Any,
    script_plan: V2ScriptPlan,
    specialist_type: str,
    slot_type: str,
    *,
    prompt: str | None = None,
    item_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = prompt if prompt is not None else _slot_prompt(brief, slot_type)
    metadata = {
        "source_script_brief_id": script_plan.script_brief_id,
        "source_script_version_id": script_plan.script_version_id,
        "source_brief_item_id": brief.item_id,
        "specialist_type": specialist_type,
        "slot_type": slot_type,
        "asset_prompt_hash": _asset_prompt_hash(prompt),
        "specialist_quality_audit": dict(getattr(brief, "specialist_quality_audit", {}) or {}),
        "source_skill_ids": list(getattr(brief, "source_skill_ids", [])),
        "source_skill_paths": list(getattr(brief, "source_skill_paths", [])),
        "brief_builder_version": getattr(brief, "brief_builder_version", None),
    }
    brief_metadata = dict(getattr(brief, "metadata", {}) or {})
    for key in (
        "creative_inventory_id",
        "creative_inventory_hash",
        "creative_inventory_version",
        "source_inventory_item_id",
    ):
        if key in brief_metadata:
            metadata[key] = brief_metadata[key]
    if item_metadata:
        metadata.update(slot_identity_metadata(item_metadata))
    return metadata


def _slot_prompt(brief: Any, slot_type: str) -> str:
    asset_prompts = getattr(brief, "asset_prompts", {}) or {}
    slot_prompts = getattr(brief, "slot_prompts", {}) or {}
    prompt = asset_prompts.get(slot_type) or slot_prompts.get(slot_type)
    return str(prompt or "")


def _asset_prompt_hash(prompt: str) -> str:
    return "sha256:" + sha256(prompt.encode("utf-8")).hexdigest()


def _identity_slot_prompt(
    metadata: dict[str, Any],
    item_type: str,
    slot_type: str,
    brief: Any,
) -> str:
    spec = metadata.get("identity_spec")
    fallback = _slot_prompt(brief, slot_type)
    if not isinstance(spec, dict):
        return fallback
    return render_identity_slot_prompt(
        item_type=item_type,
        slot_type=slot_type,
        identity_spec=spec,
        fallback_prompt=fallback,
    )
