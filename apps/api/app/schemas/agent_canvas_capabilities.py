"""Strict contracts for deterministic Agent Canvas capability dispatch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    TypeAdapter,
    ValidationInfo,
    model_validator,
)

from app.schemas.agent_canvas_ad_media import SemanticReferenceRoleV2
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.language import BCP47Tag
from app.schemas.agent_canvas_requirements import (
    CapabilityRequirementProjectionV1,
    CharacterAuthoringPhaseV1,
    CharacterOccurrencePatchV1,
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


class CompactVideoRepresentationModeControlV2(_CompactControlValueV2):
    value: Literal["illustrated", "illustration_to_live_action"]


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
    video_representation_mode: CompactVideoRepresentationModeControlV2 = Field(default=None)

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


class CompactCharacterOccurrencePatchV3(_CapabilityModel):
    occurrence_index: int = Field(ge=1, le=32)
    role: str = Field(min_length=1, max_length=256)
    identity_summary: str = Field(min_length=1, max_length=2_048)
    presence: Literal["include", "exclude", "unspecified"]
    source_quote: str = Field(min_length=1, max_length=2_048)


class CompactRequirementPatchV3(_CapabilityModel):
    controls_to_set: CompactRequirementControlsV2 = Field(
        default_factory=CompactRequirementControlsV2
    )
    directives_to_add: tuple[CompactRequirementDirectivePatchV3, ...] = Field(
        default=(), max_length=16
    )
    character_occurrences_to_set: tuple[CompactCharacterOccurrencePatchV3, ...] | None = Field(
        default=None,
        max_length=32,
        description=(
            "Optional complete character occurrence roster. When character_count "
            "is also supplied, included occurrences must equal that count."
        ),
    )

    @model_validator(mode="after")
    def validate_character_count_occurrences(self) -> "CompactRequirementPatchV3":
        character_count = self.controls_to_set.character_count
        occurrences = self.character_occurrences_to_set
        if character_count is None or occurrences is None:
            return self
        included_count = sum(item.presence == "include" for item in occurrences)
        if included_count != character_count.value:
            raise ValueError(
                "character occurrence count must match the included occurrence roster."
            )
        return self


class ConversationQueryV1(_CapabilityModel):
    query_kind: Literal["workflow_status", "document_explanation"]
    document_kind: Literal["anchor_registry", "storyboard_production_plan"] | None = None
    requested_document_kinds: tuple[
        Literal["anchor_registry", "storyboard_production_plan"], ...
    ] = Field(default=(), max_length=2)
    sequence_id: str | None = Field(default=None, min_length=1, max_length=160)
    anchor_aliases: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_scope(self) -> "ConversationQueryV1":
        if len(self.anchor_aliases) != len(set(self.anchor_aliases)):
            raise ValueError("Conversation query anchor aliases must be unique.")
        if self.query_kind == "workflow_status":
            if (
                self.document_kind is not None
                or self.requested_document_kinds
                or self.sequence_id is not None
                or self.anchor_aliases
            ):
                raise ValueError("Workflow status query cannot carry a document selector.")
            return self
        if self.requested_document_kinds:
            if self.requested_document_kinds != (
                "anchor_registry",
                "storyboard_production_plan",
            ):
                raise ValueError("Document selection requires the canonical two-document pair.")
            if (
                self.document_kind is not None
                or self.sequence_id is not None
                or self.anchor_aliases
            ):
                raise ValueError("Document selection cannot carry a document selector.")
            return self
        if self.document_kind is None:
            raise ValueError("Document explanation requires a document kind.")
        if self.document_kind == "anchor_registry":
            if self.sequence_id is not None:
                raise ValueError("Anchor Registry query cannot carry a sequence selector.")
        elif self.anchor_aliases:
            raise ValueError("Storyboard plan query cannot carry anchor aliases.")
        return self


class FreeformReplyOrdinaryIntentV1(_CapabilityModel):
    intent_kind: Literal["freeform_reply"]
    assistant_message: str = Field(min_length=1, max_length=2_000)


class AgentIdentityOrdinaryIntentV1(_CapabilityModel):
    intent_kind: Literal["agent_identity"]


class AgentCapabilitiesOrdinaryIntentV1(_CapabilityModel):
    intent_kind: Literal["agent_capabilities"]


class WorkflowStatusOrdinaryIntentV1(_CapabilityModel):
    intent_kind: Literal["workflow_status"]


class DocumentExplanationOrdinaryIntentV1(_CapabilityModel):
    intent_kind: Literal["document_explanation"]
    document_kind: Literal["anchor_registry", "storyboard_production_plan"] | None = None
    requested_document_kinds: tuple[
        Literal["anchor_registry", "storyboard_production_plan"], ...
    ] = Field(default=(), max_length=2)
    sequence_id: str | None = Field(default=None, min_length=1, max_length=160)
    anchor_aliases: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_scope(self) -> "DocumentExplanationOrdinaryIntentV1":
        ConversationQueryV1(
            query_kind="document_explanation",
            document_kind=self.document_kind,
            requested_document_kinds=self.requested_document_kinds,
            sequence_id=self.sequence_id,
            anchor_aliases=self.anchor_aliases,
        )
        return self

    def to_legacy_query(self) -> ConversationQueryV1:
        return ConversationQueryV1(
            query_kind="document_explanation",
            document_kind=self.document_kind,
            requested_document_kinds=self.requested_document_kinds,
            sequence_id=self.sequence_id,
            anchor_aliases=self.anchor_aliases,
        )


_OrdinaryConversationIntentVariantV1 = Annotated[
    FreeformReplyOrdinaryIntentV1
    | AgentIdentityOrdinaryIntentV1
    | AgentCapabilitiesOrdinaryIntentV1
    | WorkflowStatusOrdinaryIntentV1
    | DocumentExplanationOrdinaryIntentV1,
    Field(discriminator="intent_kind"),
]


class OrdinaryConversationIntentV1(RootModel[_OrdinaryConversationIntentVariantV1]):
    """One mutually exclusive ordinary-conversation route."""

    @property
    def intent_kind(
        self,
    ) -> Literal[
        "freeform_reply",
        "agent_identity",
        "agent_capabilities",
        "workflow_status",
        "document_explanation",
    ]:
        return self.root.intent_kind

    @property
    def sequence_id(self) -> str | None:
        return getattr(self.root, "sequence_id", None)


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
    ordinary_intent: OrdinaryConversationIntentV1 | None = None
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
            if self.ordinary_intent is not None:
                raise ValueError("ordinary_intent is valid only for ordinary_conversation.")
            if self.assistant_message is None or not self.assistant_message.strip():
                raise ValueError("authoring intent requires a non-empty assistant_message.")
            return self
        if self.ordinary_intent is None:
            raise ValueError("ordinary_conversation requires exactly one ordinary_intent.")
        if self.assistant_message is not None:
            raise ValueError("ordinary assistant_message belongs only inside freeform_reply.")
        has_explicit_elements = bool(self.explicit_elements.model_dump(exclude_none=True))
        has_requirement_patch = self.requirement_patch is not None and bool(
            self.requirement_patch.controls_to_set.model_dump(exclude_none=True)
            or self.requirement_patch.directives_to_add
            or self.requirement_patch.character_occurrences_to_set
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
    ordinary_intent: OrdinaryConversationIntentV1 | None = None
    requirement_patch: RequirementPatchV1 | None = None
    response_locale: BCP47Tag = "und"

    @model_validator(mode="after")
    def validate_unique_explicit_elements(self) -> "TurnIntentDecisionV2":
        element_kinds = tuple(item.element_kind for item in self.explicit_elements)
        if len(element_kinds) != len(set(element_kinds)):
            raise ValueError("Explicit element decisions must use unique element kinds.")
        if self.mode != "ordinary_conversation":
            if self.ordinary_intent is not None:
                raise ValueError("ordinary_intent is valid only for ordinary_conversation.")
            return self
        if self.ordinary_intent is None:
            raise ValueError("ordinary_conversation requires exactly one ordinary_intent.")
        if self.assistant_message is not None:
            raise ValueError("ordinary assistant_message belongs only inside freeform_reply.")
        if (
            self.requested_capability
            or self.explicit_elements
            or self.requirement_patch is not None
        ):
            raise ValueError("ordinary_conversation cannot carry authoring-only structured fields.")
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
            character_occurrences_to_set=tuple(
                CharacterOccurrencePatchV1.model_validate(item.model_dump())
                for item in compact_patch.character_occurrences_to_set
            )
            if compact_patch.character_occurrences_to_set is not None
            else None,
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
        ordinary_intent=compact.ordinary_intent,
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
    workflow_context: "WorkflowStateCapsuleV1 | None" = None


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
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None

    @model_validator(mode="after")
    def validate_character_identity(self) -> "PlannedCapabilityReferenceV1":
        if (self.occurrence_id is None) != (self.character_phase is None):
            raise ValueError("Character reference identity requires occurrence and phase.")
        return self


class CapabilityReferencePlanV1(_CapabilityModel):
    capability_id: CapabilityIdV1
    references: tuple[PlannedCapabilityReferenceV1, ...] = Field(default=(), max_length=64)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=64)

    @property
    def approved_reference_ids(self) -> tuple[str, ...]:
        return tuple(reference.source_id for reference in self.references)


class CharacterProposalTargetV1(BaseModel):
    """Immutable identity of the Character occurrence a Proposal describes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_id: str = Field(min_length=1, max_length=160)
    occurrence_index: int = Field(ge=1, le=32)
    occurrence_count: int = Field(ge=1, le=32)
    character_phase: Literal["main"] = "main"
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    target_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def digest_for(
        cls,
        *,
        occurrence_id: str,
        occurrence_index: int,
        occurrence_count: int,
        character_phase: Literal["main"] = "main",
        requirement_revision_id: str,
        requirement_revision_no: int,
    ) -> str:
        payload = {
            "character_phase": character_phase,
            "occurrence_count": occurrence_count,
            "occurrence_id": occurrence_id,
            "occurrence_index": occurrence_index,
            "requirement_revision_id": requirement_revision_id,
            "requirement_revision_no": requirement_revision_no,
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        occurrence_id: str,
        occurrence_index: int,
        occurrence_count: int,
        requirement_revision_id: str,
        requirement_revision_no: int,
    ) -> "CharacterProposalTargetV1":
        return cls(
            occurrence_id=occurrence_id,
            occurrence_index=occurrence_index,
            occurrence_count=occurrence_count,
            character_phase="main",
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            target_digest=cls.digest_for(
                occurrence_id=occurrence_id,
                occurrence_index=occurrence_index,
                occurrence_count=occurrence_count,
                requirement_revision_id=requirement_revision_id,
                requirement_revision_no=requirement_revision_no,
            ),
        )

    @model_validator(mode="after")
    def validate_identity(self) -> "CharacterProposalTargetV1":
        if self.occurrence_index > self.occurrence_count:
            raise ValueError("Character occurrence index exceeds the target count.")
        expected = self.digest_for(
            occurrence_id=self.occurrence_id,
            occurrence_index=self.occurrence_index,
            occurrence_count=self.occurrence_count,
            character_phase=self.character_phase,
            requirement_revision_id=self.requirement_revision_id,
            requirement_revision_no=self.requirement_revision_no,
        )
        if self.target_digest != expected:
            raise ValueError("Character proposal target digest does not match its fields.")
        return self


def _validate_character_target_contract(
    *,
    target: CharacterProposalTargetV1 | None,
    capability_id: CapabilityIdV1,
    requirement_revision_id: str,
    requirement_revision_no: int,
    required: bool = False,
) -> None:
    """Keep occurrence scope present only on guided Character Proposal commands."""

    if required and target is None:
        raise ValueError("Guided Character Proposal commands require an occurrence target.")
    if target is None:
        return
    if capability_id != "character_design":
        raise ValueError("Character occurrence scope is valid only for Character proposals.")
    if (
        target.requirement_revision_id != requirement_revision_id
        or target.requirement_revision_no != requirement_revision_no
    ):
        raise ValueError("Character occurrence scope must match the Requirement Ledger revision.")


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
    character_target: CharacterProposalTargetV1 | None = None

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)

    @model_validator(mode="after")
    def validate_character_target(self) -> "CapabilityContextSnapshotV2":
        _validate_character_target_contract(
            target=self.character_target,
            capability_id=self.requirement_projection.capability_id,
            requirement_revision_id=self.requirement_projection.ledger_revision_id,
            requirement_revision_no=self.requirement_projection.ledger_revision_no,
        )
        return self


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
    character_target: CharacterProposalTargetV1 | None = None

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)

    @model_validator(mode="after")
    def validate_character_target(self) -> "CapabilityInvocationContextV2":
        _validate_character_target_contract(
            target=self.character_target,
            capability_id=self.capability_id,
            requirement_revision_id=self.requirement_projection.ledger_revision_id,
            requirement_revision_no=self.requirement_projection.ledger_revision_no,
        )
        return self


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
    character_target: CharacterProposalTargetV1 | None = None

    _validate_context = model_validator(mode="before")(_validate_bounded_context_fields)

    @model_validator(mode="after")
    def validate_character_target(self) -> "CapabilityCommandEnvelopeV2":
        _validate_character_target_contract(
            target=self.character_target,
            capability_id=self.capability_id,
            requirement_revision_id=self.requirement_revision_id,
            requirement_revision_no=self.requirement_revision_no,
            required=(
                self.publication_kind == "proposal"
                and self.capability_id == "character_design"
                and self.session_id is not None
            ),
        )
        return self

    @model_validator(mode="after")
    def validate_publication_boundary(
        self,
        info: ValidationInfo,
    ) -> "CapabilityCommandEnvelopeV2":
        internal_stages = {"narrative_direction", "style_lock", "storyboard_plan"}
        if self.publication_kind == "proposal":
            if self.journey_stage is not None:
                raise ValueError("Proposal commands cannot own an internal journey stage.")
            return self
        if (
            self.capability_id != "script_authoring"
            or self.journey_stage not in internal_stages
            or self.result_contract_name
            not in {"GuidedScriptCheckpointDraftV1", "ScriptMaterializationResultV1"}
            or self.candidate_count != 1
        ):
            raise ValueError("Internal document commands require one fixed Script checkpoint.")
        if self.result_contract_name == "ScriptMaterializationResultV1" and not (
            info.context and info.context.get("allow_retired_historical_envelope")
        ):
            raise ValueError("The retired direct Script checkpoint contract is not accepted.")
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
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    resume_materialization_envelope_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    action_owner: Literal["guided_journey", "targeted_authoring", "quick_media"] = "guided_journey"
    created_at: datetime

    @model_validator(mode="after")
    def validate_character_identity(self) -> "NextActionEnvelopeV1":
        if (self.occurrence_id is None) != (self.character_phase is None):
            raise ValueError("Character next-action identity requires occurrence and phase.")
        return self


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


class GuidedProposalAuthoringOptionV4(_CapabilityModel):
    """Safety-bounded creative text projected into a public Proposal Card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=256)
    public_summary: str = Field(min_length=1, max_length=2_048)


class GuidedProposalAuthoringResultV4(_CapabilityModel):
    """Exact-three authoring result for normal guided Proposal operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    options: tuple[
        GuidedProposalAuthoringOptionV4,
        GuidedProposalAuthoringOptionV4,
        GuidedProposalAuthoringOptionV4,
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
    "world_setting": GuidedProposalAuthoringResultV4,
    "product_design": GuidedProposalAuthoringResultV4,
    "prop_design": GuidedProposalAuthoringResultV4,
    "character_design": GuidedProposalAuthoringResultV4,
    "scene_design": GuidedProposalAuthoringResultV4,
    "script_authoring": GuidedProposalAuthoringResultV4,
    "storyboard_design": GuidedProposalAuthoringResultV4,
    "video_direction": GuidedProposalAuthoringResultV4,
    "bgm_direction": GuidedProposalAuthoringResultV4,
    "quick_media": ProposalCardResultV2,
}


from app.schemas.agent_operation_contexts import WorkflowStateCapsuleV1  # noqa: E402


TurnIntentContextV2.model_rebuild(
    _types_namespace={"WorkflowStateCapsuleV1": WorkflowStateCapsuleV1}
)
