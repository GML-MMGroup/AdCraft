from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class V2ProviderPromptContract(BaseModel):
    contract_id: str
    slot_type: str
    media_type: str
    primary_goal: str
    required_prompt_clauses: list[str] = Field(default_factory=list)
    reference_instruction_template: str | None = None
    negative_constraints: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    warning_only_quality_flags: list[str] = Field(default_factory=list)
    technical_failure_rules: list[str] = Field(default_factory=list)

    @field_validator(
        "contract_id",
        "slot_type",
        "media_type",
        "primary_goal",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator(
        "required_prompt_clauses",
        "negative_constraints",
        "forbidden_terms",
        "warning_only_quality_flags",
        "technical_failure_rules",
        mode="after",
    )
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in (str(raw).strip() for raw in value) if item))


class V2ProviderPromptContractResult(BaseModel):
    provider_prompt: str
    provider_prompt_contract: dict[str, Any]
    negative_constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("provider_prompt", mode="after")
    @classmethod
    def strip_provider_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("provider_prompt must not be empty")
        return value


class V2ReferenceRole(BaseModel):
    asset_id: str
    role: str
    required: bool = False
    priority: int = 100
    source: str | None = None

    @field_validator("asset_id", "role", mode="after")
    @classmethod
    def strip_reference_role_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ReferenceDeliveryAudit(BaseModel):
    requested_reference_asset_ids: list[str] = Field(default_factory=list)
    submitted_reference_asset_ids: list[str] = Field(default_factory=list)
    dropped_reference_asset_ids: list[str] = Field(default_factory=list)
    drop_reasons: dict[str, str] = Field(default_factory=dict)
    provider_supports_image_reference: bool | None = None
    provider_supports_video_reference: bool | None = None
    provider_supports_audio_reference: bool | None = None
    provider_reference_confidence: str = "unknown"
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "requested_reference_asset_ids",
        "submitted_reference_asset_ids",
        "dropped_reference_asset_ids",
        "warnings",
        mode="after",
    )
    @classmethod
    def clean_reference_delivery_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in (str(raw).strip() for raw in value) if item))
