from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class V2ProviderExecutionContext(BaseModel):
    """Immutable identity propagated from the scheduler into provider workers."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    execution_id: str
    attempt_id: str
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    media_type: Literal["image", "video", "audio"]
    input_fingerprint: str
    source_action: str
    select_generated: bool = True


class V2ProviderOutputDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    output_index: int = Field(ge=0)
    is_primary: bool
    staging_path: str
    media_type: Literal["image", "video", "audio"]
    mime_type: str
    byte_size: int = Field(gt=0)
    sha256: str
    provider_asset_id: str | None = None


class V2ProviderManifestError(BaseModel):
    code: str
    message: str
    stage: str = "provider_result"
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ProviderResultManifest(BaseModel):
    manifest_version: Literal[1] = 1
    provider_result_id: str
    workflow_id: str
    execution_id: str
    attempt_id: str
    node_id: str
    item_id: str
    slot_id: str
    slot_key: str
    slot_type: str
    media_type: Literal["image", "video", "audio"]
    input_fingerprint: str
    provider_name: str
    provider_model: str | None = None
    source_action: str
    select_generated: bool
    provider_status: Literal["succeeded", "failed"]
    commit_status: Literal["pending", "committed", "rejected"]
    outputs: list[V2ProviderOutputDescriptor] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)
    generation_plan_snapshot: dict[str, Any] = Field(default_factory=dict)
    provider_payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    provider_result_metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_asset_ids: list[str] = Field(default_factory=list)
    canonical_version_ids: list[str] = Field(default_factory=list)
    error: V2ProviderManifestError | None = None
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None = None


class V2ExecutionRecoveryReport(BaseModel):
    workflow_id: str
    committed_slot_ids: list[str] = Field(default_factory=list)
    reset_slot_ids: list[str] = Field(default_factory=list)
    resumed_slot_ids: list[str] = Field(default_factory=list)
    rejected_manifest_ids: list[str] = Field(default_factory=list)
