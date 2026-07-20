from typing import Any


def followups_for_item_action(node_type: str, item_id: str, action: str) -> list[dict[str, Any]]:
    if node_type == "scene-generation" and action == "item_selected":
        return [
            {
                "action_type": "add_item",
                "target_node_id": "storyboard",
                "item_type": "storyboard_image",
                "source_item_id": item_id,
                "confirm_required": True,
            }
        ]
    if node_type == "storyboard" and action == "item_selected":
        return [
            {
                "action_type": "generate_shot_video",
                "target_node_id": "storyboard-video-generation",
                "shot_id": item_id,
                "confirm_required": True,
            }
        ]
    if node_type == "storyboard-video-generation" and action in {
        "item_selected",
        "shot_video_generated",
    }:
        return [
            {
                "action_type": "use_current_shot_videos_for_composition",
                "target_node_id": "storyboard-video-generation",
                "shot_id": item_id,
                "confirm_required": True,
            }
        ]
    return []


def item_event_payload(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    refresh: list[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_type": node_type,
        "item_id": item_id,
        "refresh": refresh,
        **extra,
    }
