"""Private authority commands for durable Agent Canvas execution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import (
    CanvasExecutionRecordV2,
    CanvasRunScopeV2,
    NodeRunBindingSnapshotV2,
    ResolvedModelExecutionV2,
)
from app.schemas.agent_canvas_execution_mode import (
    CanvasExecutionModeV2,
    CanvasSemanticExtractionModeV2,
)


class _AuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasExecutionMemberIntentV2(_AuthorityModel):
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    member_order: int = Field(ge=0)
    frozen_node: dict[str, JsonValue]
    binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...] = ()
    snapshot_id: str = Field(min_length=1, max_length=160)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_asset_digests: dict[str, str] = Field(default_factory=dict)
    parameter_normalizations: tuple[str, ...] = ()
    execution_mode: CanvasExecutionModeV2 = "agent_assisted"
    semantic_extraction: CanvasSemanticExtractionModeV2 = "agent"

    @model_validator(mode="after")
    def validate_asset_digests(self) -> "CanvasExecutionMemberIntentV2":
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.expected_source_asset_digests.values()
        ):
            raise ValueError("Source Asset digests must be lowercase SHA-256 values.")
        return self


class CanvasExecutionStartCommandV2(_AuthorityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    expected_workflow_revision: int = Field(ge=1)
    scope: CanvasRunScopeV2
    idempotency_key: str = Field(min_length=1, max_length=320)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    member_intents: tuple[CanvasExecutionMemberIntentV2, ...]
    created_at: datetime

    @model_validator(mode="after")
    def validate_distinct_members(self) -> "CanvasExecutionStartCommandV2":
        node_ids = [intent.node_id for intent in self.member_intents]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Execution member intents must have distinct Node IDs.")
        orders = [intent.member_order for intent in self.member_intents]
        if orders != list(range(len(orders))):
            raise ValueError("Execution member order must be contiguous from zero.")
        return self


class CanvasExecutionStartResultV2(_AuthorityModel):
    execution: CanvasExecutionRecordV2
    accepted_node_ids: tuple[str, ...] = ()
    joined_node_ids: tuple[str, ...] = ()
    snapshot_ids: dict[str, str] = Field(default_factory=dict)


class ProviderSubmissionIntentV2(_AuthorityModel):
    intent_id: str = Field(min_length=1, max_length=160)
    logical_operation_key: str = Field(min_length=1, max_length=320)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=320)
    attempt_no: int = Field(ge=1)
    supports_idempotency_token: bool
    supports_remote_task_lookup: bool
    frozen_model_resolution: ResolvedModelExecutionV2 | None = None
    provider_idempotency_token: str | None = Field(default=None, max_length=320)
    remote_task_id: str | None = Field(default=None, max_length=320)
    provider_task_id: str | None = Field(default=None, max_length=160)
    state: Literal["prepared", "submitted", "outcome_unknown", "completed"]
    created_at: datetime
    updated_at: datetime


class PreparedContentObjectV2(_AuthorityModel):
    storage_key: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: Literal["image", "video", "audio"]
    mime_type: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=512)
    media_facts: dict[str, JsonValue] = Field(default_factory=dict)


class PreparedPostReadyEffectV2(_AuthorityModel):
    effect_type: Literal[
        "persist_script_document",
        "persist_text_document",
        "advance_storyboard_progression",
    ]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class PreparedNodeResultV2(_AuthorityModel):
    logical_result_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    publication_intent_id: str | None = Field(default=None, min_length=1, max_length=160)
    structured_content: dict[str, JsonValue] | None = None
    prepared_object: PreparedContentObjectV2 | None = None
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    asset_display_name: str | None = Field(default=None, max_length=512)
    asset_source_type: Literal["generated", "derived"] = "generated"
    asset_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    provider_task_id: str | None = Field(default=None, max_length=160)
    post_ready_effects: tuple[PreparedPostReadyEffectV2, ...] = ()


class CanvasResultPublicationIntentV1(_AuthorityModel):
    """Durable handoff between verified local media and terminal publication."""

    intent_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    logical_result_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_snapshot_id: str = Field(min_length=1, max_length=160)
    source_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_storage_key: str = Field(min_length=1, max_length=1024)
    expected_object_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    planned_result: PreparedNodeResultV2
    prepared_result: PreparedNodeResultV2 | None = None
    state: Literal["preparing", "prepared", "committed", "abandoned"]
    attempt_count: int = Field(ge=0, le=16)
    next_attempt_at: datetime
    recovery_deadline: datetime
    last_error_code: str | None = Field(default=None, min_length=1, max_length=160)
    committed_receipt_id: str | None = Field(default=None, min_length=1, max_length=160)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_publication_identity(self) -> "CanvasResultPublicationIntentV1":
        if self.expected_storage_key.startswith(("/", "file:", "data:")):
            raise ValueError("Publication storage key must be a managed relative key.")
        if ".." in self.expected_storage_key.split("/"):
            raise ValueError("Publication storage key must not escape managed storage.")
        if self.recovery_deadline < self.created_at:
            raise ValueError("Publication recovery deadline must follow intent creation.")
        if self.next_attempt_at > self.recovery_deadline:
            raise ValueError("Publication retry cannot be scheduled after its deadline.")
        self._validate_result(self.planned_result, require_measured=False)
        if self.state in {"prepared", "committed"} and self.prepared_result is None:
            raise ValueError("Prepared publication state requires a prepared result.")
        if self.state == "preparing" and self.prepared_result is not None:
            raise ValueError("Preparing publication state cannot claim a prepared result.")
        if self.prepared_result is not None:
            self._validate_result(self.prepared_result, require_measured=True)
        if self.state == "committed" and self.committed_receipt_id is None:
            raise ValueError("Committed publication state requires a receipt identity.")
        if self.state != "committed" and self.committed_receipt_id is not None:
            raise ValueError("Only committed publication state may identify a receipt.")
        _reject_unsafe_publication_values(self.planned_result.model_dump(mode="python"))
        if self.prepared_result is not None:
            _reject_unsafe_publication_values(self.prepared_result.model_dump(mode="python"))
        return self

    def _validate_result(
        self,
        result: PreparedNodeResultV2,
        *,
        require_measured: bool,
    ) -> None:
        if (
            result.logical_result_key != self.logical_result_key
            or result.payload_digest != self.payload_digest
            or result.publication_intent_id != self.intent_id
            or result.prepared_object is None
            or result.prepared_object.storage_key != self.expected_storage_key
            or result.prepared_object.sha256 != self.expected_object_sha256
        ):
            raise ValueError("Publication result identity must match its durable intent.")
        if require_measured and not result.prepared_object.media_facts:
            raise ValueError("Prepared publication result requires measured media facts.")


def _reject_unsafe_publication_values(value: object, *, key: str | None = None) -> None:
    sensitive_keys = {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
    if key is not None and key.lower() in sensitive_keys:
        raise ValueError("Publication intent cannot persist credentials or secrets.")
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            _reject_unsafe_publication_values(nested_value, key=str(nested_key))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_unsafe_publication_values(item)
        return
    if isinstance(value, str) and value.startswith(("/", "file:", "data:")):
        raise ValueError("Publication intent cannot persist local paths or raw data URLs.")


class CanvasExecutionResultCommitCommandV2(_AuthorityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    lease_owner_id: str = Field(min_length=1, max_length=160)
    lease_generation: int = Field(ge=1)
    logical_result_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    publication_intent_id: str | None = Field(default=None, min_length=1, max_length=160)
    publication_recovery_attempt: int | None = Field(default=None, ge=0, le=16)
    provider_task_id: str | None = Field(default=None, max_length=160)
    outcome: Literal["succeeded", "failed", "cancelled"]
    prepared_result: PreparedNodeResultV2 | None = None
    error: CanvasNodeErrorV2 | None = None
    committed_at: datetime

    @model_validator(mode="after")
    def validate_outcome_payload(self) -> "CanvasExecutionResultCommitCommandV2":
        if self.outcome == "succeeded" and self.prepared_result is None:
            raise ValueError("A successful result requires prepared output.")
        if self.prepared_result is not None and (
            self.prepared_result.logical_result_key != self.logical_result_key
            or self.prepared_result.payload_digest != self.payload_digest
            or self.prepared_result.publication_intent_id != self.publication_intent_id
        ):
            raise ValueError("Prepared output identity must match the commit command.")
        if self.outcome != "succeeded" and self.error is None:
            raise ValueError("A failed or cancelled result requires a safe error.")
        if self.publication_recovery_attempt is not None and self.publication_intent_id is None:
            raise ValueError("Publication recovery requires a durable intent identity.")
        return self


class CanvasExecutionResultCommitReceiptV2(_AuthorityModel):
    commit_id: str = Field(min_length=1, max_length=160)
    logical_result_key: str = Field(min_length=1, max_length=320)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["succeeded", "failed", "cancelled"]
    asset_id: str | None = None
    version_id: str | None = None
    event_cursor: int = Field(ge=0)
    committed_at: datetime


class CanvasPostReadyEffectV2(_AuthorityModel):
    effect_id: str = Field(min_length=1, max_length=160)
    effect_type: Literal[
        "persist_script_document",
        "persist_text_document",
        "advance_storyboard_progression",
    ]
    source_commit_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    status: Literal["queued", "running", "completed", "failed"]
    attempt_no: int = Field(ge=0)
    lease_owner_id: str | None = None
    lease_generation: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    error: CanvasNodeErrorV2 | None = None
    created_at: datetime
    updated_at: datetime
