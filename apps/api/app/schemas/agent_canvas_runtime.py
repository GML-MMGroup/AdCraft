"""Strict public and persistence contracts for Agent Canvas execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import (
    CanvasCreativeRoleV2,
    CanvasInputRoleV2,
    CanvasNodeErrorV2,
    CanvasNodeStatusV2,
    CanvasNodeTypeV2,
    RoleContractVersionV2,
)


CanvasRunScopeV2 = Literal["all_drafts", "selected_nodes"]
CanvasExecutionStatusV2 = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "partial_completed",
    "failed",
    "cancelled",
]
NodeRuntimePhaseV2 = Literal[
    "waiting_for_input",
    "blocked_by_upstream",
    "queued",
    "running",
    "waiting_provider",
    "recovering",
    "publishing",
]


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _contains_forbidden_transport(value: object, *, key: str | None = None) -> bool:
    forbidden_key_fragments = ("api_key", "token", "secret", "credential", "authorization")
    if key and any(fragment in key.lower() for fragment in forbidden_key_fragments):
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return (
            normalized.startswith(("data:", "file://", "/"))
            or "x-amz-signature=" in normalized
            or "signature=" in normalized
            and "http" in normalized
        )
    if isinstance(value, dict):
        return any(
            _contains_forbidden_transport(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_forbidden_transport(item) for item in value)
    return False


class EffectiveMediaParameterSnapshotV2(_RuntimeModel):
    requested: dict[str, JsonValue] = Field(default_factory=dict)
    effective: dict[str, JsonValue] = Field(default_factory=dict)
    normalizations: tuple[str, ...] = ()
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=320)
    capability_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_sanitized_values(self) -> "EffectiveMediaParameterSnapshotV2":
        if _contains_forbidden_transport(self.requested) or _contains_forbidden_transport(
            self.effective
        ):
            raise ValueError("Media parameters cannot contain transport values.")
        return self


class NodeRunBindingSnapshotV2(_RuntimeModel):
    binding_id: str = Field(min_length=1, max_length=160)
    input_role: CanvasInputRoleV2
    order: int = Field(ge=0)
    required: bool
    source_kind: Literal["node_output", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int | None = Field(default=None, ge=1)


class NodeRunIntentSnapshotV2(_RuntimeModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    role_contract_version: RoleContractVersionV2
    summary_prompt: str | None = Field(default=None, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_selection_mode: Literal["default", "explicit"]
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    requested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...] = ()
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_sanitized_snapshot(self) -> "NodeRunIntentSnapshotV2":
        payload = self.model_dump(mode="json")
        if _contains_forbidden_transport(payload):
            raise ValueError("Run intent snapshots cannot contain transport values.")
        return self


class PublishedMediaFactsV2(_RuntimeModel):
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    frame_rate: float | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1, max_length=160)


class GeneratedAssetProvenanceV2(_RuntimeModel):
    node_run_snapshot_id: str = Field(min_length=1, max_length=160)
    input_manifest_id: str | None = Field(default=None, min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    compiled_prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_registry_ref: str = Field(min_length=1, max_length=320)
    prompt_registry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=320)
    provider_task_id: str | None = Field(default=None, max_length=160)
    requested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    effective_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    normalizations: tuple[str, ...] = ()
    source_asset_version_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_sanitized_provenance(self) -> "GeneratedAssetProvenanceV2":
        if _contains_forbidden_transport(self.model_dump(mode="json")):
            raise ValueError("Generated asset provenance cannot contain transport values.")
        return self


class CanvasRunRequestV2(_RuntimeModel):
    scope: CanvasRunScopeV2
    node_ids: tuple[str, ...] = ()
    retry_failed: bool = False
    source_action: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self) -> "CanvasRunRequestV2":
        if self.scope == "selected_nodes" and not self.node_ids:
            raise ValueError("selected_nodes requires at least one node ID")
        if self.scope == "all_drafts" and (self.node_ids or self.retry_failed):
            raise ValueError("all_drafts does not accept node IDs or failed retry")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("node IDs must be unique")
        return self


class CanvasRunSkippedNodeV2(_RuntimeModel):
    node_id: str
    reason: str


class CanvasRunAcceptedV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    status: CanvasExecutionStatusV2
    accepted_node_ids: tuple[str, ...] = ()
    joined_node_ids: tuple[str, ...] = ()
    skipped: tuple[CanvasRunSkippedNodeV2, ...] = ()
    waiting_node_ids: tuple[str, ...] = ()
    run_intent_snapshot_ids: dict[str, str] = Field(default_factory=dict)
    events_cursor: int = Field(default=0, ge=0)


class CanvasExecutionRecordV2(_RuntimeModel):
    execution_id: str
    workflow_id: str
    status: CanvasExecutionStatusV2
    scope: CanvasRunScopeV2
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime


class CanvasExecutionMembershipV2(_RuntimeModel):
    member_id: str
    execution_id: str
    workflow_id: str
    node_id: str
    state: Literal[
        "queued",
        "waiting",
        "blocked",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ]
    phase: NodeRuntimePhaseV2 | None = None
    attempt_no: int = Field(default=0, ge=0)
    waiting_for_node_ids: tuple[str, ...] = ()
    provider_task_id: str | None = None
    run_intent_snapshot_id: str | None = None
    run_intent_snapshot: NodeRunIntentSnapshotV2 | None = None
    run_intent_snapshot_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    resolved_input_manifest_id: str | None = None
    resolved_input_manifest: dict[str, JsonValue] | None = None
    resolved_input_manifest_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None
    omitted_optional_inputs: tuple[dict[str, JsonValue], ...] = ()
    lease_generation: int = Field(default=0, ge=0)
    prompt_metadata: dict[str, object] = Field(default_factory=dict)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime


class ResolvedModelExecutionV1(_RuntimeModel):
    """Secret-free model snapshot frozen for one Canvas node attempt."""

    model_ref: str = Field(min_length=3, max_length=320)
    provider_id: str = Field(min_length=1, max_length=80)
    provider_model_id: str = Field(min_length=1, max_length=320)
    capability: Literal["text", "image", "video", "audio"]
    provider_protocol: str = Field(min_length=1, max_length=80)
    credential_capability: Literal["text", "image", "video", "audio"] | None = None
    credential_revision: int = Field(ge=1)
    catalog_revision: int = Field(ge=1)
    capability_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def use_capability_for_legacy_snapshots(self) -> "ResolvedModelExecutionV1":
        if self.credential_capability is None:
            self.credential_capability = self.capability
        return self


ProviderReferenceMediaTypeV1 = Literal["text", "image", "video", "audio"]


class ProviderReferenceDeliveryContextV1(_RuntimeModel):
    """Secret-free frozen provider input delivery policy for one attempt."""

    provider_id: str = Field(min_length=1, max_length=80)
    provider_model_id: str = Field(min_length=1, max_length=320)
    provider_protocol: str = Field(min_length=1, max_length=80)
    target_capability: Literal["image", "video", "audio"]
    accepted_input_types: tuple[ProviderReferenceMediaTypeV1, ...]
    reference_limits: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def validate_reference_limits(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        reference_limits = value.get("reference_limits", {})
        if not isinstance(reference_limits, dict):
            return value
        allowed = {"image", "video", "audio"}
        if any(key not in allowed for key in reference_limits):
            raise ValueError("Reference limits contain an unsupported media type.")
        if any(
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
            for limit in reference_limits.values()
        ):
            raise ValueError("Reference limits must be non-negative integers.")
        return value


class CanvasRunCancelRequestV2(_RuntimeModel):
    reason: str = Field(default="user_cancelled", min_length=1, max_length=512)


class CanvasRunCancelResponseV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    status: Literal["cancelled"]
    cancelled_node_ids: tuple[str, ...] = ()
    events_cursor: int = Field(ge=0)


class NodeRuntimeV2(_RuntimeModel):
    node_id: str
    visible_status: CanvasNodeStatusV2
    phase: NodeRuntimePhaseV2 | None = None
    execution_id: str | None = None
    provider_task_id: str | None = None
    run_intent_snapshot_id: str | None = None
    input_manifest_id: str | None = None
    effective_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    normalizations: tuple[str, ...] = ()
    omitted_optional_inputs: tuple[dict[str, JsonValue], ...] = ()
    waiting_reason: str | None = None
    missing_required_source_node_ids: tuple[str, ...] = ()
    waiting_for_node_ids: tuple[str, ...] = ()
    blocked_by_node_ids: tuple[str, ...] = ()
    attempt_no: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: CanvasNodeErrorV2 | None = None


class CanvasRuntimeSnapshotV2(_RuntimeModel):
    workflow_id: str
    active_execution_id: str | None = None
    execution_status: CanvasExecutionStatusV2 | None = None
    node_runtime: dict[str, NodeRuntimeV2] = Field(default_factory=dict)
    queued_node_ids: tuple[str, ...] = ()
    working_node_ids: tuple[str, ...] = ()
    waiting_node_ids: tuple[str, ...] = ()
    ready_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    events_cursor: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CanvasProviderModelCapabilityV2(_RuntimeModel):
    provider: str
    model_id: str
    output_type: Literal["image", "video", "audio"]
    accepted_input_types: frozenset[Literal["text", "image", "video", "audio"]]
    max_references: int = Field(ge=0)
    reference_limits: dict[Literal["image", "video", "audio"], int] = Field(default_factory=dict)
    supported_parameters: frozenset[str] = frozenset()
    supported_aspect_ratios: tuple[str, ...] = ()
    duration_range_seconds: tuple[float, float] | None = None
    pixel_bounds: tuple[int, int] | None = None
    available: bool
    unavailable_reason: str | None = None
    supports_native_audio: bool = False
    capability_revision: int = Field(default=1, ge=1)


class CanvasProviderModelCapabilityListV2(_RuntimeModel):
    items: tuple[CanvasProviderModelCapabilityV2, ...]


class BindingCapabilityDecisionV2(_RuntimeModel):
    accepted: bool
    target_node_id: str
    selected_model_id: str | None = None
    required_input_types: frozenset[Literal["text", "image", "video", "audio"]]
    compatible_model_ids: tuple[str, ...] = ()
    switch_model_required: bool = False


class NodeExecutionLeaseV2(_RuntimeModel):
    workflow_id: str
    execution_id: str
    node_id: str
    owner_id: str
    generation: int = Field(ge=1)
    state: Literal["claimed", "completed", "released", "expired"]
    heartbeat_at: datetime
    expires_at: datetime


class CanvasProviderTaskV2(_RuntimeModel):
    task_id: str
    workflow_id: str
    execution_id: str
    node_id: str
    provider: str
    remote_task_id: str | None = None
    status: Literal[
        "submitted",
        "waiting",
        "recovering",
        "succeeded",
        "failed",
        "cancelled",
    ]
    lease_generation: int = Field(ge=1)
    next_poll_at: datetime | None = None
    recovery_deadline: datetime
    result_descriptor: dict[str, object] = Field(default_factory=dict)
    error: CanvasNodeErrorV2 | None = None


class CanvasRuntimeEventV2(_RuntimeModel):
    sequence_no: int = Field(ge=1)
    workflow_id: str
    event_type: str
    project_id: str | None = None
    execution_id: str | None = None
    node_id: str | None = None
    binding_id: str | None = None
    asset_id: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    action_id: str | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class CanvasRuntimeEventListV2(_RuntimeModel):
    items: tuple[CanvasRuntimeEventV2, ...]
    next_cursor: int = Field(ge=0)
