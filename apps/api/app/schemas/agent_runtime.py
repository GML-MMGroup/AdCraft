"""Canonical internal contracts shared by Python and the Pi Agent runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_operation_contexts import (
    AgentCanvasSpecialistName,
    PlanningAgentContext,
)
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_editing import EditingManifestV2, EditingOutputSettingsV2
from app.schemas.agent_canvas_creative_session import ProposedDraftReferenceV2
from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    DesignAssetContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
)


AgentName = Literal[
    "director",
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
]
AgentRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]
AgentEventType = Literal[
    "run_started",
    "output_delta",
    "tool_call",
    "tool_result",
    "heartbeat",
    "run_completed",
    "run_failed",
    "run_cancelled",
]

_PROTOCOL_VERSION = "1"
_MAX_CONTEXT_TEXT = 65_536
_MAX_COLLECTION_ITEMS = 128
_MAX_SAFE_PAYLOAD_BYTES = 65_536
_SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "secret", "token")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class V2ResolvedAgentTarget(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    state_version: int = Field(ge=1)
    target_locator: str = Field(min_length=1, max_length=320)
    target_type: Literal["node", "item", "slot", "asset"]
    node_id: Literal["character-generation", "scene-generation"]
    item_id: str = Field(min_length=1, max_length=160)
    slot_id: str = Field(min_length=1, max_length=240)
    slot_type: Literal[
        "character_main_image",
        "character_three_view",
        "scene_main_image",
        "scene_multi_view_grid",
    ]
    owner_type: Literal["character", "scene"]
    display_name: str = Field(min_length=1, max_length=256)
    requested_scope: Literal["main", "multiview"] = "main"
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    selected_main_asset_locator: str | None = Field(default=None, max_length=320)
    related_multiview_slot_id: str | None = Field(default=None, max_length=240)


class V2AgentTargetCatalog(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    state_version: int = Field(ge=1)
    targets: list[V2ResolvedAgentTarget] = Field(default_factory=list, max_length=256)


def _validate_safe_payload(value: Any, *, field_name: str = "payload") -> Any:
    encoded_size = len(str(value).encode("utf-8"))
    if encoded_size > _MAX_SAFE_PAYLOAD_BYTES:
        raise ValueError(f"{field_name} exceeds the internal payload limit")

    def visit(current: Any, key: str | None = None) -> None:
        if key is not None and any(part in key.casefold() for part in _SENSITIVE_KEY_PARTS):
            raise ValueError(f"{field_name} contains a sensitive field")
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, str) and current.startswith(("/", "\\\\")):
            raise ValueError(f"{field_name} contains an absolute path")

    visit(value)
    return value


class AgentReferenceSummary(_StrictModel):
    asset_id: str = Field(min_length=1, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    semantic_type: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=256)
    media_type: Literal["image", "video", "audio", "text"] | None = None
    description: str = Field(default="", max_length=2_048)


class AgentTargetContext(_StrictModel):
    target_type: str = Field(min_length=1, max_length=80)
    workflow_id: str | None = Field(default=None, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    item_id: str | None = Field(default=None, max_length=160)
    slot_id: str | None = Field(default=None, max_length=160)
    asset_id: str | None = Field(default=None, max_length=160)
    version_id: str | None = Field(default=None, max_length=160)
    owner_type: str | None = Field(default=None, max_length=80)
    owner_display_name: str | None = Field(default=None, max_length=256)
    semantic_type: str | None = Field(default=None, max_length=80)
    current_prompt: str | None = Field(default=None, max_length=16_384)
    selected_version_summary: AgentReferenceSummary | None = None
    reference_asset_summaries: tuple[AgentReferenceSummary, ...] = Field(
        default=(), max_length=_MAX_COLLECTION_ITEMS
    )
    expected_revision: int | None = Field(default=None, ge=1)


class AgentRunContext(_StrictModel):
    operation: str = Field(min_length=1, max_length=120)
    user_input: str = Field(min_length=1, max_length=_MAX_CONTEXT_TEXT)
    conversation_id: str | None = Field(default=None, max_length=160)
    workflow_id: str | None = Field(default=None, max_length=160)
    target: AgentTargetContext | None = None
    screenplay_summary: str | None = Field(default=None, max_length=16_384)
    style_summary: str | None = Field(default=None, max_length=8_192)
    continuity_summary: str | None = Field(default=None, max_length=8_192)
    reference_summaries: tuple[AgentReferenceSummary, ...] = Field(
        default=(), max_length=_MAX_COLLECTION_ITEMS
    )
    constraints: tuple[str, ...] = Field(default=(), max_length=_MAX_COLLECTION_ITEMS)
    system_prompt: str | None = Field(default=None, max_length=32_768)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    contract_schema: dict[str, Any] = Field(default_factory=dict)


class AgentCanvasScriptOutput(BaseModel):
    """Validated Script Writer output while preserving editable structured fields."""

    model_config = ConfigDict(extra="allow")

    content: str = Field(min_length=1, max_length=32_768)


class AgentRunPolicy(_StrictModel):
    max_turns: int = Field(default=8, ge=1, le=64)
    max_tool_calls: int = Field(default=16, ge=0, le=128)
    max_handoffs: int = Field(default=8, ge=0, le=32)
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)
    max_input_bytes: int = Field(default=131_072, ge=1, le=4_194_304)
    max_output_bytes: int = Field(default=262_144, ge=1, le=4_194_304)
    max_event_bytes: int = Field(default=65_536, ge=1, le=1_048_576)


class AgentRunRequest(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    parent_run_id: str | None = Field(default=None, max_length=160)
    agent_name: AgentName
    operation: str = Field(min_length=1, max_length=120)
    deadline_at: datetime
    model_policy_id: str = Field(min_length=1, max_length=160)
    context: PlanningAgentContext | AgentRunContext
    policy: AgentRunPolicy = Field(default_factory=AgentRunPolicy)
    credential_ref: str = Field(default="llm-default", min_length=1, max_length=120)
    contract_name: str | None = Field(default=None, max_length=160)
    contract_schema: dict[str, Any] = Field(default_factory=dict)
    validation_profile: str | None = Field(default=None, max_length=160)
    validation_context: dict[str, Any] = Field(default_factory=dict)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeEvent(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    seq: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=160)
    agent_name: AgentName
    event_type: AgentEventType
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> AgentRuntimeEvent:
        _validate_safe_payload(self.payload)
        if self.event_type == "run_completed":
            AgentRunCompletedPayload.model_validate(self.payload)
        elif self.event_type == "run_failed":
            AgentRunFailedPayload.model_validate(self.payload)
        elif self.event_type == "run_cancelled":
            AgentRunCancelledPayload.model_validate(self.payload)
        return self


class AgentRunCompletedPayload(_StrictModel):
    value: dict[str, Any]
    audit: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_safe_values(self) -> AgentRunCompletedPayload:
        _validate_safe_payload(self.value, field_name="value")
        _validate_safe_payload(self.audit, field_name="audit")
        return self


class AgentRunFailedPayload(_StrictModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1_024)
    retryable: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class AgentRunCancelledPayload(_StrictModel):
    code: Literal["agent_run_cancelled"]
    message: str = Field(min_length=1, max_length=1_024)
    audit: dict[str, Any] = Field(default_factory=dict)


class AgentToolCall(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    tool_call_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_arguments(self) -> AgentToolCall:
        _validate_safe_payload(self.arguments, field_name="arguments")
        return self


class AgentToolResult(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    tool_call_id: str = Field(min_length=1, max_length=160)
    status: Literal["accepted", "completed", "rejected", "failed"]
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1_024)


class AgentStructuredSubmission(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    run_id: str = Field(min_length=1, max_length=160)
    submission_id: str = Field(min_length=1, max_length=160)
    contract_name: str = Field(min_length=1, max_length=160)
    value: dict[str, Any]
    attempt: int = Field(default=1, ge=1, le=2)


class StructuredViolation(_StrictModel):
    code: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=1_024)
    field_path: str | None = Field(default=None, max_length=512)
    expected: Any | None = None
    actual: Any | None = None


class AgentStructuredValidationResult(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    accepted: bool
    normalized_result_id: str | None = Field(default=None, max_length=160)
    normalized_value: dict[str, Any] | None = None
    violations: tuple[StructuredViolation, ...] = Field(default=(), max_length=128)
    repair_allowed: bool = False


class AgentRuntimeHealth(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    runtime_version: str = Field(min_length=1, max_length=80)
    status: Literal["ready", "degraded", "unavailable"]
    mode: Literal["real", "fake"]
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    pi_version: str = Field(min_length=1, max_length=80)
    active_runs: int = Field(default=0, ge=0)


class AgentRuntimeManifest(_StrictModel):
    runtime_version: str = Field(min_length=1, max_length=80)
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AgentRuntimeError(_StrictModel):
    protocol_version: Literal["1"] = _PROTOCOL_VERSION
    code: Literal[
        "agent_runtime_unavailable",
        "agent_protocol_mismatch",
        "agent_model_unavailable",
        "agent_structured_output_invalid",
        "agent_run_budget_exceeded",
        "agent_deadline_exceeded",
        "agent_stream_backpressure_exceeded",
        "agent_tool_not_allowed",
        "agent_target_revision_conflict",
        "agent_run_cancelled",
        "agent_runtime_fake_forbidden",
    ]
    message: str = Field(min_length=1, max_length=1_024)
    retryable: bool = False


class SpecialistDraft(_StrictModel):
    contract_name: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=16_384)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    negative_prompt: str | None = Field(default=None, max_length=8_192)
    constraints: tuple[str, ...] = Field(default=(), max_length=128)
    reference_roles: tuple[str, ...] = Field(default=(), max_length=128)
    warnings: tuple[str, ...] = Field(default=(), max_length=128)


class ConceptOptionV2(_StrictModel):
    option_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=4_096)


class ConceptProposalDraftV2(_StrictModel):
    proposal_kind: Literal[
        "script",
        "product",
        "prop",
        "character",
        "scene",
        "storyboard",
        "video",
        "bgm",
    ]
    specialist_name: AgentCanvasSpecialistName
    options: tuple[ConceptOptionV2, ...] = Field(min_length=1, max_length=4)
    proposed_references: tuple[ProposedDraftReferenceV2, ...] = Field(
        default=(),
        max_length=64,
    )


class AgentNodeIdRefV2(_StrictModel):
    kind: Literal["node_id"] = "node_id"
    node_id: str = Field(min_length=1, max_length=160)


class AgentOperationResultRefV2(_StrictModel):
    kind: Literal["operation_result"] = "operation_result"
    operation_id: str = Field(min_length=1, max_length=160)


AgentNodeRefV2 = Annotated[
    AgentNodeIdRefV2 | AgentOperationResultRefV2,
    Field(discriminator="kind"),
]


class AgentAssetRefV2(_StrictModel):
    kind: Literal["image_asset"] = "image_asset"
    asset_id: str = Field(min_length=1, max_length=160)


class _AgentCommandOperationV2(_StrictModel):
    operation_id: str = Field(min_length=1, max_length=160)


class AgentCreateNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["create_node"] = "create_node"
    node_type: Literal["text", "script", "image", "video", "audio"]
    semantic_role: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str | None = Field(default=None, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, Any] = Field(default_factory=dict)
    model_id: str | None = Field(default=None, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_asset_id: str | None = Field(default=None, max_length=160)
    video_skill_run_id: str | None = Field(default=None, max_length=160)
    placement_hint: AgentPlacementHintV2


class AgentPatchEditableNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["patch_editable_node"] = "patch_editable_node"
    node: AgentNodeRefV2
    title: str | None = Field(default=None, min_length=1, max_length=256)
    summary_prompt: str | None = Field(default=None, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, Any] | None = None
    model_id: str | None = Field(default=None, max_length=160)
    parameters: dict[str, Any] | None = None


class AgentCreateBindingOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["create_binding"] = "create_binding"
    source: AgentNodeRefV2 | AgentAssetRefV2
    target: AgentNodeRefV2
    binding_kind: Literal[
        "brief_context",
        "script_context",
        "image_reference",
        "video_reference",
        "audio_reference",
    ]
    required: bool = True
    display_order: int = Field(default=0, ge=0)


class AgentDeleteBindingOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["delete_binding"] = "delete_binding"
    binding_id: str = Field(min_length=1, max_length=160)


class AgentDeleteNodeOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["delete_node"] = "delete_node"
    node: AgentNodeRefV2


class AgentMaterializeProposalOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["materialize_proposal"] = "materialize_proposal"
    proposal_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    placement_hint: AgentPlacementHintV2


class AgentForkReadyMediaOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["fork_ready_media"] = "fork_ready_media"
    source_node: AgentNodeRefV2
    title: str = Field(min_length=1, max_length=256)
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    model_id: str | None = Field(default=None, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    placement_hint: AgentPlacementHintV2


class AgentRequestNodeRunOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["request_node_run"] = "request_node_run"
    node: AgentNodeRefV2


class AgentUpdatePlanningTopicOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["update_planning_topic"] = "update_planning_topic"
    skill_run_id: str = Field(min_length=1, max_length=160)
    topic_id: str = Field(min_length=1, max_length=160)
    status: Literal["resolved", "skipped", "not_required"]
    related_nodes: tuple[AgentNodeRefV2, ...] = Field(default=(), max_length=32)


class AgentPrepareCompositionOperationV2(_AgentCommandOperationV2):
    operation_type: Literal["prepare_composition"] = "prepare_composition"
    editing_node: AgentNodeRefV2 | None = None
    title: str | None = Field(default=None, min_length=1, max_length=256)
    ordered_video_nodes: tuple[AgentNodeRefV2, ...] = Field(
        default=(),
        max_length=32,
    )
    bgm_audio_node: AgentNodeRefV2 | None = None
    bgm_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    output: EditingOutputSettingsV2 = Field(default_factory=EditingOutputSettingsV2)
    placement_hint: AgentPlacementHintV2 | None = None

    @model_validator(mode="after")
    def validate_composition_sources(self) -> "AgentPrepareCompositionOperationV2":
        if self.editing_node is None and (self.title is None or self.placement_hint is None):
            raise ValueError("A new composition requires title and placement_hint.")
        if not self.ordered_video_nodes and self.bgm_audio_node is None:
            raise ValueError("Composition requires at least one media source.")
        video_refs = tuple(reference.model_dump_json() for reference in self.ordered_video_nodes)
        if len(set(video_refs)) != len(video_refs):
            raise ValueError("Composition video references must be unique.")
        return self


AgentCommandOperationDraftV2 = Annotated[
    AgentCreateNodeOperationV2
    | AgentPatchEditableNodeOperationV2
    | AgentCreateBindingOperationV2
    | AgentDeleteBindingOperationV2
    | AgentDeleteNodeOperationV2
    | AgentMaterializeProposalOperationV2
    | AgentForkReadyMediaOperationV2
    | AgentRequestNodeRunOperationV2
    | AgentUpdatePlanningTopicOperationV2
    | AgentPrepareCompositionOperationV2,
    Field(discriminator="operation_type"),
]


class AgentPrepareCompositionResultV2(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    editing_node: CanvasNodeV2
    manifest: EditingManifestV2
    bindings: tuple[CanvasBindingV2, ...]
    semantic_revision: int = Field(ge=1)
    events_cursor: int = Field(ge=0)
    replayed: bool = False


_NODE_RESULT_OPERATIONS = {
    "create_node",
    "materialize_proposal",
    "fork_ready_media",
}


def _operation_result_references(value: Any) -> tuple[str, ...]:
    references: list[str] = []

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            if current.get("kind") == "operation_result":
                operation_id = current.get("operation_id")
                if isinstance(operation_id, str):
                    references.append(operation_id)
            for child in current.values():
                visit(child)
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)

    visit(value)
    return tuple(references)


class AgentCommandPlanDraftV2(_StrictModel):
    operations: tuple[AgentCommandOperationDraftV2, ...] = Field(
        min_length=1,
        max_length=8,
    )
    continuation_requested: bool = False

    @model_validator(mode="after")
    def validate_operation_graph(self) -> "AgentCommandPlanDraftV2":
        all_operations = {operation.operation_id: operation for operation in self.operations}
        if len(all_operations) != len(self.operations):
            raise ValueError("Command operation_id values must be unique.")
        seen: dict[str, _AgentCommandOperationV2] = {}
        for operation in self.operations:
            operation_payload = operation.model_dump(mode="python")
            _validate_safe_payload(operation_payload, field_name="command operation")
            for reference_id in _operation_result_references(operation_payload):
                if reference_id not in seen:
                    raise ValueError("Command operation result reference must point backward.")
                if seen[reference_id].operation_type not in _NODE_RESULT_OPERATIONS:
                    raise ValueError("Referenced command operation does not produce a node.")
            seen[operation.operation_id] = operation
        return self


AgentCommandRiskV2 = Literal[
    "reversible_authoring",
    "destructive_authoring",
    "external_effect",
]
AgentCommandPlanStatusV2 = Literal[
    "pending_confirmation",
    "applying",
    "applied",
    "rejected",
    "superseded",
    "failed",
]


class AgentCommandPlanCreateV2(AgentCommandPlanDraftV2):
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    base_workflow_revision: int = Field(ge=1)
    risk: AgentCommandRiskV2
    confirmation_required: bool
    target_summary: str = Field(default="", max_length=4_000)


class AgentCommandPlanV2(AgentCommandPlanCreateV2):
    plan_id: str = Field(min_length=1, max_length=160)
    operation_fingerprint: str = Field(min_length=1, max_length=128)
    status: AgentCommandPlanStatusV2
    supersedes_plan_id: str | None = Field(default=None, max_length=160)
    replacement_plan_id: str | None = Field(default=None, max_length=160)
    actor: Literal["agent", "user", "system"] = "agent"
    created_at: datetime
    updated_at: datetime


class AgentCommandReplanResultV2(_StrictModel):
    original_plan_id: str = Field(min_length=1, max_length=160)
    replacement_plan: AgentCommandPlanV2
    confirmation_transferred: bool


class AgentOperationResultV2(_StrictModel):
    operation_id: str = Field(min_length=1, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    binding_id: str | None = Field(default=None, max_length=160)
    execution_id: str | None = Field(default=None, max_length=160)
    status: Literal["applied", "queued", "failed"]
    error_code: str | None = Field(default=None, max_length=160)


class AgentCommandTransactionResultV2(_StrictModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    operation_results: tuple[AgentOperationResultV2, ...] = Field(max_length=8)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    updated_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    deleted_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    deleted_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)
    post_commit_run_node_ids: tuple[str, ...] = Field(default=(), max_length=8)


class AgentActionEnvelopeV2(_StrictModel):
    assistant_message: str = Field(min_length=1, max_length=4_000)
    specialist_handoff: AgentCanvasSpecialistName | None = None
    proposal: ConceptProposalDraftV2 | None = None
    command_plan: AgentCommandPlanDraftV2 | None = None
    auto_continue_requested: bool = False


class AdMediaSpecialistDraftV2(_StrictModel):
    semantic_role: Literal[
        "product_main",
        "product_view_board",
        "prop_main",
        "character_main",
        "character_turnaround",
        "scene_design_board",
        "storyboard_grid",
        "storyboard_video_segment",
        "bgm",
    ]
    title: str = Field(min_length=1, max_length=256)
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: (
        DesignAssetContentV2
        | SceneDesignBoardContentV2
        | StoryboardGridContentV2
        | VideoSegmentContentV2
        | BgmContentV2
    )


class SpecialistDirectResponseV2(_StrictModel):
    summary: str = Field(min_length=1, max_length=4_000)
