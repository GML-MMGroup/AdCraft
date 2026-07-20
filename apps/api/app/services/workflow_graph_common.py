from __future__ import annotations


from app.schemas.workflow_graph import (
    CanvasPosition,
)


class WorkflowGraphError(ValueError):
    """Raised when an editable workflow graph cannot be loaded or saved."""


NODE_CATEGORY_BY_TYPE: dict[str, str] = {
    "requirements-analysis": "agent_text",
    "product-design": "agent_text",
    "creative-direction": "agent_text",
    "script": "agent_text",
    "product-generation": "image_generation",
    "character-generation": "image_generation",
    "scene-generation": "image_generation",
    "character-design": "agent_text",
    "scene-design": "agent_text",
    "storyboard": "image_generation",
    "character-image-generation": "image_generation",
    "scene-image-generation": "image_generation",
    "storyboard-image-generation": "image_generation",
    "storyboard-video-generation": "video_generation",
    "bgm": "audio_generation",
    "final-composition": "composition",
}
DEFAULT_POSITIONS: dict[str, CanvasPosition] = {
    "requirements-analysis": CanvasPosition(x=0, y=180),
    "product-design": CanvasPosition(x=180, y=180),
    "creative-direction": CanvasPosition(x=360, y=60),
    "script": CanvasPosition(x=0, y=180),
    "product-generation": CanvasPosition(x=240, y=180),
    "character-generation": CanvasPosition(x=240, y=80),
    "scene-generation": CanvasPosition(x=240, y=280),
    "character-design": CanvasPosition(x=540, y=80),
    "scene-design": CanvasPosition(x=540, y=280),
    "character-image-generation": CanvasPosition(x=720, y=80),
    "scene-image-generation": CanvasPosition(x=720, y=280),
    "storyboard": CanvasPosition(x=520, y=180),
    "storyboard-image-generation": CanvasPosition(x=1080, y=180),
    "storyboard-video-generation": CanvasPosition(x=800, y=180),
    "bgm": CanvasPosition(x=800, y=440),
    "final-composition": CanvasPosition(x=1080, y=180),
}
VERSION_FIELDS = {"prompt", "override_prompt", "config", "input_assets", "output", "metadata"}
PRESERVED_SYSTEM_INPUT_CONTEXT_KEYS = {
    "system_resolved_prompt_preview",
    "system_resolved_prompt_with_assets",
    "resolved_input_context",
    "materialized_prompt",
    "source_mappings",
}
PRESERVED_SYSTEM_METADATA_KEYS = {
    "system_materialized_prompt",
    "previous_system_materialized_prompt",
    "materialized_prompt",
    "materialized_asset_count",
    "materialized_prompt_updated_at",
    "source_mappings",
    "resolved_input_context",
    "resolved_input_asset_count",
    "resolved_prompt_preview",
    "resolved_prompt_with_assets",
    "effective_prompt",
    "prompt_source",
    "manual_prompt_dirty",
}
GRAPH_RECURSIVE_OMIT_KEYS = {"raw_response"}
GRAPH_INPUT_CONTEXT_OMIT_KEYS = {
    "resolved_input_assets",
    "materialized_assets",
}
