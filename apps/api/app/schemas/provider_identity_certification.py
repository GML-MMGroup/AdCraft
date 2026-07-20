from typing import Any, Literal

from pydantic import BaseModel, Field


IdentityCertificationStatus = Literal[
    "certified",
    "experimental",
    "uncertified",
    "revoked",
]
IdentityCertificationResultStatus = Literal[
    "not_required",
    "certified",
    "experimental",
    "uncertified",
    "revoked",
]


class IdentityCertificationRecord(BaseModel):
    certification_id: str
    provider: str
    model_id: str
    media_type: str
    node_type: str
    reference_semantic_type: str
    reference_role: str | None = None
    status: IdentityCertificationStatus
    certification_level: str = "strict_identity"
    certified_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    test_report_id: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityCertificationLookupRequest(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    media_type: str
    provider: str
    model_id: str
    reference_mode: Literal["best_effort", "strict"] = "strict"
    asset_references: list[dict[str, Any]] = Field(default_factory=list)


class IdentityCertificationResult(BaseModel):
    required: bool = False
    mode: str = "best_effort"
    status: IdentityCertificationResultStatus = "not_required"
    provider: str | None = None
    model_id: str | None = None
    media_type: str | None = None
    node_type: str | None = None
    reference_semantic_types: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    certification_lookup_keys: list[dict[str, Any]] = Field(default_factory=list)
    certification_ids: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ProviderCertificationListResponse(BaseModel):
    records: list[IdentityCertificationRecord] = Field(default_factory=list)
