from typing import Any, Literal

from pydantic import BaseModel, Field


AdType = Literal[
    "product_showcase",
    "story_ad",
    "ip_character_ad",
    "ecommerce_ad",
    "brand_campaign",
    "promotion_ad",
    "acg_short",
]


class DirectorNodeBriefs(BaseModel):
    script: str = ""
    product_generation: str = ""
    character_generation: str = ""
    scene_generation: str = ""
    storyboard: str = ""
    storyboard_video_generation: str = ""
    bgm: str = ""
    final_composition: str = ""


class DirectorContext(BaseModel):
    workflow_id: str
    version: int = Field(default=1, ge=1)
    created_at: str | None = None
    updated_at: str | None = None
    ad_request: dict[str, Any] = Field(default_factory=dict)
    ad_type: AdType = "product_showcase"
    ad_type_confidence: float = Field(default=0.5, ge=0, le=1)
    strategy: dict[str, Any] = Field(default_factory=dict)
    commercial_design: dict[str, Any] = Field(default_factory=dict)
    creative_direction: dict[str, Any] = Field(default_factory=dict)
    art_direction: dict[str, Any] = Field(default_factory=dict)
    audio_direction: dict[str, Any] = Field(default_factory=dict)
    node_briefs: DirectorNodeBriefs = Field(default_factory=DirectorNodeBriefs)
    recommended_skill_groups: dict[str, list[str]] = Field(default_factory=dict)
    references: list[dict[str, Any]] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
