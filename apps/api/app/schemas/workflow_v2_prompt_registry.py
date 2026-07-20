from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


V2PromptRegistryScope = Literal[
    "specialist_prompt",
    "provider_payload",
    "storyboard_detail",
    "repair_prompt",
    "fallback_prompt",
]


class V2PromptRegistryEntry(BaseModel):
    prompt_id: str
    prompt_version: str
    owner: str
    scope: V2PromptRegistryScope
    stage: str
    source_path: str
    output_schema: str | None = None
    allowed_runtime: list[str] = Field(default_factory=lambda: ["mock", "real"])
    deprecated: bool = False
    title: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2PromptRegistryRef(BaseModel):
    prompt_id: str
    prompt_version: str
    owner: str
    scope: V2PromptRegistryScope
    stage: str
    source_path: str
    registry_revision: str = "2026-07-07"


class V2PromptRenderIdentity(BaseModel):
    workflow_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    media_type: str | None = None
    specialist: str | None = None
    path_kind: str = "normal"


class V2PromptRenderResult(BaseModel):
    prompt_registry_ref: V2PromptRegistryRef
    render_identity: V2PromptRenderIdentity
    prompt_text: str
    prompt_hash: str
    render_context_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2PromptContentProfile(BaseModel):
    profile_id: str
    profile_version: str
    prompt_id: str
    stage: str
    target_min_words: int | None = None
    target_max_words: int | None = None
    required_sections: list[str] = Field(default_factory=list)
    quality_rules: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    example_blocks: list[str] = Field(default_factory=list)
    anti_example_blocks: list[str] = Field(default_factory=list)


class V2PromptContentProfileMetadata(BaseModel):
    profile_id: str
    profile_version: str
    prompt_id: str
    stage: str
    sections: list[str] = Field(default_factory=list)
    word_count: int
    budget_status: Literal["within_budget", "under_minimum", "over_maximum"]


class V2PromptLineage(BaseModel):
    prompt_registry_ref: dict[str, Any]
    prompt_id: str
    prompt_version: str
    workflow_id: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    media_type: str | None = None
    specialist: str | None = None
    path_kind: str = "normal"
    prompt_hash: str
    render_context_hash: str
    source_path: str
    owner: str
    scope: V2PromptRegistryScope
    stage: str
