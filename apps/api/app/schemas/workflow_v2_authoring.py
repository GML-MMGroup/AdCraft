"""Strict persisted authoring contracts for V2 Workflow revisions."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


WorkflowRevisionChangeSource = Literal[
    "create",
    "migration",
    "prompt_edit",
    "structure_edit",
    "reference_change",
    "selected_version_change",
    "script_confirm",
    "timeline_edit",
    "restore",
    "execution_result",
]
WorkflowRevisionCommitStatus = Literal["committed", "no_change", "already_committed"]
WorkflowProjectionState = Literal["clean", "dirty"]

_WINDOWS_DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_BARE_BASE64_MINIMUM_LENGTH = 1_024
_SIGNED_QUERY_KEYS = frozenset(
    {
        "x-amz-algorithm",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "signature",
        "sig",
        "token",
        "expires",
        "expiry",
    }
)


class _AuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowAuthoringCreativeContextV2(_AuthoringModel):
    """Allowlisted high-level creative context for revision history."""

    request: dict[str, JsonValue] = Field(default_factory=dict)
    screenplay: dict[str, JsonValue] = Field(default_factory=dict)
    visual_style: dict[str, JsonValue] = Field(default_factory=dict)
    creative_inventory: dict[str, JsonValue] = Field(default_factory=dict)
    specialist_briefs: dict[str, JsonValue] = Field(default_factory=dict)
    storyboard_config: dict[str, JsonValue] = Field(default_factory=dict)
    planning_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    planning: dict[str, JsonValue] = Field(default_factory=dict)
    script_reconciliation: dict[str, JsonValue] = Field(default_factory=dict)
    visual_style_scope_audit: dict[str, JsonValue] = Field(default_factory=dict)
    expert_brief_plan: dict[str, JsonValue] = Field(default_factory=dict)
    specialist_quality_audit: dict[str, JsonValue] = Field(default_factory=dict)
    planner_warnings: tuple[JsonValue, ...] = ()
    input_asset_descriptors: tuple[dict[str, JsonValue], ...] = ()


class WorkflowAuthoringSlotV2(_AuthoringModel):
    """One semantic media slot without operational generation state."""

    slot_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    slot_type: str = Field(min_length=1)
    media_type: Literal["image", "video", "audio", "text"]
    required: bool = True
    slot_prompt: str | None = None
    system_suggested_prompt: str | None = None
    user_prompt: str | None = None
    negative_prompt: str | None = None
    dialogue_prompt: str | None = None
    audio_description_prompt: str | None = None
    voice_style_prompt: str | None = None
    negative_constraints: str | None = None
    prompt_source: str = "system"
    manual_prompt_dirty: bool = False
    media_prompt_asset_ids: tuple[str, ...] = ()
    implicit_reference_ids: tuple[str, ...] = ()
    explicit_reference_ids: tuple[str, ...] = ()
    dependency_slot_ids: tuple[str, ...] = ()
    provider: str | None = None
    provider_params: dict[str, JsonValue] = Field(default_factory=dict)
    selected_asset_id: str | None = None
    selected_version_id: str | None = None
    authoring_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowAuthoringItemV2(_AuthoringModel):
    """One semantic canvas item without runtime status or provider state."""

    item_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    item_type: Literal[
        "product",
        "character",
        "scene",
        "bgm",
        "shot",
        "free",
        "final_composition",
        "script",
    ]
    display_name: str = Field(min_length=1)
    description: str = ""
    item_prompt: str | None = None
    system_suggested_prompt: str | None = None
    user_prompt: str | None = None
    prompt_source: str = "system"
    manual_prompt_dirty: bool = False
    lifecycle_state: Literal["active", "archived"] = "active"
    shot_id: str | None = None
    shot_index: int | None = Field(default=None, ge=1)
    aspect_ratio: str | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    summary_prompt: str | None = None
    cell_prompts: tuple[dict[str, JsonValue], ...] = ()
    shot_summary_prompt: str | None = None
    detail_prompts: dict[str, JsonValue] = Field(default_factory=dict)
    reference_item_ids: tuple[str, ...] = ()
    primary_scene_item_id: str | None = None
    reference_source: (
        Literal[
            "llm_structured",
            "repaired",
            "deterministic_fallback",
        ]
        | None
    ) = None
    authoring_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    slots: tuple[WorkflowAuthoringSlotV2, ...] = ()


class WorkflowAuthoringNodeV2(_AuthoringModel):
    """Stable graph node structure for one authoring revision."""

    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    position: dict[str, float] = Field(default_factory=dict)
    authoring_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    items: tuple[WorkflowAuthoringItemV2, ...] = ()


class WorkflowAuthoringEdgeV2(_AuthoringModel):
    """Stable canvas graph edge definition."""

    edge_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_kind: Literal["display_flow"] = "display_flow"
    label: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowAuthoringReferenceV2(_AuthoringModel):
    """An explicit authoring-time reference binding."""

    node_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    reference_asset_ids: tuple[str, ...] = ()
    implicit_reference_ids: tuple[str, ...] = ()
    explicit_reference_ids: tuple[str, ...] = ()


class WorkflowAuthoringTimelineV2(_AuthoringModel):
    """Final-composition timeline state separated from operational renders."""

    item_id: str = Field(min_length=1)
    timeline_plan: dict[str, JsonValue] = Field(default_factory=dict)
    timeline_clips: tuple[dict[str, JsonValue], ...] = ()


class WorkflowAuthoringDocumentV2(_AuthoringModel):
    """Complete allowlisted semantic state stored in one immutable revision."""

    document_schema_version: Literal[1] = 1
    workflow_schema_version: Literal[2] = 2
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    prompt: str = Field(min_length=1)
    duration_seconds: int = Field(ge=1)
    aspect_ratio: str = Field(min_length=1)
    output_resolution: Literal["480p", "720p", "1080p"]
    audio_mode: Literal["none", "bgm_only", "full"]
    creative_context: WorkflowAuthoringCreativeContextV2 = Field(
        default_factory=WorkflowAuthoringCreativeContextV2
    )
    nodes: tuple[WorkflowAuthoringNodeV2, ...] = ()
    edges: tuple[WorkflowAuthoringEdgeV2, ...] = ()
    references: tuple[WorkflowAuthoringReferenceV2, ...] = ()
    timelines: tuple[WorkflowAuthoringTimelineV2, ...] = ()

    @model_validator(mode="after")
    def reject_unsafe_persisted_values(self) -> "WorkflowAuthoringDocumentV2":
        _validate_json_value(self.model_dump(mode="json"), path="$")
        return self


class WorkflowRevisionCommitRequest(_AuthoringModel):
    """Validated data for one semantic authoring revision transaction."""

    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    expected_state_version: int = Field(ge=1)
    document: WorkflowAuthoringDocumentV2
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_source: WorkflowRevisionChangeSource
    source_execution_id: str | None = None
    restored_from_revision_no: int | None = Field(default=None, ge=1)


class WorkflowRevisionCommitResult(_AuthoringModel):
    """Typed outcome of an authoring revision transaction."""

    status: WorkflowRevisionCommitStatus
    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    revision_no: int = Field(ge=1)
    state_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_source: WorkflowRevisionChangeSource
    projection_state: WorkflowProjectionState


class WorkflowRevisionV2Summary(_AuthoringModel):
    """Bounded immutable revision metadata for history listings."""

    revision_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    revision_no: int = Field(ge=1)
    state_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_source: WorkflowRevisionChangeSource
    restored_from_revision_no: int | None = Field(default=None, ge=1)
    source_execution_id: str | None = None
    created_at: str = Field(min_length=1)


class WorkflowRevisionV2Detail(WorkflowRevisionV2Summary):
    """One immutable revision including its validated authoring document."""

    document: WorkflowAuthoringDocumentV2


class WorkflowRevisionPage(_AuthoringModel):
    """Deterministic page of newest-first Workflow revisions."""

    items: tuple[WorkflowRevisionV2Summary, ...] = ()
    next_cursor: str | None = None


class CurrentWorkflowAuthoringState(_AuthoringModel):
    """Current pointer plus the immutable document it references."""

    project_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    semantic_revision_no: int = Field(ge=1)
    state_version: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    projection_state: WorkflowProjectionState
    projection_revision_no: int | None = Field(default=None, ge=1)
    projection_error_code: str | None = None
    projection_error_summary: str | None = None
    revision: WorkflowRevisionV2Detail


class WorkflowOperationalViolationV2(_AuthoringModel):
    """One bounded provider/runtime validation violation."""

    code: str = Field(min_length=1, max_length=100)
    field_path: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=500)


class WorkflowOperationalSlotErrorV2(_AuthoringModel):
    """Bounded operational error retained in a projection overlay."""

    code: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)
    stage: str | None = Field(default=None, max_length=200)
    shot_id: str | None = Field(default=None, max_length=200)
    slot_id: str | None = Field(default=None, max_length=200)
    violations: tuple[WorkflowOperationalViolationV2, ...] = Field(
        default_factory=tuple,
        max_length=30,
    )


class WorkflowProviderCooldownV2(_AuthoringModel):
    """One typed provider-concurrency cooldown for image or video work."""

    media_type: Literal["image", "video"]
    reason: str = Field(min_length=1, max_length=200)
    active_until: str = Field(min_length=1, max_length=200)
    reduced_parallel_jobs: int = Field(gt=0)
    provider_task_id: str | None = Field(default=None, max_length=200)
    remote_task_id: str | None = Field(default=None, max_length=200)


class WorkflowOperationalRuntimeV2(_AuthoringModel):
    """Runtime fields permitted to rebase onto immutable authoring."""

    workflow_id: str = Field(min_length=1, max_length=200)
    running_node_ids: tuple[str, ...] = ()
    running_item_ids: tuple[str, ...] = ()
    running_slot_ids: tuple[str, ...] = ()
    waiting_slot_ids: tuple[str, ...] = ()
    failed_slot_ids: tuple[str, ...] = ()


class WorkflowOperationalNodeOverlayV2(_AuthoringModel):
    """One node runtime status keyed by stable node ID."""

    node_id: str = Field(min_length=1, max_length=200)
    status: Literal[
        "not_ready",
        "ready",
        "running",
        "waiting",
        "completed",
        "partial_failed",
        "failed",
    ]


class WorkflowOperationalItemOverlayV2(_AuthoringModel):
    """One item runtime status keyed by stable item ID."""

    item_id: str = Field(min_length=1, max_length=200)
    status: Literal[
        "empty",
        "blocked",
        "ready",
        "running",
        "waiting",
        "completed",
        "failed",
        "skipped",
        "not_ready",
        "partial_failed",
    ]


class WorkflowOperationalSlotOverlayV2(_AuthoringModel):
    """The full allowlisted slot operational state for one projection."""

    slot_id: str = Field(min_length=1, max_length=200)
    status: Literal[
        "empty",
        "blocked",
        "ready",
        "running",
        "waiting",
        "completed",
        "failed",
        "skipped",
    ]
    current_working_asset_id: str | None = Field(default=None, max_length=200)
    current_working_version_id: str | None = Field(default=None, max_length=200)
    provider_task_id: str | None = Field(default=None, max_length=200)
    remote_task_id: str | None = Field(default=None, max_length=200)
    provider_result_id: str | None = Field(default=None, max_length=200)
    waiting_reason: str | None = Field(default=None, max_length=200)
    blocked_reason: str | None = Field(default=None, max_length=200)
    skipped_reason: str | None = Field(default=None, max_length=200)
    generation_error: str | None = Field(default=None, max_length=500)
    generation_error_code: str | None = Field(default=None, max_length=200)
    error: WorkflowOperationalSlotErrorV2 | None = None
    recoverable: bool | None = None
    interrupted_at: str | None = Field(default=None, max_length=200)
    interrupted_execution_id: str | None = Field(default=None, max_length=200)
    last_runtime_event_seq: int | None = Field(default=None, ge=0)
    last_runtime_event_type: str | None = Field(default=None, max_length=200)
    provider_retry_attempts: int | None = Field(default=None, ge=0)
    provider_retry_policy: str | None = Field(default=None, max_length=200)
    provider_recovery_used: bool | None = None
    last_provider_error_code: str | None = Field(default=None, max_length=200)
    last_provider_error_message: str | None = Field(default=None, max_length=500)
    final_provider_error_code: str | None = Field(default=None, max_length=200)
    final_provider_error_message: str | None = Field(default=None, max_length=500)
    stale: bool | None = None


class WorkflowOperationalOverlayV2(_AuthoringModel):
    """Strict operational-only projection state; no semantic fields are accepted."""

    workflow_id: str = Field(min_length=1, max_length=200)
    runtime: WorkflowOperationalRuntimeV2 | None = None
    provider_cooldowns: dict[Literal["image", "video"], WorkflowProviderCooldownV2] = Field(
        default_factory=dict
    )
    nodes: tuple[WorkflowOperationalNodeOverlayV2, ...] = ()
    items: tuple[WorkflowOperationalItemOverlayV2, ...] = ()
    slots: tuple[WorkflowOperationalSlotOverlayV2, ...] = ()


def _validate_json_value(value: JsonValue, *, path: str) -> None:
    if isinstance(value, str):
        _validate_string(value, path=path)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_json_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_json_value(child, path=f"{path}[{index}]")


def _validate_string(value: str, *, path: str) -> None:
    lower_value = value.lower()
    if lower_value.startswith("data:"):
        raise ValueError(f"authoring document contains embedded data at {path}")
    if _is_absolute_local_path(value):
        raise ValueError(f"authoring document contains an absolute path at {path}")
    if _is_signed_url(value):
        raise ValueError(f"authoring document contains a signed URL at {path}")
    if _is_bare_base64_media(value):
        raise ValueError(f"authoring document contains embedded media at {path}")


def _is_absolute_local_path(value: str) -> bool:
    if value.startswith(("/media/", "/api/")):
        return False
    return value.startswith(("/", "\\\\")) or bool(_WINDOWS_DRIVE_PATH_PATTERN.match(value))


def _is_signed_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    return any(key.lower() in _SIGNED_QUERY_KEYS for key, _ in parse_qsl(parsed.query))


def _is_bare_base64_media(value: str) -> bool:
    if len(value) < _BARE_BASE64_MINIMUM_LENGTH:
        return False
    prefix = value[:4096]
    prefix = prefix[: len(prefix) - (len(prefix) % 4)]
    if not prefix:
        return False
    try:
        decoded = base64.b64decode(prefix, validate=True)
    except (binascii.Error, ValueError):
        return False
    return (
        decoded.startswith(b"\x89PNG\r\n\x1a\n")
        or decoded.startswith(b"\xff\xd8\xff")
        or decoded.startswith((b"GIF87a", b"GIF89a", b"ID3", b"OggS"))
        or decoded.startswith(b"RIFF")
        and decoded[8:12] in {b"WEBP", b"WAVE"}
        or len(decoded) >= 8
        and decoded[4:8] == b"ftyp"
    )
