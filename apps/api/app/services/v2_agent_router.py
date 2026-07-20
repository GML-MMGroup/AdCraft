from app.schemas.workflow_v2 import V2AgentRoute, V2GenerationTarget, WorkflowV2Specialist


class V2AgentRouteError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2AgentRouter:
    def route(self, target: V2GenerationTarget) -> V2AgentRoute:
        specialist = _specialist_for_target(target)
        if specialist is None:
            raise V2AgentRouteError("agent_route_not_found")
        return V2AgentRoute(
            specialist=specialist,
            owner_node_id=target.node_id,
            owner_item_id=target.item_id,
            owner_slot_id=target.slot_id,
            generation_mode=_generation_mode(target, specialist),
            materializer_version="v2.0",
        )


def _specialist_for_target(target: V2GenerationTarget) -> WorkflowV2Specialist | None:
    slot_type = target.slot_type or ""
    node_id = target.node_id or ""
    node_type = target.node_type or node_id

    if node_id == "product-generation" or node_type == "product-generation":
        return "product_designer"
    if node_id == "character-generation" or node_type == "character-generation":
        return "character_designer"
    if node_id == "scene-generation" or node_type == "scene-generation":
        return "scene_designer"
    if node_id == "bgm" or node_type == "bgm":
        return "sound_director"
    if node_id == "final-composition" or node_type == "final-composition":
        return "composition_tool"
    if node_id == "storyboard" or node_type == "storyboard":
        if slot_type.startswith("shot_cell_") or not slot_type:
            return "storyboard_artist"
        if slot_type == "shot_video_segment":
            return "video_director"
    if (node_type == "free-generation" or node_id.startswith("free-generation")) and (
        target.is_free_generation or slot_type == "free_output"
    ):
        if target.media_type == "video":
            return "quick_video_generator"
        if target.media_type == "audio":
            return "quick_audio_generator"
        return "quick_image_generator"
    return None


def _generation_mode(target: V2GenerationTarget, specialist: WorkflowV2Specialist) -> str:
    if specialist == "composition_tool":
        return "composition"
    if specialist in {
        "quick_image_generator",
        "quick_video_generator",
        "quick_audio_generator",
    }:
        return "free_generation"
    if target.slot_id:
        return "slot_generation"
    if target.item_id:
        return "item_prompt_revision"
    return "node_prompt_revision"
