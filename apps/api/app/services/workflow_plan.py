import json
import re
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.ad_workflow import (
    AdWorkflowGenerateRequest,
    AdWorkflowResponse,
    WorkflowEdge,
    WorkflowNode,
)
from app.schemas.asset_library import AssetReference
from app.schemas.chat_workflow import ChatWorkflowResponse
from app.schemas.director_context import AdType, DirectorContext, DirectorNodeBriefs
from app.schemas.front_desk import FrontDeskChatRequest
from app.services.agent_trace import utc_now
from app.services.asset_library_references import (
    normalize_asset_references,
    reference_context_for_node,
)
from app.services.director_context import save_director_context
from app.services.front_desk import FrontDeskError, FrontDeskService
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_graph import save_graph_for_plan
from app.services.workflow_node_direct_outputs import (
    creative_direction_output as _creative_direction_output,
    mock_agent_output as _mock_agent_output,
    product_design_output as _product_design_output,
    requirements_output_from_mapping as _requirements_output_from_mapping,
)
from app.services.workflow_prompt_projection import build_script_display_prompt
from app.services.script_beats import script_beats_from_script
from app.services.workflow_state import save_planning_context, save_workflow_plan
from app.workflows.ad_workflow import create_workflow_id


class WorkflowPlanError(RuntimeError):
    """Raised when a workflow plan cannot be created."""


CHAT_WORKFLOW_CREATION_NODE_SCOPED_REFERENCE_FIELDS = {
    "target_node_id",
    "target_node_type",
    "target_node_ids",
    "target_entity_id",
    "item_id",
}

PRODUCT_REFERENCE_HINTS = {
    "product",
    "product_reference",
    "product_main",
    "product_main_image",
    "product_packshot",
    "packshot",
    "package",
    "packaging",
    "brand",
    "brand_main",
    "main_image",
    "hero_image",
    "商品",
    "产品",
    "包装",
    "品牌",
    "主图",
}


def _plan_chat_ad_request_updates(
    request: FrontDeskChatRequest,
    ad_request: AdWorkflowGenerateRequest,
    data_dir: Path,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if request.skip_audio_agents:
        updates["skip_audio_agents"] = True
        updates["audio_mode"] = "none"
    elif request.audio_mode is not None:
        updates["audio_mode"] = request.audio_mode
    if request.selected_assets:
        updates["selected_assets"] = [
            *ad_request.selected_assets,
            *request.selected_assets,
        ]
    if ad_request.asset_references or request.asset_references:
        updates["asset_references"] = [
            *_sanitize_chat_workflow_creation_asset_references(
                data_dir,
                [*ad_request.asset_references, *request.asset_references],
            ),
        ]
    if request.library_entity_ids:
        updates["library_entity_ids"] = [
            *ad_request.library_entity_ids,
            *request.library_entity_ids,
        ]
    if request.reference_mode != "strict":
        updates["reference_mode"] = request.reference_mode
    return updates


def _sanitize_chat_workflow_creation_asset_references(
    data_dir: Path,
    asset_references: list[AssetReference | dict[str, Any]],
) -> list[AssetReference]:
    return [
        _sanitize_chat_workflow_creation_asset_reference(data_dir, reference)
        for reference in asset_references
    ]


def _sanitize_chat_workflow_creation_asset_reference(
    data_dir: Path,
    reference: AssetReference | dict[str, Any],
) -> AssetReference:
    if isinstance(reference, AssetReference):
        return reference.model_copy(
            update={
                "target_node_ids": [],
                "role": _chat_workflow_creation_reference_role(data_dir, reference),
            }
        )
    payload = dict(reference)
    for field in CHAT_WORKFLOW_CREATION_NODE_SCOPED_REFERENCE_FIELDS:
        payload.pop(field, None)
    parsed = AssetReference.model_validate(payload)
    return parsed.model_copy(
        update={"role": _chat_workflow_creation_reference_role(data_dir, parsed)}
    )


def _chat_workflow_creation_reference_role(
    data_dir: Path,
    reference: AssetReference,
) -> str | None:
    role = reference.role
    if role not in (None, "", "general_reference"):
        return role
    if _is_product_like_chat_reference(data_dir, reference):
        return "product_reference"
    return role


def _is_product_like_chat_reference(data_dir: Path, reference: AssetReference) -> bool:
    values = _reference_product_hint_values(reference)
    if reference.reference_source == "asset_library" and reference.entity_id:
        values.extend(_asset_library_product_hint_values(data_dir, reference.entity_id))
    return any(_value_has_product_hint(value) for value in values)


def _reference_product_hint_values(reference: AssetReference) -> list[Any]:
    metadata = reference.metadata if isinstance(reference.metadata, dict) else {}
    values: list[Any] = [
        reference.role,
        reference.display_name,
        reference.mention_text,
        metadata,
        *metadata.values(),
    ]
    return values


def _asset_library_product_hint_values(data_dir: Path, entity_id: str) -> list[Any]:
    values: list[Any] = []
    entity_path = data_dir / "asset_library" / "entities" / f"{entity_id}.json"
    if not entity_path.exists():
        return values
    try:
        entity = json.loads(entity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return values
    if not isinstance(entity, dict):
        return values
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
    values.extend(
        [
            entity.get("entity_type"),
            entity.get("display_name"),
            entity.get("description"),
            metadata,
            *metadata.values(),
        ]
    )
    for asset_id in entity.get("asset_ids", []):
        values.extend(_asset_product_hint_values(data_dir, str(asset_id)))
    return values


def _asset_product_hint_values(data_dir: Path, asset_id: str) -> list[Any]:
    asset_path = data_dir / "asset_library" / "assets" / f"{asset_id}.json"
    if not asset_path.exists():
        return []
    try:
        asset = json.loads(asset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(asset, dict):
        return []
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    return [
        asset.get("asset_type"),
        asset.get("semantic_type"),
        asset.get("mime_type"),
        metadata,
        *metadata.values(),
    ]


def _value_has_product_hint(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_value_has_product_hint(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_value_has_product_hint(item) for item in value)
    text = str(value or "").strip().casefold()
    if not text:
        return False
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", text)
    return any(hint in normalized for hint in PRODUCT_REFERENCE_HINTS)


class AdWorkflowPlanService:
    def __init__(
        self,
        settings: Settings,
        front_desk_service: FrontDeskService | None = None,
    ) -> None:
        self._settings = settings
        self._front_desk_service = front_desk_service or FrontDeskService(settings)

    def plan(self, request: AdWorkflowGenerateRequest) -> AdWorkflowResponse:
        return create_workflow_plan(request, self._settings)

    def plan_from_chat(self, request: FrontDeskChatRequest) -> ChatWorkflowResponse:
        try:
            front_desk_response = self._front_desk_service.chat(request)
        except FrontDeskError as exc:
            raise WorkflowPlanError(f"front_desk_failed: {exc}") from exc
        except Exception as exc:
            raise WorkflowPlanError(f"front_desk_failed: {exc}") from exc

        if not front_desk_response.should_start_workflow:
            return ChatWorkflowResponse(front_desk=front_desk_response)
        if front_desk_response.ad_request is None:
            raise WorkflowPlanError(
                "invalid_front_desk_state: should_start_workflow=true but ad_request is missing"
            )

        ad_request = front_desk_response.ad_request
        updates = _plan_chat_ad_request_updates(
            request,
            ad_request,
            self._settings.media_data_dir,
        )
        if updates:
            ad_request = ad_request.model_copy(update=updates)
        return ChatWorkflowResponse(
            front_desk=front_desk_response,
            workflow=create_workflow_plan(ad_request, self._settings),
        )


PLAN_NODE_DEFS: dict[str, dict[str, Any]] = {
    "script": {
        "type": "agent",
        "title": "Ad Script",
        "description": "Generate the short advertising script.",
        "supports_override_prompt": True,
    },
    "product-generation": {
        "type": "tool",
        "title": "Product Generation",
        "description": "Optimize and generate strict-reference product image assets.",
        "supports_override_prompt": True,
    },
    "character-generation": {
        "type": "tool",
        "title": "Character Generation",
        "description": "Optimize and generate character reference image assets.",
        "supports_override_prompt": True,
    },
    "scene-generation": {
        "type": "tool",
        "title": "Scene Generation",
        "description": "Optimize and generate scene reference image assets.",
        "supports_override_prompt": True,
    },
    "storyboard": {
        "type": "tool",
        "title": "Storyboard Image Generation",
        "description": "Optimize and generate storyboard image assets.",
        "supports_override_prompt": True,
    },
    "storyboard-video-generation": {
        "type": "tool",
        "title": "Storyboard Video Generation",
        "description": "Optimize and generate storyboard video segments.",
        "supports_override_prompt": True,
    },
    "bgm": {
        "type": "tool",
        "title": "Background Music",
        "description": "Optimize and generate BGM for the advertisement.",
        "supports_override_prompt": True,
    },
    "final-composition": {
        "type": "tool",
        "title": "Final Video Composition",
        "description": "Compose generated video segments and BGM into the final video.",
        "supports_override_prompt": False,
    },
}


def create_workflow_plan(
    request: AdWorkflowGenerateRequest,
    settings: Settings,
    workflow_id: str | None = None,
) -> AdWorkflowResponse:
    normalized_request = _request_with_audio_mode(request)
    audio_mode = normalized_request.audio_mode
    workflow_id = workflow_id or create_workflow_id()
    node_order = _plan_node_order(audio_mode)
    asset_references = normalize_asset_references(
        settings.media_data_dir,
        normalized_request.asset_references,
        library_entity_ids=normalized_request.library_entity_ids,
        available_node_ids=set(node_order),
        workflow_id=workflow_id,
    )
    planning_context = _build_planning_context(
        normalized_request,
        workflow_id,
        audio_mode,
        asset_references,
    )
    director_context = _build_director_context(
        normalized_request,
        workflow_id,
        audio_mode,
        planning_context,
        asset_references,
    )
    edges = _plan_edges(audio_mode)
    depends_on = _depends_on(edges)
    nodes = [
        _plan_node(
            node_id,
            depends_on.get(node_id, []),
            normalized_request,
            audio_mode,
            planning_context,
            director_context,
            asset_references,
        )
        for node_id in node_order
    ]
    workflow = AdWorkflowResponse(workflow_id=workflow_id, nodes=nodes, edges=edges)
    ad_request = normalized_request.model_dump(mode="json")
    ad_request["asset_references"] = asset_references
    save_director_context(settings.media_data_dir, director_context)
    save_workflow_plan(
        workflow=workflow,
        ad_request=ad_request,
        audio_mode=audio_mode,
        data_dir=settings.media_data_dir,
    )
    save_planning_context(
        workflow_id=workflow_id,
        planning_context=planning_context,
        data_dir=settings.media_data_dir,
    )
    save_graph_for_plan(
        workflow=workflow,
        ad_request=ad_request,
        audio_mode=audio_mode,
        data_dir=settings.media_data_dir,
    )
    return workflow


def _request_with_audio_mode(request: AdWorkflowGenerateRequest) -> AdWorkflowGenerateRequest:
    if request.skip_audio_agents:
        return request.model_copy(update={"audio_mode": "none"})
    return request


def _plan_node_order(audio_mode: str) -> list[str]:
    node_ids = [
        "script",
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
    ]
    if audio_mode in {"bgm_only", "full"}:
        node_ids.append("bgm")
    node_ids.append("final-composition")
    return node_ids


def _plan_edges(audio_mode: str) -> list[WorkflowEdge]:
    edges = [
        WorkflowEdge(source="script", target="product-generation", label="product brief"),
        WorkflowEdge(source="script", target="character-generation", label="character brief"),
        WorkflowEdge(source="script", target="scene-generation", label="scene brief"),
        WorkflowEdge(source="script", target="storyboard", label="script"),
        WorkflowEdge(
            source="product-generation", target="scene-generation", label="product references"
        ),
        WorkflowEdge(source="product-generation", target="storyboard", label="product references"),
        WorkflowEdge(
            source="product-generation",
            target="storyboard-video-generation",
            label="product references",
        ),
        WorkflowEdge(
            source="product-generation", target="final-composition", label="product stills"
        ),
        WorkflowEdge(
            source="character-generation", target="storyboard", label="character references"
        ),
        WorkflowEdge(source="scene-generation", target="storyboard", label="scene references"),
        WorkflowEdge(
            source="storyboard", target="storyboard-video-generation", label="storyboard images"
        ),
        WorkflowEdge(
            source="character-generation",
            target="storyboard-video-generation",
            label="character references",
        ),
        WorkflowEdge(
            source="scene-generation",
            target="storyboard-video-generation",
            label="scene references",
        ),
        WorkflowEdge(
            source="storyboard-video-generation",
            target="final-composition",
            label="video segments",
        ),
        WorkflowEdge(
            source="script",
            target="final-composition",
            label="script",
        ),
    ]
    if audio_mode in {"bgm_only", "full"}:
        edges.extend(
            [
                WorkflowEdge(source="script", target="bgm", label="music brief"),
                WorkflowEdge(source="storyboard", target="bgm", label="storyboard rhythm"),
                WorkflowEdge(source="bgm", target="final-composition", label="background music"),
            ]
        )
    return edges


def _depends_on(edges: list[WorkflowEdge]) -> dict[str, list[str]]:
    depends_on: dict[str, list[str]] = {}
    for edge in edges:
        depends_on.setdefault(edge.target, []).append(edge.source)
    return depends_on


def _plan_node(
    node_id: str,
    depends_on: list[str],
    request: AdWorkflowGenerateRequest,
    audio_mode: str,
    planning_context: dict[str, Any],
    director_context: DirectorContext,
    asset_references: list[dict[str, Any]],
) -> WorkflowNode:
    node_def = PLAN_NODE_DEFS[node_id]
    content: dict[str, Any] = {}
    prompt = _node_system_suggestion(node_id, director_context)
    director_summary = _director_context_summary(director_context)
    input_context: dict[str, Any] = _node_input_context(
        node_id,
        prompt,
        director_summary,
        planning_context["script"],
    )
    metadata: dict[str, Any] = {
        "stage": "planned",
        "audio_mode": audio_mode,
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "output_resolution": request.output_resolution,
        "prompt_source": "system",
        "manual_prompt_dirty": False,
        "has_new_system_suggestion": False,
        "director_context_version": director_context.version,
    }
    if node_id == "script":
        content = dict(planning_context["script"])
        prompt = build_script_display_prompt(content, planning_context)
        input_context = _node_input_context(
            node_id,
            prompt,
            director_summary,
            content,
        )
        input_context["resolved_input_context"]["ad_request"] = planning_context["ad_request"]
        metadata["director_context_available"] = True
    reference_assets = _apply_reference_context(input_context, node_id, asset_references)
    if node_id == "product-generation":
        input_context["media_items"] = _product_generation_media_items(
            prompt,
            planning_context["ad_request"],
            input_context.get("display_input_assets", []),
        )
        input_context["resolved_input_context"]["media_items"] = input_context["media_items"]
    return WorkflowNode(
        id=node_id,
        type=node_def["type"],
        title=node_def["title"],
        description=node_def["description"],
        status="completed" if node_id == "script" else "pending",
        content=content,
        output=content,
        prompt=prompt,
        override_prompt=prompt,
        input_context=input_context,
        metadata=metadata,
        input_assets=reference_assets,
        output_assets=[],
        depends_on=depends_on,
        can_run_standalone=True,
        supports_override_prompt=bool(node_def["supports_override_prompt"]),
    )


def _node_input_context(
    node_id: str,
    system_suggested_prompt: str,
    director_summary: dict[str, Any],
    script_output: dict[str, Any],
) -> dict[str, Any]:
    resolved_context: dict[str, Any] = {
        "director_context": director_summary,
        "ad_type": director_summary.get("ad_type"),
        "recommended_skill_groups": director_summary.get("recommended_skill_groups", {}).get(
            node_id, []
        ),
        "system_suggested_prompt": system_suggested_prompt,
    }
    if node_id != "script":
        resolved_context["script"] = script_output
    preview = system_suggested_prompt[:240] + ("..." if len(system_suggested_prompt) > 240 else "")
    return {
        "director_context_summary": director_summary,
        "ad_type": director_summary.get("ad_type"),
        "recommended_skill_groups": director_summary.get("recommended_skill_groups", {}).get(
            node_id, []
        ),
        "system_suggested_prompt": system_suggested_prompt,
        "user_prompt": "",
        "optimized_generation_prompt": "",
        "provider_prompt": "",
        "materialized_prompt": system_suggested_prompt,
        "resolved_input_context": resolved_context,
        "source_mappings": [
            {
                "source_node_id": "director-context",
                "target_node_id": node_id,
                "field": "system_suggested_prompt",
            }
        ],
        "system_resolved_prompt_preview": preview,
        "system_resolved_prompt_with_assets": system_suggested_prompt,
        "resolved_input_assets": [],
        "materialized_assets": [],
    }


def _apply_reference_context(
    input_context: dict[str, Any],
    node_id: str,
    asset_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reference_context = reference_context_for_node(asset_references, node_id)
    input_context["asset_references"] = reference_context["asset_references"]
    input_context["prompt_context_assets"] = reference_context["prompt_context_assets"]
    input_context["provider_reference_assets"] = reference_context["provider_reference_assets"]
    input_context["display_input_assets"] = reference_context["display_input_assets"]
    resolved_context = input_context.setdefault("resolved_input_context", {})
    resolved_context["asset_references"] = reference_context["asset_references"]
    resolved_context["prompt_context_assets"] = reference_context["prompt_context_assets"]
    resolved_context["provider_reference_assets"] = reference_context["provider_reference_assets"]
    resolved_context["display_input_assets"] = reference_context["display_input_assets"]
    input_context["resolved_input_assets"] = dedupe_output_assets(
        [
            *input_context.get("resolved_input_assets", []),
            *reference_context["display_input_assets"],
        ]
    )
    input_context["materialized_assets"] = dedupe_output_assets(
        [
            *input_context.get("materialized_assets", []),
            *reference_context["prompt_context_assets"],
        ]
    )
    input_context["source_mappings"] = [
        *input_context.get("source_mappings", []),
        *reference_context["source_mappings"],
    ]
    return reference_context["display_input_assets"]


def _product_generation_media_items(
    prompt: str,
    ad_request: dict[str, Any],
    display_input_assets: Any,
) -> list[dict[str, Any]]:
    reference_assets = [
        asset
        for asset in display_input_assets
        if isinstance(asset, dict) and asset.get("role") == "product_reference"
    ]
    input_asset_ids = [
        str(asset.get("asset_id"))
        for asset in reference_assets
        if str(asset.get("asset_id") or "").strip()
    ]
    reference_required = bool(reference_assets)
    product_name = str(ad_request.get("product_name") or "Product")
    item_prompt = prompt or f"Clean hero product image for {product_name}."
    return [
        {
            "item_id": "product-1",
            "item_type": "product_image",
            "order": 1,
            "display_name": f"{product_name} hero image",
            "prompt": item_prompt,
            "prompt_source": "system",
            "manual_prompt_dirty": False,
            "input_asset_ids": input_asset_ids,
            "reference_mode": "strict",
            "status": "pending",
            "output_assets": [],
            "metadata": {
                "product_reference_required": reference_required,
                "product_identity_locked": reference_required,
                "commercial_design_source": "director_context",
            },
        }
    ]


def _node_system_suggestion(node_id: str, director_context: DirectorContext) -> str:
    field_by_node = {
        "script": "script",
        "product-generation": "product_generation",
        "character-generation": "character_generation",
        "scene-generation": "scene_generation",
        "storyboard": "storyboard",
        "storyboard-video-generation": "storyboard_video_generation",
        "bgm": "bgm",
        "final-composition": "final_composition",
    }
    brief_field = field_by_node[node_id]
    return str(getattr(director_context.node_briefs, brief_field) or "")


def _director_context_summary(director_context: DirectorContext) -> dict[str, Any]:
    return {
        "workflow_id": director_context.workflow_id,
        "version": director_context.version,
        "ad_type": director_context.ad_type,
        "ad_type_confidence": director_context.ad_type_confidence,
        "strategy": director_context.strategy,
        "commercial_design": director_context.commercial_design,
        "creative_direction": director_context.creative_direction,
        "art_direction": director_context.art_direction,
        "audio_direction": director_context.audio_direction,
        "node_briefs": director_context.node_briefs.model_dump(mode="json"),
        "recommended_skill_groups": director_context.recommended_skill_groups,
        "references": director_context.references,
    }


def _reference_constraint_summary(asset_references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "entity_id": reference.get("entity_id"),
            "display_name": reference.get("display_name"),
            "role": reference.get("role"),
            "lock_identity": reference.get("lock_identity", False),
            "allow_style_transfer": reference.get("allow_style_transfer", False),
            "target_node_ids": reference.get("target_node_ids", []),
        }
        for reference in asset_references
    ]


def _reference_brief_note(asset_references: list[dict[str, Any]]) -> str:
    if not asset_references:
        return ""
    labels = [
        f"{reference.get('display_name')} ({reference.get('role')})"
        for reference in asset_references
        if reference.get("display_name")
    ]
    if not labels:
        return ""
    return f" Use asset library references: {', '.join(labels)}."


def _build_director_context(
    request: AdWorkflowGenerateRequest,
    workflow_id: str,
    audio_mode: str,
    planning_context: dict[str, Any],
    asset_references: list[dict[str, Any]],
) -> DirectorContext:
    ad_request = request.model_dump(mode="json")
    requirements = planning_context["requirements_analysis"]
    product_design = planning_context["product_design"]
    creative_direction = planning_context["creative_direction"]
    visual_style = request.visual_style or creative_direction.get("visual_style") or "brand-aligned"
    ad_type, ad_type_confidence, ad_type_reason = _classify_ad_type(ad_request)
    now = utc_now().isoformat()
    return DirectorContext(
        workflow_id=workflow_id,
        version=1,
        created_at=now,
        updated_at=now,
        ad_request=ad_request,
        ad_type=ad_type,
        ad_type_confidence=ad_type_confidence,
        strategy={
            "core_selling_point": requirements.get("core_selling_point"),
            "target_audience": requirements.get("target_audience"),
            "campaign_goal": requirements.get("campaign_goal"),
            "desired_emotion": requirements.get("desired_emotion"),
            "duration_seconds": requirements.get("duration_seconds"),
            "references": ad_request.get("references", []),
            "asset_references": asset_references,
            "channels": ad_request.get("channels", []),
        },
        commercial_design=product_design,
        creative_direction=creative_direction,
        art_direction={
            "visual_style": visual_style,
            "continuity_constraints": "Keep product, characters, scenes, and camera language consistent.",
            "quality_bar": f"{ad_request.get('output_resolution') or 'default'} production quality",
            "library_reference_constraints": _reference_constraint_summary(asset_references),
        },
        audio_direction={
            "audio_mode": audio_mode,
            "mood": request.desired_emotion,
            "sync_constraints": "Match music and edit rhythm to the script timing.",
        },
        node_briefs=_director_node_briefs(
            ad_request,
            planning_context,
            visual_style,
            audio_mode,
            asset_references,
        ),
        recommended_skill_groups=_recommended_skill_groups(ad_type, audio_mode),
        references=asset_references,
        source={
            "planner": "director-planning-path",
            "ad_type_reason": ad_type_reason,
        },
    )


def _classify_ad_type(ad_request: dict[str, Any]) -> tuple[AdType, float, str]:
    text = " ".join(
        str(ad_request.get(key) or "")
        for key in (
            "product_name",
            "product_description",
            "core_selling_point",
            "target_audience",
            "campaign_goal",
            "desired_emotion",
            "visual_style",
        )
    ).lower()
    scored_rules: list[tuple[AdType, tuple[str, ...], str]] = [
        (
            "ecommerce_ad",
            (
                "ecommerce",
                "shopping",
                "coupon",
                "discount",
                "buy now",
                "store conversion",
                "conversion",
                "电商",
                "下单",
                "购买",
                "优惠券",
                "折扣",
                "直播间",
            ),
            "commerce/conversion terms",
        ),
        (
            "promotion_ad",
            (
                "promotion",
                "limited-time",
                "limited time",
                "launch event",
                "campaign sale",
                "促销",
                "活动",
                "限时",
                "上新",
                "新品发布",
            ),
            "promotion/event terms",
        ),
        (
            "story_ad",
            (
                "story",
                "story-led",
                "narrative",
                "friendship",
                "courage",
                "emotional arc",
                "故事",
                "剧情",
                "叙事",
            ),
            "story/narrative terms",
        ),
        (
            "ip_character_ad",
            (
                "ip",
                "mascot",
                "character-centered",
                "hero character",
                "ip角色",
                "吉祥物",
                "角色ip",
            ),
            "IP/character terms",
        ),
        (
            "acg_short",
            (
                "acg",
                "anime",
                "manga",
                "game-like",
                "二次元",
                "动漫",
                "漫画",
                "游戏感",
            ),
            "ACG style terms",
        ),
        (
            "brand_campaign",
            (
                "brand campaign",
                "premium",
                "brand values",
                "brand image",
                "less salesy",
                "品牌",
                "高端",
                "品牌形象",
            ),
            "brand positioning terms",
        ),
        (
            "product_showcase",
            (
                "showcase",
                "demo",
                "close-up",
                "feature",
                "benefit",
                "product",
                "展示",
                "卖点",
                "特写",
                "功能",
            ),
            "product showcase terms",
        ),
    ]
    for ad_type, keywords, reason in scored_rules:
        if any(_keyword_matches(text, keyword) for keyword in keywords):
            return ad_type, 0.85, reason
    return "product_showcase", 0.55, "default closest legal ad_type"


def _keyword_matches(text: str, keyword: str) -> bool:
    if keyword.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9 -]*", keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return keyword in text


def _recommended_skill_groups(ad_type: AdType, audio_mode: str) -> dict[str, list[str]]:
    script_groups: dict[AdType, list[str]] = {
        "product_showcase": ["short_ad_structure", "cta_copy"],
        "story_ad": ["story_short_script", "rhythm_duration_control"],
        "ip_character_ad": ["story_short_script", "voiceover_copy"],
        "ecommerce_ad": ["short_ad_structure", "cta_copy"],
        "brand_campaign": ["voiceover_copy", "rhythm_duration_control"],
        "promotion_ad": ["short_ad_structure", "cta_copy"],
        "acg_short": ["story_short_script", "rhythm_duration_control"],
    }
    groups = {
        "script": script_groups[ad_type],
        "product-generation": [
            "product_showcase_strategy",
            "product_image_prompt_expansion",
            "product_reference_selection",
        ],
        "character-generation": [
            "character_setting_extraction",
            "character_style_selection",
            "character_image_prompt_expansion",
            "character_three_view_generation",
        ],
        "scene-generation": [
            "scene_setting_extraction",
            "scene_style_selection",
            "scene_image_prompt_expansion",
            "scene_multiview_generation",
        ],
        "storyboard": [
            "shot_list_generation",
            "storyboard_image_prompt_generation",
            "reference_asset_selection",
        ],
        "storyboard-video-generation": [
            "storyboard_video_prompt_generation",
            "camera_motion_prompt_generation",
            "storyboard_video_generation",
        ],
        "final-composition": ["timeline_validation", "ffmpeg_composition"],
    }
    if ad_type == "ecommerce_ad":
        groups["storyboard"] = ["product_storyboard", "storyboard_image_prompt_generation"]
        groups["scene-generation"] = ["product_scene_design", "scene_image_prompt_expansion"]
    elif ad_type == "story_ad":
        groups["storyboard"] = ["shot_list_generation", "storyboard_continuity_check"]
        groups["storyboard-video-generation"] = [
            "storyboard_video_prompt_generation",
            "camera_motion_prompt_generation",
            "dialogue_prompt_generation",
        ]
    if audio_mode in {"bgm_only", "full"}:
        groups["bgm"] = [
            "music_mood_direction",
            "music_prompt_generation",
            "tempo_duration_match",
        ]
    return groups


def _director_node_briefs(
    ad_request: dict[str, Any],
    planning_context: dict[str, Any],
    visual_style: str,
    audio_mode: str,
    asset_references: list[dict[str, Any]],
) -> DirectorNodeBriefs:
    product_name = str(ad_request.get("product_name") or "the product")
    audience = str(ad_request.get("target_audience") or "the target audience")
    emotion = str(ad_request.get("desired_emotion") or "brand confidence")
    selling_point = str(ad_request.get("core_selling_point") or "the key selling point")
    script = planning_context["script"]
    script_summary = " ".join(
        str(script.get(part) or "") for part in ("hook", "body", "cta") if script.get(part)
    )
    shot_beat_summary = _brief_shot_beat_summary(script)
    reference_note = _reference_brief_note(asset_references)
    return DirectorNodeBriefs(
        script=(
            f"Write a {ad_request.get('duration_seconds', 30)} second ad script for "
            f"{product_name}, aimed at {audience}, emphasizing {selling_point}. "
            "Include 4-6 ordered shot_beats with duration, scene intent, location, visual action, "
            "product action, and audience-facing copy."
            f"{reference_note}"
        ),
        product_generation=(
            f"Generate product image assets for {product_name}. "
            "Preserve uploaded product visual identity when product references exist. "
            f"Emphasize {selling_point} for {audience} using {visual_style} commercial art direction."
            f"{reference_note}"
        ),
        character_generation=(
            f"Generate brand-aligned character image assets for {product_name}. "
            f"Audience: {audience}. Emotion: {emotion}. Visual style: {visual_style}. "
            "Create main character references, avatar-ready details, and turnaround-friendly poses."
            f"{reference_note}"
        ),
        scene_generation=(
            f"Generate scene reference image assets for {product_name}. "
            f"Use {visual_style} art direction and environments that support: {script_summary}. "
            f"Shot beats: {shot_beat_summary} "
            "Create at least 3 distinct scene specs with stable ids scene-reference-1, "
            "scene-reference-2, scene-reference-3; vary location, lighting, atmosphere, and spatial layout."
            f"{reference_note}"
        ),
        storyboard=(
            f"Generate storyboard image assets for the {product_name} ad. "
            "Translate the script into clear shot images with consistent characters, product presence, "
            "camera rhythm, and commercial readability. "
            f"Shot beats: {shot_beat_summary} "
            "Each storyboard scene is one single keyframe plan for exactly one shot; include "
            "scene_id and input_asset_ids, and bind shots to scene-reference-N."
            f"{reference_note}"
        ),
        storyboard_video_generation=(
            f"Generate short video segments from storyboard images for {product_name}. "
            "Preserve character, scene, and product continuity while matching the script timing."
            f"{reference_note}"
        ),
        bgm=(
            f"Generate {audio_mode} background music direction for {product_name}: "
            f"{emotion}, timed to the ad rhythm and final edit."
        ),
        final_composition=(
            "Compose the final ad from generated video segments, script/subtitles, timing metadata, "
            "and BGM when available. Do not invent missing media assets."
        ),
    )


def _brief_shot_beat_summary(script: dict[str, Any]) -> str:
    beats = script_beats_from_script(script)
    if not beats:
        return "No structured shot beats yet."
    return " ".join(
        (
            f"Beat {beat.get('order')}: {beat.get('duration_seconds')}s, "
            f"{beat.get('scene_intent')} at {beat.get('location_hint')}, "
            f"{beat.get('visual_action')}"
        )
        for beat in beats
    )


def _build_planning_context(
    request: AdWorkflowGenerateRequest,
    workflow_id: str,
    audio_mode: str,
    asset_references: list[dict[str, Any]],
) -> dict[str, Any]:
    ad_request = request.model_dump(mode="json")
    ad_request["asset_references"] = asset_references
    requirements = _requirements_output_from_mapping(ad_request)
    product_design = _product_design_output(request, requirements)
    creative_direction = _creative_direction_output(
        request,
        {
            "requirements": requirements,
            "product_design": product_design,
        },
    )
    script = _mock_agent_output(
        "script",
        {
            "requirements": requirements,
            "product_design": product_design,
            "creative_direction": creative_direction,
            "ad_request": ad_request,
        },
        None,
    )
    return {
        "workflow_id": workflow_id,
        "created_at": utc_now().isoformat(),
        "audio_mode": audio_mode,
        "ad_request": ad_request,
        "asset_references": asset_references,
        "requirements_analysis": requirements,
        "product_design": product_design,
        "creative_direction": creative_direction,
        "script": script,
    }
