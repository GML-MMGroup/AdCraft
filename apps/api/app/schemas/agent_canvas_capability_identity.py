"""Stable capability identities and display projections for Agent Canvas."""

from typing import Literal


CapabilityIdV1 = Literal[
    "world_setting",
    "product_design",
    "prop_design",
    "character_design",
    "scene_design",
    "script_authoring",
    "storyboard_design",
    "video_direction",
    "bgm_direction",
    "quick_media",
]


CAPABILITY_DISPLAY_NAMES: dict[CapabilityIdV1, str] = {
    "world_setting": "World Setting Designer",
    "product_design": "Product Designer",
    "prop_design": "Prop Designer",
    "character_design": "Character Designer",
    "scene_design": "Scene Designer",
    "script_authoring": "Script Writer",
    "storyboard_design": "Storyboard Artist",
    "video_direction": "Video Director",
    "bgm_direction": "BGM Director",
    "quick_media": "Quick Media Agent",
}
