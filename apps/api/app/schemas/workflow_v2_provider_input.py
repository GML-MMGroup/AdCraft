from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class V2ProviderInputBlueprint(BaseModel):
    blueprint_id: str
    slot_type: str
    media_type: Literal["image", "video", "audio"]
    prompt_sections: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    allowed_reference_roles: list[str] = Field(default_factory=list)
    provider_params: dict[str, Any] = Field(default_factory=dict)


class V2ProviderInputAudit(BaseModel):
    blueprint_id: str
    slot_type: str
    media_type: Literal["image", "video", "audio"]
    negative_constraints: list[str]
    reference_roles: list[str]
    provider_params: dict[str, Any]
    prompt_hash: str


class V2QualityFlag(BaseModel):
    code: str
    severity: Literal["info", "warning"]
    message: str
    source: Literal["provider_input", "provider_result", "metadata"]
