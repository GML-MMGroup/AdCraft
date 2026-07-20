from typing import Any, Literal

from pydantic import BaseModel, Field

PromptOptimizationMode = Literal["optimize_only", "generate", "local_revision"]


class PromptOptimizationRequest(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    mode: PromptOptimizationMode
    user_prompt: str | None = None
    system_suggested_prompt: str | None = None
    materialized_prompt: str | None = None
    override_prompt: str | None = None
    director_context: dict[str, Any] = Field(default_factory=dict)
    resolved_input_context: dict[str, Any] = Field(default_factory=dict)
    resolved_input_assets: list[dict[str, Any]] = Field(default_factory=list)
    upstream_structured_outputs: dict[str, Any] = Field(default_factory=dict)
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    provider_media_type: str | None = None
    provider_capability_summary: dict[str, Any] = Field(default_factory=dict)
    reference_policy_summary: dict[str, Any] = Field(default_factory=dict)
    identity_certification_summary: dict[str, Any] = Field(default_factory=dict)
    selected_provider: str | None = None
    target_context: dict[str, Any] = Field(default_factory=dict)
    allow_optimizer_fallback: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class PromptOptimizationResult(BaseModel):
    optimized_generation_prompt: str
    provider_prompt: str
    negative_prompt: str | None = None
    asset_references: list[str] = Field(default_factory=list)
    reference_requirements: list[dict[str, Any]] = Field(default_factory=list)
    provider_parameters: dict[str, Any] = Field(default_factory=dict)
    continuity_constraints: list[str] = Field(default_factory=list)
    quality_notes: str | None = None
    optimizer_agent: str
    selected_skill_ids: list[str] = Field(default_factory=list)
    mock_mode: bool = False
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class PromptOptimizerTraceMetadata(BaseModel):
    trace_role: Literal["prompt_optimizer"] = "prompt_optimizer"
    workflow_id: str
    node_id: str
    node_type: str
    mode: PromptOptimizationMode
    optimizer_agent: str
    selected_skill_ids: list[str] = Field(default_factory=list)
    model_id: str | None = None
    mock_mode: bool = False
