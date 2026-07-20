from __future__ import annotations

from app.schemas.workflow_nodes import WorkflowNodeCatalogItem, WorkflowNodeCatalogResponse


OPTIMIZER_AGENT_BY_NODE: dict[str, str] = {
    "product-generation": "Product Designer Agent",
    "character-generation": "Character Designer Agent",
    "scene-generation": "Scene Designer Agent",
    "storyboard": "Storyboard Agent",
    "storyboard-video-generation": "Video Generation / Composition Agent",
    "bgm": "BGM Agent",
}

OUTPUT_CONTRACT_MEDIA_NODES = {
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
}


NODE_CATALOG: list[WorkflowNodeCatalogItem] = [
    WorkflowNodeCatalogItem(
        node_type="script",
        display_name="Script Writer",
        category="agent",
        description="Generate an advertising script and playable subtitle lines.",
        optional_inputs=[
            "director_context",
            "ad_request",
            "requirements",
            "creative_direction",
            "product_design",
            "override_prompt",
        ],
        supports_override_prompt=True,
        downstream_nodes=[
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
            "bgm",
            "final-composition",
        ],
    ),
    WorkflowNodeCatalogItem(
        node_type="product-generation",
        display_name="Product Generation",
        category="image_generation",
        description="Optimize and generate strict-reference product image assets.",
        optional_inputs=[
            "director_context",
            "script",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        input_asset_roles=["product_reference"],
        output_asset_roles=["product_image"],
        supports_override_prompt=True,
        downstream_nodes=[
            "scene-generation",
            "storyboard",
            "storyboard-video-generation",
            "final-composition",
        ],
    ),
    WorkflowNodeCatalogItem(
        node_type="character-generation",
        display_name="Character Generation",
        category="image_generation",
        description="Optimize and generate character reference image assets.",
        optional_inputs=[
            "director_context",
            "script",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        input_asset_roles=["character_reference"],
        output_asset_roles=["character_main", "character_avatar", "character_turnaround"],
        supports_override_prompt=True,
        downstream_nodes=["storyboard", "storyboard-video-generation"],
    ),
    WorkflowNodeCatalogItem(
        node_type="scene-generation",
        display_name="Scene Generation",
        category="image_generation",
        description="Optimize and generate scene reference image assets.",
        optional_inputs=[
            "director_context",
            "script",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        input_asset_roles=["scene_reference"],
        output_asset_roles=["scene_main", "scene_reference"],
        supports_override_prompt=True,
        downstream_nodes=["storyboard", "storyboard-video-generation"],
    ),
    WorkflowNodeCatalogItem(
        node_type="storyboard",
        display_name="Storyboard Image Generation",
        category="image_generation",
        description="Optimize and generate storyboard image assets.",
        optional_inputs=[
            "director_context",
            "script",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        input_asset_roles=["character_turnaround", "scene_reference"],
        output_asset_roles=["storyboard"],
        supports_override_prompt=True,
        downstream_nodes=["storyboard-video-generation", "bgm"],
    ),
    WorkflowNodeCatalogItem(
        node_type="storyboard-video-generation",
        display_name="Storyboard Video Generation",
        category="video_generation",
        description="Optimize and generate storyboard video segments.",
        optional_inputs=[
            "director_context",
            "script",
            "storyboard",
            "scene_prompts",
            "duration_seconds",
            "aspect_ratio",
            "output_resolution",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        input_asset_roles=[
            "product_reference",
            "character_turnaround",
            "scene_reference",
            "storyboard",
        ],
        output_asset_roles=["video_segment"],
        supports_override_prompt=True,
        downstream_nodes=["final-composition"],
    ),
    WorkflowNodeCatalogItem(
        node_type="bgm",
        display_name="Background Music",
        category="audio_generation",
        description="Optimize and generate BGM for the advertisement.",
        optional_inputs=[
            "director_context",
            "script",
            "storyboard",
            "system_suggested_prompt",
            "user_prompt",
            "override_prompt",
        ],
        output_asset_roles=["audio"],
        supports_override_prompt=True,
        downstream_nodes=["final-composition"],
    ),
    WorkflowNodeCatalogItem(
        node_type="final-composition",
        display_name="Final Composition",
        category="composition",
        description="Compose downloaded video segments into the final mp4 or metadata plan.",
        required_inputs=["segments"],
        optional_inputs=["timeline", "subtitles", "audio"],
        input_asset_roles=["video_segment", "subtitle", "audio"],
        output_asset_roles=["final_video"],
        supports_override_prompt=False,
        downstream_nodes=[],
    ),
]

SUPPORTED_NODE_TYPES = {node.node_type for node in NODE_CATALOG}


def workflow_node_catalog_response() -> WorkflowNodeCatalogResponse:
    return WorkflowNodeCatalogResponse(nodes=NODE_CATALOG)


def catalog_item_for_node_type(node_type: str) -> WorkflowNodeCatalogItem:
    return next(node for node in NODE_CATALOG if node.node_type == node_type)
