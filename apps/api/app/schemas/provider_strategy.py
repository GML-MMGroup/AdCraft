from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ProviderAttemptStatus = Literal["selected", "skipped", "failed", "succeeded"]
ProviderAttemptReasonCode = Literal[
    "capability_not_satisfied",
    "strict_reference_not_supported",
    "identity_certification_required",
    "identity_certification_revoked",
    "identity_certification_warning",
    "provider_exception",
    "provider_failure",
    "provider_timeout",
    "provider_cooldown",
    "max_attempts_exceeded",
    "success",
]


class ProviderHealthState(BaseModel):
    provider: str
    status: Literal["healthy", "cooldown"] = "healthy"
    consecutive_failures: int = 0
    last_failure_at: str | None = None
    cooldown_until: str | None = None
    last_error_code: str | None = None
    latency_ms: int | None = None
    success_rate: float | None = None
    quota_remaining: int | None = None
    rate_limited_until: str | None = None
    region: str | None = None
    cost_tier: str | None = None


class ProviderCandidate(BaseModel):
    provider: str
    media_type: str
    node_types: list[str] = Field(default_factory=list)
    capability: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    health: ProviderHealthState
    cost_tier: str | None = None
    speed_tier: str | None = None
    quality_tier: str | None = None
    reference_policy: dict[str, Any] = Field(default_factory=dict)
    provider_reference_plan: dict[str, Any] = Field(default_factory=dict)
    identity_certification: dict[str, Any] = Field(default_factory=dict)


class ProviderSelectionRequest(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    media_type: Literal["image", "video", "audio"]
    reference_mode: Literal["best_effort", "strict"] = "strict"
    asset_references: list[dict[str, Any]] = Field(default_factory=list)
    provider: str | None = None
    allow_provider_fallback: bool = True
    provider_hints: dict[str, Any] = Field(default_factory=lambda: {"priority": "capability_first"})

    @field_validator("provider")
    @classmethod
    def strip_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProviderSelectionResult(BaseModel):
    selected_provider: str | None = None
    candidates: list[ProviderCandidate] = Field(default_factory=list)
    fallback_allowed: bool = True
    selection_reason: str = ""
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    provider_hints: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 0
    identity_certifications: list[dict[str, Any]] = Field(default_factory=list)


class ProviderAttemptTrace(BaseModel):
    attempt_index: int
    provider: str
    status: ProviderAttemptStatus
    reason_code: ProviderAttemptReasonCode
    message: str = ""
    reference_policy: dict[str, Any] = Field(default_factory=dict)
    identity_certification: dict[str, Any] = Field(default_factory=dict)
    started_at: str
    ended_at: str
    duration_ms: int = 0


class ProviderFallbackPolicy(BaseModel):
    allow_provider_fallback: bool = True
    max_attempts: int = 2
