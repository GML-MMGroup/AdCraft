"""Strict contracts for deterministic Agent Canvas capability dispatch."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_ad_media import SemanticReferenceRoleV2
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_draft_seeds import (
    DraftSeedCapabilityIdV1,
    DraftSeedEnvelopeV1,
)


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_FORBIDDEN_CONTEXT_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "media_bytes",
    "provider_payload",
    "secret",
    "token",
)


def _validate_bounded_context_fields(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    def visit(current: Any, key: str | None = None) -> None:
        normalized_key = key.casefold() if key else ""
        if normalized_key and any(part in normalized_key for part in _FORBIDDEN_CONTEXT_KEY_PARTS):
            raise ValueError("Capability context contains a forbidden field.")
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, str) and current.startswith(("/", "\\\\")):
            raise ValueError("Capability context cannot contain an absolute path.")

    for field in ("capability_context", "style_projection"):
        visit(value.get(field), field)
    return value


class ExplicitElementIntentV1(_CapabilityModel):
    element_kind: Literal[
        "product",
        "prop",
        "character",
        "scene",
        "world_setting",
        "script",
        "storyboard",
        "video",
        "audio",
    ]
    presence: Literal["include", "exclude"]
    requirements: dict[str, JsonValue] = Field(default_factory=dict)


class TurnIntentDecisionV1(_CapabilityModel):
    mode: Literal[
        "ordinary_conversation",
        "guided_production",
        "targeted_authoring",
        "quick_media",
    ]
    objective: str = Field(min_length=1, max_length=4_096)
    requested_capability: CapabilityIdV1 | None = None
    explicit_elements: tuple[ExplicitElementIntentV1, ...] = Field(default=(), max_length=16)
    explicit_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    assistant_message: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def validate_unique_explicit_elements(self) -> "TurnIntentDecisionV1":
        element_kinds = tuple(item.element_kind for item in self.explicit_elements)
        if len(element_kinds) != len(set(element_kinds)):
            raise ValueError("Explicit element decisions must use unique element kinds.")
        return self


class TurnIntentContextV1(_CapabilityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    user_input: str = Field(min_length=1, max_length=32_768)
    session_exists: bool
    mentioned_node_ids: tuple[str, ...] = Field(default=(), max_length=16)
    mentioned_image_asset_ids: tuple[str, ...] = Field(default=(), max_length=16)


class NextActionCommandV1(_CapabilityModel):
    action: Literal["ask_user", "invoke_capability", "reply", "finish"]
    capability_id: CapabilityIdV1 | None = None
    message: str | None = Field(default=None, max_length=4_000)
    objective: str | None = Field(default=None, max_length=4_096)

    @model_validator(mode="after")
    def validate_action_shape(self) -> "NextActionCommandV1":
        if self.action == "invoke_capability":
            if self.capability_id is None or not self.objective:
                raise ValueError("Capability invocation requires capability_id and objective.")
            return self
        if self.action in {"ask_user", "reply"}:
            if not self.message or self.capability_id is not None or self.objective is not None:
                raise ValueError(
                    "Conversation actions require message and forbid capability fields."
                )
            return self
        if self.capability_id is not None or self.objective is not None:
            raise ValueError("Finish forbids capability fields.")
        return self


class NextActionContextV1(_CapabilityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    session_revision: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=4_096)
    policy: "CapabilityPolicyResultV1"
    shared_summary: str = Field(default="", max_length=8_192)


class CapabilityDefinitionV1(_CapabilityModel):
    capability_id: CapabilityIdV1
    display_name: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=160)
    result_contract_name: str = Field(min_length=1, max_length=160)
    node_type: Literal["text", "script", "image", "video", "audio"] | None
    creative_role: str | None = Field(default=None, max_length=160)
    default_candidate_count: int = Field(ge=1, le=3)
    allowed_reference_roles: tuple[SemanticReferenceRoleV2, ...] = ()


class CapabilityPolicyContextV1(_CapabilityModel):
    is_new_guided_production: bool = False
    world_setting_selected: bool = False
    targeted_capability: CapabilityIdV1 | None = None
    completed_capabilities: tuple[CapabilityIdV1, ...] = ()
    excluded_capabilities: tuple[CapabilityIdV1, ...] = ()
    open_proposal_capabilities: tuple[CapabilityIdV1, ...] = ()
    active_materialization_capabilities: tuple[CapabilityIdV1, ...] = ()
    deferred_capabilities: tuple[CapabilityIdV1, ...] = ()
    required_capabilities: tuple[CapabilityIdV1, ...] = ()


class CapabilityPolicyResultV1(_CapabilityModel):
    allowed_capabilities: tuple[CapabilityIdV1, ...]
    recommended_capabilities: tuple[CapabilityIdV1, ...]
    completion_allowed: bool
    blocking_facts: tuple[str, ...] = ()
    required_deferred_capabilities: tuple[CapabilityIdV1, ...] = ()
    targeted_resume: bool = False


class PlannedCapabilityReferenceV1(_CapabilityModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    input_role: Literal[
        "text_context",
        "image_reference",
        "video_reference",
        "audio_reference",
    ]
    required: bool = False
    default_selected: bool = True
    semantic_reference_role: SemanticReferenceRoleV2 | None = None
    priority: int = Field(ge=0, le=10_000)
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class CapabilityReferencePlanV1(_CapabilityModel):
    capability_id: CapabilityIdV1
    references: tuple[PlannedCapabilityReferenceV1, ...] = Field(default=(), max_length=64)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=64)

    @property
    def approved_reference_ids(self) -> tuple[str, ...]:
        return tuple(reference.source_id for reference in self.references)


GuidanceSourceActionV1 = Literal[
    "required_deferred_final_review",
    "user_resumed_deferred_topic",
]


class ValidatedNextActionV1(_CapabilityModel):
    command: NextActionCommandV1
    definition: CapabilityDefinitionV1 | None = None
    source_action: GuidanceSourceActionV1 | None = None


class CapabilityContextSnapshotV1(_CapabilityModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    shared_summary: str = Field(default="", max_length=8_192)
    approved_reference_ids: tuple[str, ...] = Field(default=(), max_length=64)
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    reference_plan: CapabilityReferencePlanV1

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)


class CapabilityInvocationContextV1(_CapabilityModel):
    context_kind: Literal["capability_operation"]
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    capability_id: CapabilityIdV1
    objective: str = Field(min_length=1, max_length=4_096)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    shared_summary: str | None = Field(default=None, min_length=1, max_length=4_096)
    approved_reference_ids: tuple[str, ...] = Field(default=(), max_length=64)
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    repair_error: str | None = Field(default=None, max_length=160)

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)


class CapabilityCommandEnvelopeV1(_CapabilityModel):
    schema_version: Literal["1"] = "1"
    envelope_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    capability_turn_id: str = Field(min_length=1, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    expected_session_revision: int | None = Field(default=None, ge=1)
    capability_id: CapabilityIdV1
    source_action: GuidanceSourceActionV1 | None = None
    objective: str = Field(min_length=1, max_length=4_096)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    shared_summary: str = Field(default="", max_length=8_192)
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    result_contract_name: str = Field(min_length=1, max_length=160)
    candidate_count: int = Field(ge=1, le=3)
    reference_allowlist: tuple[str, ...] = Field(default=(), max_length=64)
    reference_plan: CapabilityReferencePlanV1
    agent_request_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)

    @model_validator(mode="before")
    @classmethod
    def restore_legacy_reference_plan(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "reference_plan" in value:
            return value
        capability_id = value.get("capability_id")
        allowlist = value.get("reference_allowlist") or ()
        references = [
            {
                "source_kind": "node",
                "source_id": source_id,
                "input_role": "image_reference",
                "required": False,
                "default_selected": True,
                "priority": index,
                "display_name": source_id,
                "media_type": "image",
            }
            for index, source_id in enumerate(allowlist)
        ]
        payload = {
            "capability_id": capability_id,
            "references": references,
            "warnings": ["legacy_reference_allowlist_restored"],
        }
        digest = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {**value, "reference_plan": {**payload, "digest": digest}}


class NextActionEnvelopeV1(_CapabilityModel):
    schema_version: Literal["1"] = "1"
    envelope_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    next_action_turn_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=4_096)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime


class CapabilityDispatchReceiptV1(_CapabilityModel):
    envelope_id: str
    continuation_id: str
    capability_turn_id: str
    capability_id: CapabilityIdV1
    activity_id: str
    queued_at: datetime


class CapabilityExecutionResultV1(_CapabilityModel):
    envelope_id: str
    capability_id: CapabilityIdV1
    result_contract_name: str
    proposal_id: str
    repaired: bool = False


class _OptionBaseV1(_CapabilityModel):
    title: str = Field(min_length=1, max_length=256)
    public_summary: str = Field(min_length=1, max_length=8_192)
    key_decisions: tuple[str, ...] = Field(min_length=1, max_length=6)


class _SeededOptionBaseV1(_OptionBaseV1):
    expected_capability_id: ClassVar[DraftSeedCapabilityIdV1]
    private_draft_seed: DraftSeedEnvelopeV1

    @model_validator(mode="after")
    def validate_seed_capability(self) -> "_SeededOptionBaseV1":
        if self.private_draft_seed.capability_id != self.expected_capability_id:
            raise ValueError("Proposal option Draft Seed has the wrong capability.")
        return self


class WorldSettingProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "world_setting"


class ProductProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "product_design"


class PropProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "prop_design"


class CharacterProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "character_design"


class SceneProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "scene_design"


class ScriptProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "script_authoring"


class StoryboardProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "storyboard_design"


class VideoProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "video_direction"


class BgmProposalOptionV1(_SeededOptionBaseV1):
    expected_capability_id = "bgm_direction"


class QuickMediaProposalOptionV1(_OptionBaseV1):
    pass


class WorldSettingProposalResultV1(_CapabilityModel):
    options: tuple[WorldSettingProposalOptionV1, ...] = Field(min_length=2, max_length=3)


class ProductProposalResultV1(_CapabilityModel):
    options: tuple[ProductProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class PropProposalResultV1(_CapabilityModel):
    options: tuple[PropProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class CharacterProposalResultV1(_CapabilityModel):
    options: tuple[CharacterProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class SceneProposalResultV1(_CapabilityModel):
    options: tuple[SceneProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class ScriptProposalResultV1(_CapabilityModel):
    options: tuple[ScriptProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class StoryboardProposalResultV1(_CapabilityModel):
    options: tuple[StoryboardProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class VideoProposalResultV1(_CapabilityModel):
    options: tuple[VideoProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class BgmProposalResultV1(_CapabilityModel):
    options: tuple[BgmProposalOptionV1, ...] = Field(min_length=1, max_length=3)


class QuickMediaProposalResultV1(_CapabilityModel):
    options: tuple[QuickMediaProposalOptionV1, ...] = Field(min_length=1, max_length=3)


CAPABILITY_RESULT_CONTRACTS: dict[CapabilityIdV1, type[_CapabilityModel]] = {
    "world_setting": WorldSettingProposalResultV1,
    "product_design": ProductProposalResultV1,
    "prop_design": PropProposalResultV1,
    "character_design": CharacterProposalResultV1,
    "scene_design": SceneProposalResultV1,
    "script_authoring": ScriptProposalResultV1,
    "storyboard_design": StoryboardProposalResultV1,
    "video_direction": VideoProposalResultV1,
    "bgm_direction": BgmProposalResultV1,
    "quick_media": QuickMediaProposalResultV1,
}
