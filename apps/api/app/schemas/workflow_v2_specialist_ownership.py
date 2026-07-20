from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.workflow_v2 import V2PromptMaterializerMode, WorkflowV2Specialist


V2SpecialistAction = Literal[
    "materialize_item_slots",
    "materialize_shot_cells",
    "materialize_shot_video",
    "revise_prompt",
    "revise_and_generate",
    "update_shot_summary",
    "build_timeline",
    "revise_timeline",
    "free_generate",
]


class V2SpecialistOwnershipScope(BaseModel):
    ownership_scope_id: str
    specialist: WorkflowV2Specialist
    node_types: list[str] = Field(default_factory=list)
    item_types: list[str] = Field(default_factory=list)
    slot_types: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    is_llm_specialist: bool = True
    free_output_media_types: list[str] = Field(default_factory=list)


class V2SpecialistSlotPlan(BaseModel):
    slot_id: str
    slot_type: str
    item_id: str
    summary_prompt: str
    specialist_prompt: str
    provider_prompt: str | None = None
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    detail_prompts: dict[str, Any] = Field(default_factory=dict)
    prompt_contract_name: str
    prompt_contract_version: str
    quality_notes: list[str] = Field(default_factory=list)

    @field_validator(
        "slot_id",
        "slot_type",
        "item_id",
        "summary_prompt",
        "specialist_prompt",
        "prompt_contract_name",
        "prompt_contract_version",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("provider_prompt", "negative_prompt", "negative_constraints", mode="after")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("reference_asset_ids", "quality_notes", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in (str(raw).strip() for raw in value) if item))


class V2SpecialistOwnedPlan(BaseModel):
    specialist: WorkflowV2Specialist
    model_id: str | None = None
    ownership_scope_id: str
    target_node_id: str
    target_item_id: str
    action: str
    slot_plans: list[V2SpecialistSlotPlan] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    materializer_mode: V2PromptMaterializerMode
    profile_version: str


class V2SpecialistPromptProfile(BaseModel):
    profile_id: str
    specialist: WorkflowV2Specialist
    profile_version: str
    model_env_key: str | None = None
    allowed_node_types: list[str] = Field(default_factory=list)
    allowed_item_types: list[str] = Field(default_factory=list)
    allowed_slot_types: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    skill_pack_ids: list[str] = Field(default_factory=list)
    output_contracts: list[str] = Field(default_factory=list)
    quality_gate_id: str
    is_llm_specialist: bool = True


class V2SpecialistOwnershipValidationResult(BaseModel):
    valid: bool
    specialist: str | None = None
    ownership_scope_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    violations: list[str] = Field(default_factory=list)


class V2SlotPromptContext(BaseModel):
    workflow_id: str
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    specialist: WorkflowV2Specialist
    campaign_summary: dict[str, Any] = Field(default_factory=dict)
    item_summary: dict[str, Any] = Field(default_factory=dict)
    own_summary_prompt: str | None = None
    own_specialist_prompt: str | None = None
    own_provider_prompt: str | None = None
    own_detail_prompts: dict[str, Any] = Field(default_factory=dict)
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    reference_version_ids: list[str] = Field(default_factory=list)
    dependency_asset_summaries: list[dict[str, Any]] = Field(default_factory=list)
    lightweight_owner_labels: dict[str, str] = Field(default_factory=dict)


class V2ProviderPromptCompilationResult(BaseModel):
    provider_prompt: str | None = None
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    reference_version_ids: list[str] = Field(default_factory=list)
    provider_payload_metadata: dict[str, Any] = Field(default_factory=dict)


class V2PromptContaminationCheckResult(BaseModel):
    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    evidence: list[str] = Field(default_factory=list)
    forbidden_evidence: list[str] = Field(default_factory=list)
    sibling_prompt_fingerprint_evidence: list[dict[str, Any]] = Field(default_factory=list)
    own_prompt_fingerprint: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)


class V2PromptIsolationAudit(BaseModel):
    valid: bool
    slot_id: str | None = None
    slot_type: str | None = None
    stage: str = "slot_context"
    error_code: str | None = None
    error_message: str | None = None
    own_prompt_fingerprint: str | None = None
    serialized_payload_fingerprint: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    allowed_reference_asset_ids: list[str] = Field(default_factory=list)
    forbidden_evidence: list[str] = Field(default_factory=list)
    sibling_prompt_fingerprint_evidence: list[dict[str, Any]] = Field(default_factory=list)
