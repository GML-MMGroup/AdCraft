"""Deterministic ownership and context isolation for V2 Pi agents."""

from __future__ import annotations

from typing import Any

from app.schemas.agent_runtime import AgentName

_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credentials",
        "full_workflow",
        "local_path",
        "media_bytes",
        "provider_payload",
        "raw_media",
        "secret",
        "sibling_prompts",
        "sibling_provider_prompts",
        "token",
        "workflow_json",
    }
)


def agent_for_semantic_family(semantic_family: str) -> AgentName:
    if semantic_family.startswith("product_"):
        return "product_designer"
    if semantic_family.startswith("character_"):
        return "character_designer"
    if semantic_family.startswith("scene_"):
        return "scene_designer"
    if semantic_family.startswith("shot_cell_"):
        return "storyboard_artist"
    if semantic_family == "shot_video_segment":
        return "video_director"
    if semantic_family in {"bgm_audio", "bgm_track"}:
        return "bgm_director"
    if semantic_family in {"free_image", "free_video", "free_audio"}:
        return "quick_media_agent"
    raise ValueError("agent_semantic_family_not_allowed")


def isolate_agent_input_payload(payload: dict[str, Any]) -> dict[str, Any]:
    isolated = _isolate_value(payload)
    return isolated if isinstance(isolated, dict) else {}


def _isolate_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): isolated
            for key, child in value.items()
            if str(key).casefold() not in _FORBIDDEN_CONTEXT_KEYS
            and (isolated := _isolate_value(child)) is not None
        }
    if isinstance(value, (list, tuple)):
        return [isolated for child in value if (isolated := _isolate_value(child)) is not None]
    if isinstance(value, bytes):
        return None
    if isinstance(value, str):
        lowered = value.casefold()
        if ";base64," in lowered or lowered.startswith(("data:", "/", "\\\\")):
            return None
    return value
