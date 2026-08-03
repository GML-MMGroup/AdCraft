"""Stable display labels for Agent Canvas specialists."""

from __future__ import annotations

_SPECIALIST_DISPLAY_NAMES: dict[str, str] = {
    "script_writer": "Script Writer",
    "product_designer": "Product Designer",
    "prop_designer": "Prop Designer",
    "character_designer": "Character Designer",
    "scene_designer": "Scene Designer",
    "storyboard_artist": "Storyboard Artist",
    "video_director": "Video Director",
    "bgm_director": "BGM Director",
    "quick_media_agent": "Quick Media Agent",
}


def specialist_display_name(specialist_name: str) -> str:
    """Return the status-neutral label exposed in activity records."""

    return _SPECIALIST_DISPLAY_NAMES[specialist_name]
