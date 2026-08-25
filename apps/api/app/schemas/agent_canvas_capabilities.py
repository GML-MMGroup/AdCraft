"""Strict contracts for deterministic Agent Canvas capability dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    TypeAdapter,
    model_validator,
)

from app.schemas.agent_canvas_ad_media import SemanticReferenceRoleV2
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.language import BCP47Tag
from app.schemas.agent_canvas_requirements import (
    CapabilityRequirementProjectionV1,
    EditableRequirementDirectiveV1,
    RequirementControlV1,
    RequirementControlPatchV1,
    RequirementControlNameV1,
    RequirementDirectivePatchV1,
    RequirementElementPresencePatchV1,
    RequirementPatchV1,
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


class ExplicitElementIntentV2(RequirementElementPresencePatchV1):
    """One exact-evidence element decision from the current user message."""


class CompactRequirementDirectivePatchV1(_CapabilityModel):
    source_quote: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: Literal["global", "capability"]
    capability_id: CapabilityIdV1 | None = None
    strength: Literal["hard", "preference"]

    @model_validator(mode="after")
    def validate_scope(self) -> "CompactRequirementDirectivePatchV1":
        if self.scope_kind == "global" and self.capability_id is not None:
            raise ValueError("Global directives cannot select a capability.")
        if self.scope_kind == "capability" and self.capability_id is None:
            raise ValueError("Capability directives require one capability.")
        return self


_REQUIREMENT_CONTROL_PATCH_ADAPTER = TypeAdapter(RequirementControlPatchV1)


class CompactRequirementControlPatchV1(_CapabilityModel):
    control: RequirementControlNameV1
    value: str | int | float | bool
    source_quote: str = Field(min_length=1, max_length=2_048)

    @model_validator(mode="after")
    def validate_control_value(self) -> "CompactRequirementControlPatchV1":
        _REQUIREMENT_CONTROL_PATCH_ADAPTER.validate_python(self.model_dump())
        return self

    def to_requirement_patch(self) -> RequirementControlPatchV1:
        return _REQUIREMENT_CONTROL_PATCH_ADAPTER.validate_python(self.model_dump())


class CompactRequirementPatchV1(_CapabilityModel):
    controls_to_set: tuple[CompactRequirementControlPatchV1, ...] = Field(default=(), max_length=16)
    directives_to_add: tuple[CompactRequirementDirectivePatchV1, ...] = Field(
        default=(), max_length=16
    )


class CompactTurnIntentDecisionV1(_CapabilityModel):
    mode: Literal[
        "ordinary_conversation",
        "guided_production",
        "targeted_authoring",
        "quick_media",
    ]
    objective: str = Field(min_length=1, max_length=2_048)
    requested_capability: CapabilityIdV1 | None = None
    explicit_elements: tuple[ExplicitElementIntentV2, ...] = Field(default=(), max_length=16)
    assistant_message: str | None = Field(default=None, max_length=2_000)
    requirement_patch: CompactRequirementPatchV1 | None = None
    response_locale: BCP47Tag | None = None

    @model_validator(mode="after")
    def validate_unique_explicit_elements(self) -> "CompactTurnIntentDecisionV1":
        element_kinds = tuple(item.element_kind for item in self.explicit_elements)
        if len(element_kinds) != len(set(element_kinds)):
            raise ValueError("Explicit element decisions must use unique element kinds.")
        return self


class _CompactControlValueV2(_CapabilityModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_quote: str = Field(min_length=1, max_length=2_048)


class CompactDurationSecondsControlV2(_CompactControlValueV2):
    value: float = Field(ge=1, le=3_600)


class CompactAspectRatioControlV2(_CompactControlValueV2):
    value: str = Field(min_length=1, max_length=32)


class CompactOutputResolutionControlV2(_CompactControlValueV2):
    value: str = Field(min_length=1, max_length=64)


class CompactFrameRateControlV2(_CompactControlValueV2):
    value: float = Field(ge=1, le=240)


class CompactSpokenLanguageControlV2(_CompactControlValueV2):
    value: str = Field(min_length=1, max_length=64)


class CompactAudioModeControlV2(_CompactControlValueV2):
    value: Literal["none", "bgm_only", "full"]


class CompactProductCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=32)


class CompactPropCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=64)


class CompactCharacterCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=32)


class CompactSceneCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=32)


class CompactStoryboardSequenceCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=64)


class CompactVideoSegmentCountControlV2(_CompactControlValueV2):
    value: int = Field(ge=0, le=64)


class CompactRequirementControlsV2(_CapabilityModel):
    # Non-nullable optional properties keep the model-facing schema precise: omission
    # means unspecified, while an explicitly supplied control must be a complete object.
    duration_seconds: CompactDurationSecondsControlV2 = Field(default=None)
    aspect_ratio: CompactAspectRatioControlV2 = Field(default=None)
    output_resolution: CompactOutputResolutionControlV2 = Field(default=None)
    frame_rate: CompactFrameRateControlV2 = Field(default=None)
    spoken_language: CompactSpokenLanguageControlV2 = Field(default=None)
    audio_mode: CompactAudioModeControlV2 = Field(default=None)
    product_count: CompactProductCountControlV2 = Field(default=None)
    prop_count: CompactPropCountControlV2 = Field(default=None)
    character_count: CompactCharacterCountControlV2 = Field(default=None)
    scene_count: CompactSceneCountControlV2 = Field(default=None)
    storyboard_sequence_count: CompactStoryboardSequenceCountControlV2 = Field(default=None)
    video_segment_count: CompactVideoSegmentCountControlV2 = Field(default=None)

    def to_requirement_patches(self) -> tuple[RequirementControlPatchV1, ...]:
        patches: list[RequirementControlPatchV1] = []
        for control_name in RequirementControlNameV1.__args__:
            value = getattr(self, control_name)
            if value is None:
                continue
            patches.append(
                _REQUIREMENT_CONTROL_PATCH_ADAPTER.validate_python(
                    {"control": control_name, **value.model_dump()}
                )
            )
        return tuple(patches)


class CompactExplicitElementValueV3(_CapabilityModel):
    presence: Literal["include", "exclude", "unspecified"]
    source_quote: str = Field(min_length=1, max_length=2_048)


class CompactExplicitElementsV3(_CapabilityModel):
    # Omission means no new decision. Explicit null remains invalid because each field
    # has a non-nullable annotation even though its omission default is None.
    product: CompactExplicitElementValueV3 = Field(default=None)
    prop: CompactExplicitElementValueV3 = Field(default=None)
    character: CompactExplicitElementValueV3 = Field(default=None)
    scene: CompactExplicitElementValueV3 = Field(default=None)
    world_setting: CompactExplicitElementValueV3 = Field(default=None)
    script: CompactExplicitElementValueV3 = Field(default=None)
    storyboard: CompactExplicitElementValueV3 = Field(default=None)
    video: CompactExplicitElementValueV3 = Field(default=None)
    audio: CompactExplicitElementValueV3 = Field(default=None)


class CompactGlobalRequirementDirectivePatchV3(_CapabilityModel):
    source_quote: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: Literal["global"]
    strength: Literal["hard", "preference"]


class CompactCapabilityRequirementDirectivePatchV3(_CapabilityModel):
    source_quote: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: Literal["capability"]
    capability_id: CapabilityIdV1
    strength: Literal["hard", "preference"]


_CompactRequirementDirectiveVariantV3 = Annotated[
    CompactGlobalRequirementDirectivePatchV3 | CompactCapabilityRequirementDirectivePatchV3,
    Field(discriminator="scope_kind"),
]


class CompactRequirementDirectivePatchV3(RootModel[_CompactRequirementDirectiveVariantV3]):
    """One schema-discriminated compact creative directive."""


class CompactRequirementPatchV3(_CapabilityModel):
    controls_to_set: CompactRequirementControlsV2 = Field(
        default_factory=CompactRequirementControlsV2
    )
    directives_to_add: tuple[CompactRequirementDirectivePatchV3, ...] = Field(
        default=(), max_length=16
    )


class CompactTurnIntentDecisionV3(_CapabilityModel):
    mode: Literal[
        "ordinary_conversation",
        "guided_production",
        "targeted_authoring",
        "quick_media",
    ] = Field(
        description=(
            "Interaction intent. Use guided_production for requests to create, plan, or "
            "continue advertising even when details are missing, ambiguous, or "
            "contradictory; ordinary_conversation is limited to greetings, informational "
            "questions, explanations, and other non-authoring messages. Use "
            "targeted_authoring for a specifically referenced Node or image Asset and "
            "quick_media for one bounded media output."
        )
    )
    objective: str = Field(min_length=1, max_length=2_048)
    requested_capability: CapabilityIdV1 | None = None
    explicit_elements: CompactExplicitElementsV3 = Field(default_factory=CompactExplicitElementsV3)
    assistant_message: str | None = Field(default=None, max_length=2_000)
    requirement_patch: CompactRequirementPatchV3 | None = None
    response_locale: BCP47Tag | None = Field(
        default=None,
        description=(
            "Canonical BCP 47 locale for the current response. Treat an input locale of "
            "und as unresolved prior state; when the current message clearly establishes "
            "a language, return that language rather than inheriting und."
        ),
    )

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "CompactTurnIntentDecisionV3":
        if self.mode != "ordinary_conversation":
            return self
        has_explicit_elements = bool(self.explicit_elements.model_dump(exclude_none=True))
        has_requirement_patch = self.requirement_patch is not None and bool(
            self.requirement_patch.controls_to_set.model_dump(exclude_none=True)
            or self.requirement_patch.directives_to_add
        )
        if self.requested_capability or has_explicit_elements or has_requirement_patch:
            raise ValueError("ordinary_conversation cannot carry authoring-only structured fields.")
        return self


class TurnIntentDecisionV2(_CapabilityModel):
    mode: Literal[
        "ordinary_conversation",
        "guided_production",
        "targeted_authoring",
        "quick_media",
    ]
    objective: str = Field(min_length=1, max_length=4_096)
    requested_capability: CapabilityIdV1 | None = None
    explicit_elements: tuple[ExplicitElementIntentV2, ...] = Field(default=(), max_length=16)
    assistant_message: str | None = Field(default=None, max_length=4_000)
    requirement_patch: RequirementPatchV1 | None = None
    response_locale: BCP47Tag = "und"

    @model_validator(mode="after")
    def validate_unique_explicit_elements(self) -> "TurnIntentDecisionV2":
        element_kinds = tuple(item.element_kind for item in self.explicit_elements)
        if len(element_kinds) != len(set(element_kinds)):
            raise ValueError("Explicit element decisions must use unique element kinds.")
        return self


def expand_compact_turn_intent(
    compact: CompactTurnIntentDecisionV3,
    *,
    current_response_locale: BCP47Tag | None = None,
) -> TurnIntentDecisionV2:
    """Expand model-owned routing fields into the stable public contract."""

    compact_patch = compact.requirement_patch
    requirement_patch = None
    if compact_patch is not None:
        requirement_patch = RequirementPatchV1(
            controls_to_set=compact_patch.controls_to_set.to_requirement_patches(),
            directives_to_add=tuple(
                RequirementDirectivePatchV1(
                    source_quote=item.root.source_quote,
                    normalized_meaning=item.root.normalized_meaning,
                    scope_kind=item.root.scope_kind,
                    capability_ids=(
                        (item.root.capability_id,)
                        if isinstance(item.root, CompactCapabilityRequirementDirectivePatchV3)
                        else ()
                    ),
                    target_node_ids=(),
                    strength=item.root.strength,
                )
                for item in compact_patch.directives_to_add
            ),
            directive_ids_to_supersede=(),
            conflicts=(),
        )
    explicit_elements = tuple(
        ExplicitElementIntentV2(
            element_kind=element_kind,
            presence=element.presence,
            source_quote=element.source_quote,
        )
        for element_kind in (
            "product",
            "prop",
            "character",
            "scene",
            "world_setting",
            "script",
            "storyboard",
            "video",
            "audio",
        )
        if (element := getattr(compact.explicit_elements, element_kind)) is not None
    )
    return TurnIntentDecisionV2(
        mode=compact.mode,
        objective=compact.objective,
        requested_capability=compact.requested_capability,
        explicit_elements=explicit_elements,
        assistant_message=compact.assistant_message,
        requirement_patch=requirement_patch,
        response_locale=compact.response_locale or current_response_locale or "und",
    )


class TurnIntentContextV2(_CapabilityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    workflow_revision: int = Field(ge=1)
    conversation_id: str = Field(min_length=1, max_length=160)
    user_input: str = Field(min_length=1, max_length=32_768)
    session_exists: bool
    mentioned_node_ids: tuple[str, ...] = Field(default=(), max_length=16)
    mentioned_image_asset_ids: tuple[str, ...] = Field(default=(), max_length=16)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    requirement_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    current_hard_controls: tuple[RequirementControlV1, ...] = Field(default=(), max_length=16)
    editable_directives: tuple[EditableRequirementDirectiveV1, ...] = Field(
        default=(), max_length=32
    )
    current_response_locale: BCP47Tag = "und"


class AskUserNextActionCommandV1(_CapabilityModel):
    action: Literal["ask_user"]
    message: str = Field(min_length=1, max_length=4_000)


class AuthorDecisionBundleNextActionCommandV1(_CapabilityModel):
    action: Literal["author_decision_bundle"]
    objective: str = Field(min_length=1, max_length=4_096)


class InvokeCapabilityNextActionCommandV1(_CapabilityModel):
    action: Literal["invoke_capability"]
    capability_id: CapabilityIdV1
    objective: str = Field(min_length=1, max_length=4_096)


class ReplyNextActionCommandV1(_CapabilityModel):
    action: Literal["reply"]
    message: str = Field(min_length=1, max_length=4_000)


class FinishNextActionCommandV1(_CapabilityModel):
    action: Literal["finish"]


_NextActionCommandVariantV1 = Annotated[
    AskUserNextActionCommandV1
    | AuthorDecisionBundleNextActionCommandV1
    | InvokeCapabilityNextActionCommandV1
    | ReplyNextActionCommandV1
    | FinishNextActionCommandV1,
    Field(discriminator="action"),
]


class NextActionCommandV1(RootModel[_NextActionCommandVariantV1]):
    """Compatibility wrapper around the exact action-specific command union."""

    def __init__(self, **data: Any) -> None:
        if set(data) == {"root"}:
            super().__init__(root=data["root"])
            return
        super().__init__(root=data)

    @property
    def action(self) -> str:
        return self.root.action

    @property
    def capability_id(self) -> CapabilityIdV1 | None:
        return getattr(self.root, "capability_id", None)

    @property
    def message(self) -> str | None:
        return getattr(self.root, "message", None)

    @property
    def objective(self) -> str | None:
        return getattr(self.root, "objective", None)


class NextActionContextV1(_CapabilityModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    session_revision: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=4_096)
    policy: "CapabilityPolicyResultV1"
    shared_summary: str = Field(default="", max_length=8_192)
    response_locale: BCP47Tag = "und"


class CapabilityDefinitionV1(_CapabilityModel):
    capability_id: CapabilityIdV1
    display_name: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=160)
    result_contract_name: str = Field(min_length=1, max_length=160)
    node_type: Literal["text", "script", "image", "video", "audio"] | None
    creative_role: str | None = Field(default=None, max_length=160)
    default_candidate_count: Literal[1, 3]
    allowed_reference_roles: tuple[SemanticReferenceRoleV2, ...] = ()


class CapabilityPolicyContextV1(_CapabilityModel):
    is_new_guided_production: bool = False
    world_setting_selected: bool = False
    targeted_capability: CapabilityIdV1 | None = None
    journey_capability: CapabilityIdV1 | None = None
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


class CapabilityContextSnapshotV2(_CapabilityModel):
    snapshot_id: str = Field(min_length=1, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_projection: CapabilityRequirementProjectionV1
    approved_reference_ids: tuple[str, ...] = Field(default=(), max_length=64)
    reference_plan: CapabilityReferencePlanV1
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    shared_summary: str = Field(default="", max_length=8_192)
    response_locale: BCP47Tag = "und"

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)


class CapabilityInvocationContextV2(_CapabilityModel):
    context_kind: Literal["capability_operation"]
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    capability_id: CapabilityIdV1
    candidate_count: int = Field(ge=1, le=3)
    objective: str = Field(min_length=1, max_length=4_096)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_projection: CapabilityRequirementProjectionV1
    approved_reference_ids: tuple[str, ...] = Field(default=(), max_length=64)
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    repair_error: str | None = Field(default=None, max_length=160)
    response_locale: BCP47Tag = "und"

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)


class CapabilityCommandEnvelopeV2(_CapabilityModel):
    schema_version: Literal["2"] = "2"
    envelope_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    capability_turn_id: str = Field(min_length=1, max_length=160)
    source_proposal_id: str | None = Field(default=None, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    expected_session_revision: int | None = Field(default=None, ge=1)
    capability_id: CapabilityIdV1
    publication_kind: Literal["proposal", "internal_document"] = "proposal"
    journey_stage: JourneyStageV2 | None = None
    source_action: GuidanceSourceActionV1 | None = None
    objective: str = Field(min_length=1, max_length=4_096)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    requirement_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_projection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_projection: CapabilityRequirementProjectionV1
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    capability_context: dict[str, JsonValue] = Field(default_factory=dict)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    result_contract_name: str = Field(min_length=1, max_length=160)
    candidate_count: int = Field(ge=1, le=3)
    reference_allowlist: tuple[str, ...] = Field(default=(), max_length=64)
    reference_plan: CapabilityReferencePlanV1
    agent_request_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime
    response_locale: BCP47Tag = "und"

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)

    @model_validator(mode="after")
    def validate_publication_boundary(self) -> "CapabilityCommandEnvelopeV2":
        internal_stages = {"narrative_direction", "style_lock", "storyboard_plan"}
        if self.publication_kind == "proposal":
            if self.journey_stage is not None:
                raise ValueError("Proposal commands cannot own an internal journey stage.")
            return self
        if (
            self.capability_id != "script_authoring"
            or self.journey_stage not in internal_stages
            or self.result_contract_name != "ScriptMaterializationResultV1"
            or self.candidate_count != 1
        ):
            raise ValueError("Internal document commands require one fixed Script checkpoint.")
        return self


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
    publication_kind: Literal["proposal", "internal_document"] = "proposal"
    proposal_id: str | None = None
    document_receipt_id: str | None = None
    repaired: bool = False

    @model_validator(mode="after")
    def validate_publication_result(self) -> "CapabilityExecutionResultV1":
        if self.publication_kind == "proposal":
            if self.proposal_id is None or self.document_receipt_id is not None:
                raise ValueError("Proposal execution requires only a Proposal identity.")
        elif self.document_receipt_id is None or self.proposal_id is not None:
            raise ValueError("Internal execution requires only a document receipt identity.")
        return self


class _OptionBaseV1(_CapabilityModel):
    title: str = Field(min_length=1, max_length=256)
    public_summary: str = Field(min_length=1, max_length=8_192)
    key_decisions: tuple[str, ...] = Field(min_length=1, max_length=6)


class ProposalCardOptionV2(_CapabilityModel):
    """The only model-authored fields allowed in a public Proposal Card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=64)
    public_summary: str = Field(min_length=1, max_length=240)


class ProposalCardResultV2(_CapabilityModel):
    """Compact proposal output; Python owns count and option identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    options: tuple[ProposalCardOptionV2, ...] = Field(min_length=1, max_length=3)


class GuidedProposalCardOptionV3(_CapabilityModel):
    """Compact public option for a normal guided creative choice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=64)
    public_summary: str = Field(min_length=1, max_length=240)


class GuidedProposalCardResultV3(_CapabilityModel):
    """Exact-three public proposal output for normal guided authoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    options: tuple[
        GuidedProposalCardOptionV3,
        GuidedProposalCardOptionV3,
        GuidedProposalCardOptionV3,
    ]


class WorldSettingProposalOptionV1(_OptionBaseV1):
    pass


class ProductProposalOptionV1(_OptionBaseV1):
    pass


class PropProposalOptionV1(_OptionBaseV1):
    pass


class CharacterProposalOptionV1(_OptionBaseV1):
    pass


class SceneProposalOptionV1(_OptionBaseV1):
    pass


class ScriptProposalOptionV1(_OptionBaseV1):
    pass


class StoryboardProposalOptionV1(_OptionBaseV1):
    pass


class VideoProposalOptionV1(_OptionBaseV1):
    pass


class BgmProposalOptionV1(_OptionBaseV1):
    pass


class QuickMediaProposalOptionV1(_OptionBaseV1):
    pass


class WorldSettingProposalResultV1(_CapabilityModel):
    options: tuple[WorldSettingProposalOptionV1, ...] = Field(min_length=1, max_length=3)


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
    "world_setting": GuidedProposalCardResultV3,
    "product_design": GuidedProposalCardResultV3,
    "prop_design": GuidedProposalCardResultV3,
    "character_design": GuidedProposalCardResultV3,
    "scene_design": GuidedProposalCardResultV3,
    "script_authoring": GuidedProposalCardResultV3,
    "storyboard_design": GuidedProposalCardResultV3,
    "video_direction": GuidedProposalCardResultV3,
    "bgm_direction": GuidedProposalCardResultV3,
    "quick_media": ProposalCardResultV2,
}
