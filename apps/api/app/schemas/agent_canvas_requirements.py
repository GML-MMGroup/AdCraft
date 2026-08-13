"""Strict canonical contracts for Agent Canvas workflow requirements."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1


RequirementSourceKindV1: TypeAlias = Literal[
    "user_message", "accepted_proposal", "manual_edit", "decision_bundle_answer"
]
RequirementRevisionSourceKindV1: TypeAlias = Literal[
    "initialization",
    "user_turn",
    "proposal_selection",
    "manual_edit",
    "node_deletion",
    "decision_bundle_answer",
]
RequirementScopeKindV1: TypeAlias = Literal["global", "capability", "node"]
RequirementStrengthV1: TypeAlias = Literal["hard", "preference"]
RequirementElementKindV1: TypeAlias = Literal[
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
RequirementControlNameV1: TypeAlias = Literal[
    "duration_seconds",
    "aspect_ratio",
    "output_resolution",
    "frame_rate",
    "spoken_language",
    "audio_mode",
    "product_count",
    "prop_count",
    "character_count",
    "scene_count",
    "storyboard_sequence_count",
    "video_segment_count",
]
DurationSecondsValueV1: TypeAlias = Annotated[float, Field(ge=1, le=3_600)]
AspectRatioValueV1: TypeAlias = Annotated[str, Field(min_length=1, max_length=32)]
OutputResolutionValueV1: TypeAlias = Annotated[str, Field(min_length=1, max_length=64)]
FrameRateValueV1: TypeAlias = Annotated[float, Field(ge=1, le=240)]
SpokenLanguageValueV1: TypeAlias = Annotated[str, Field(min_length=1, max_length=64)]
AudioModeValueV1: TypeAlias = Literal["none", "bgm_only", "full"]
ProductCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=32)]
PropCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=64)]
CharacterCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=32)]
SceneCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=32)]
StoryboardSequenceCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=64)]
VideoSegmentCountValueV1: TypeAlias = Annotated[int, Field(ge=0, le=64)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _StoredControlBase(_FrozenModel):
    source_kind: RequirementSourceKindV1
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_proposal_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_bundle_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_question_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_option_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=2_048)
    created_revision_no: int = Field(ge=1)


class DurationSecondsControlV1(_StoredControlBase):
    control: Literal["duration_seconds"] = "duration_seconds"
    value: DurationSecondsValueV1


class AspectRatioControlV1(_StoredControlBase):
    control: Literal["aspect_ratio"] = "aspect_ratio"
    value: AspectRatioValueV1


class OutputResolutionControlV1(_StoredControlBase):
    control: Literal["output_resolution"] = "output_resolution"
    value: OutputResolutionValueV1


class FrameRateControlV1(_StoredControlBase):
    control: Literal["frame_rate"] = "frame_rate"
    value: FrameRateValueV1


class SpokenLanguageControlV1(_StoredControlBase):
    control: Literal["spoken_language"] = "spoken_language"
    value: SpokenLanguageValueV1


class AudioModeControlV1(_StoredControlBase):
    control: Literal["audio_mode"] = "audio_mode"
    value: AudioModeValueV1


class ProductCountControlV1(_StoredControlBase):
    control: Literal["product_count"] = "product_count"
    value: ProductCountValueV1


class PropCountControlV1(_StoredControlBase):
    control: Literal["prop_count"] = "prop_count"
    value: PropCountValueV1


class CharacterCountControlV1(_StoredControlBase):
    control: Literal["character_count"] = "character_count"
    value: CharacterCountValueV1


class SceneCountControlV1(_StoredControlBase):
    control: Literal["scene_count"] = "scene_count"
    value: SceneCountValueV1


class StoryboardSequenceCountControlV1(_StoredControlBase):
    control: Literal["storyboard_sequence_count"] = "storyboard_sequence_count"
    value: StoryboardSequenceCountValueV1


class VideoSegmentCountControlV1(_StoredControlBase):
    control: Literal["video_segment_count"] = "video_segment_count"
    value: VideoSegmentCountValueV1


RequirementControlV1: TypeAlias = Annotated[
    DurationSecondsControlV1
    | AspectRatioControlV1
    | OutputResolutionControlV1
    | FrameRateControlV1
    | SpokenLanguageControlV1
    | AudioModeControlV1
    | ProductCountControlV1
    | PropCountControlV1
    | CharacterCountControlV1
    | SceneCountControlV1
    | StoryboardSequenceCountControlV1
    | VideoSegmentCountControlV1,
    Field(discriminator="control"),
]


class _ControlPatchBase(_StrictModel):
    source_quote: str = Field(min_length=1, max_length=2_048)


class DurationSecondsControlPatchV1(_ControlPatchBase):
    control: Literal["duration_seconds"] = "duration_seconds"
    value: DurationSecondsValueV1


class AspectRatioControlPatchV1(_ControlPatchBase):
    control: Literal["aspect_ratio"] = "aspect_ratio"
    value: AspectRatioValueV1


class OutputResolutionControlPatchV1(_ControlPatchBase):
    control: Literal["output_resolution"] = "output_resolution"
    value: OutputResolutionValueV1


class FrameRateControlPatchV1(_ControlPatchBase):
    control: Literal["frame_rate"] = "frame_rate"
    value: FrameRateValueV1


class SpokenLanguageControlPatchV1(_ControlPatchBase):
    control: Literal["spoken_language"] = "spoken_language"
    value: SpokenLanguageValueV1


class AudioModeControlPatchV1(_ControlPatchBase):
    control: Literal["audio_mode"] = "audio_mode"
    value: AudioModeValueV1


class ProductCountControlPatchV1(_ControlPatchBase):
    control: Literal["product_count"] = "product_count"
    value: ProductCountValueV1


class PropCountControlPatchV1(_ControlPatchBase):
    control: Literal["prop_count"] = "prop_count"
    value: PropCountValueV1


class CharacterCountControlPatchV1(_ControlPatchBase):
    control: Literal["character_count"] = "character_count"
    value: CharacterCountValueV1


class SceneCountControlPatchV1(_ControlPatchBase):
    control: Literal["scene_count"] = "scene_count"
    value: SceneCountValueV1


class StoryboardSequenceCountControlPatchV1(_ControlPatchBase):
    control: Literal["storyboard_sequence_count"] = "storyboard_sequence_count"
    value: StoryboardSequenceCountValueV1


class VideoSegmentCountControlPatchV1(_ControlPatchBase):
    control: Literal["video_segment_count"] = "video_segment_count"
    value: VideoSegmentCountValueV1


RequirementControlPatchV1: TypeAlias = Annotated[
    DurationSecondsControlPatchV1
    | AspectRatioControlPatchV1
    | OutputResolutionControlPatchV1
    | FrameRateControlPatchV1
    | SpokenLanguageControlPatchV1
    | AudioModeControlPatchV1
    | ProductCountControlPatchV1
    | PropCountControlPatchV1
    | CharacterCountControlPatchV1
    | SceneCountControlPatchV1
    | StoryboardSequenceCountControlPatchV1
    | VideoSegmentCountControlPatchV1,
    Field(discriminator="control"),
]


class _ManualControlPatchBase(_StrictModel):
    source_text: str = Field(min_length=1, max_length=2_048)


class ManualDurationSecondsControlPatchV1(_ManualControlPatchBase):
    control: Literal["duration_seconds"] = "duration_seconds"
    value: DurationSecondsValueV1


class ManualAspectRatioControlPatchV1(_ManualControlPatchBase):
    control: Literal["aspect_ratio"] = "aspect_ratio"
    value: AspectRatioValueV1


class ManualOutputResolutionControlPatchV1(_ManualControlPatchBase):
    control: Literal["output_resolution"] = "output_resolution"
    value: OutputResolutionValueV1


class ManualFrameRateControlPatchV1(_ManualControlPatchBase):
    control: Literal["frame_rate"] = "frame_rate"
    value: FrameRateValueV1


class ManualSpokenLanguageControlPatchV1(_ManualControlPatchBase):
    control: Literal["spoken_language"] = "spoken_language"
    value: SpokenLanguageValueV1


class ManualAudioModeControlPatchV1(_ManualControlPatchBase):
    control: Literal["audio_mode"] = "audio_mode"
    value: AudioModeValueV1


class ManualProductCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["product_count"] = "product_count"
    value: ProductCountValueV1


class ManualPropCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["prop_count"] = "prop_count"
    value: PropCountValueV1


class ManualCharacterCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["character_count"] = "character_count"
    value: CharacterCountValueV1


class ManualSceneCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["scene_count"] = "scene_count"
    value: SceneCountValueV1


class ManualStoryboardSequenceCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["storyboard_sequence_count"] = "storyboard_sequence_count"
    value: StoryboardSequenceCountValueV1


class ManualVideoSegmentCountControlPatchV1(_ManualControlPatchBase):
    control: Literal["video_segment_count"] = "video_segment_count"
    value: VideoSegmentCountValueV1


ManualRequirementControlPatchV1: TypeAlias = Annotated[
    ManualDurationSecondsControlPatchV1
    | ManualAspectRatioControlPatchV1
    | ManualOutputResolutionControlPatchV1
    | ManualFrameRateControlPatchV1
    | ManualSpokenLanguageControlPatchV1
    | ManualAudioModeControlPatchV1
    | ManualProductCountControlPatchV1
    | ManualPropCountControlPatchV1
    | ManualCharacterCountControlPatchV1
    | ManualSceneCountControlPatchV1
    | ManualStoryboardSequenceCountControlPatchV1
    | ManualVideoSegmentCountControlPatchV1,
    Field(discriminator="control"),
]


class RequirementDirectiveV1(_FrozenModel):
    directive_id: str = Field(min_length=1, max_length=160)
    source_kind: RequirementSourceKindV1
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_proposal_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_bundle_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_question_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_option_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: RequirementScopeKindV1
    capability_ids: tuple[CapabilityIdV1, ...] = Field(default=(), max_length=10)
    target_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    strength: RequirementStrengthV1
    created_revision_no: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_scope(self) -> "RequirementDirectiveV1":
        _validate_scope(self.scope_kind, self.capability_ids, self.target_node_ids)
        return self


class RequirementDirectivePatchV1(_StrictModel):
    source_quote: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: RequirementScopeKindV1
    capability_ids: tuple[CapabilityIdV1, ...] = Field(default=(), max_length=10)
    target_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    strength: RequirementStrengthV1

    @model_validator(mode="after")
    def validate_scope(self) -> "RequirementDirectivePatchV1":
        _validate_scope(self.scope_kind, self.capability_ids, self.target_node_ids)
        return self


class ManualRequirementDirectivePatchV1(_StrictModel):
    source_text: str = Field(min_length=1, max_length=2_048)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: RequirementScopeKindV1
    capability_ids: tuple[CapabilityIdV1, ...] = Field(default=(), max_length=10)
    target_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    strength: RequirementStrengthV1

    @model_validator(mode="after")
    def validate_scope(self) -> "ManualRequirementDirectivePatchV1":
        _validate_scope(self.scope_kind, self.capability_ids, self.target_node_ids)
        return self


class RequirementElementPresenceV1(_FrozenModel):
    element_kind: RequirementElementKindV1
    presence: Literal["include", "exclude", "unspecified"]
    source_kind: RequirementSourceKindV1
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_bundle_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_question_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_option_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=2_048)
    created_revision_no: int = Field(ge=1)


class RequirementElementPresencePatchV1(_StrictModel):
    element_kind: RequirementElementKindV1
    presence: Literal["include", "exclude", "unspecified"]
    source_quote: str = Field(min_length=1, max_length=2_048)


class RequirementConflictV1(_FrozenModel):
    conflict_id: str = Field(min_length=1, max_length=160)
    control_names: tuple[RequirementControlNameV1, ...] = Field(default=(), max_length=12)
    directive_ids: tuple[str, ...] = Field(default=(), max_length=32)
    explanation: str = Field(min_length=1, max_length=2_048)
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=160)
    created_revision_no: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_references(self) -> "RequirementConflictV1":
        if not self.control_names and not self.directive_ids:
            raise ValueError("Requirement conflicts must reference a control or directive.")
        return self


class RequirementConflictPatchV1(_StrictModel):
    control_names: tuple[RequirementControlNameV1, ...] = Field(default=(), max_length=12)
    directive_ids: tuple[str, ...] = Field(default=(), max_length=32)
    explanation: str = Field(min_length=1, max_length=2_048)
    source_quotes: tuple[str, ...] = Field(min_length=1, max_length=8)


class RequirementPatchV1(_StrictModel):
    controls_to_set: tuple[RequirementControlPatchV1, ...] = Field(default=(), max_length=16)
    directives_to_add: tuple[RequirementDirectivePatchV1, ...] = Field(default=(), max_length=16)
    directive_ids_to_supersede: tuple[str, ...] = Field(default=(), max_length=32)
    conflicts: tuple[RequirementConflictPatchV1, ...] = Field(default=(), max_length=8)


class RequirementLedgerPatchRequestV1(_StrictModel):
    controls_to_set: tuple[ManualRequirementControlPatchV1, ...] = Field(default=(), max_length=16)
    directives_to_add: tuple[ManualRequirementDirectivePatchV1, ...] = Field(
        default=(), max_length=16
    )
    directive_ids_to_supersede: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_non_empty_unique_patch(self) -> "RequirementLedgerPatchRequestV1":
        if (
            not self.controls_to_set
            and not self.directives_to_add
            and not self.directive_ids_to_supersede
        ):
            raise ValueError("Requirement patches must contain at least one change.")
        control_names = tuple(item.control for item in self.controls_to_set)
        if len(control_names) != len(set(control_names)):
            raise ValueError("Requirement patches cannot set a control more than once.")
        if len(self.directive_ids_to_supersede) != len(set(self.directive_ids_to_supersede)):
            raise ValueError("Requirement patches cannot supersede a directive more than once.")
        return self


class RequirementLedgerV1(_FrozenModel):
    schema_version: Literal["1"] = "1"
    hard_controls: tuple[RequirementControlV1, ...] = Field(default=(), max_length=16)
    active_directives: tuple[RequirementDirectiveV1, ...] = Field(default=(), max_length=256)
    element_presence: tuple[RequirementElementPresenceV1, ...] = Field(default=(), max_length=9)
    unresolved_conflicts: tuple[RequirementConflictV1, ...] = Field(default=(), max_length=32)


class RequirementLedgerRevisionV1(_FrozenModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    revision_id: str = Field(min_length=1, max_length=160)
    revision_no: int = Field(ge=1)
    parent_revision_id: str | None = Field(default=None, max_length=160)
    source_kind: RequirementRevisionSourceKindV1
    source_turn_id: str | None = Field(default=None, max_length=160)
    source_proposal_id: str | None = Field(default=None, max_length=160)
    source_bundle_id: str | None = Field(default=None, max_length=160)
    source_node_id: str | None = Field(default=None, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    ledger: RequirementLedgerV1
    updated_at: datetime


class RequirementLedgerResponseV1(_FrozenModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    revision_id: str = Field(min_length=1, max_length=160)
    revision_no: int = Field(ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    hard_controls: tuple[RequirementControlV1, ...] = Field(default=(), max_length=16)
    active_directives: tuple[RequirementDirectiveV1, ...] = Field(default=(), max_length=256)
    element_presence: tuple[RequirementElementPresenceV1, ...] = Field(default=(), max_length=9)
    unresolved_conflicts: tuple[RequirementConflictV1, ...] = Field(default=(), max_length=32)
    updated_at: datetime


class EditableRequirementDirectiveV1(_FrozenModel):
    directive_id: str = Field(min_length=1, max_length=160)
    normalized_meaning: str = Field(min_length=1, max_length=2_048)
    scope_kind: RequirementScopeKindV1
    strength: RequirementStrengthV1
    source_kind: RequirementSourceKindV1


class OmittedRequirementDirectiveV1(_FrozenModel):
    directive_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=160)


class CapabilityRequirementProjectionV1(_FrozenModel):
    ledger_revision_id: str = Field(min_length=1, max_length=160)
    ledger_revision_no: int = Field(ge=1)
    ledger_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_id: CapabilityIdV1
    goal_summary: str = Field(default="", max_length=4_096)
    hard_controls: tuple[RequirementControlV1, ...] = Field(default=(), max_length=16)
    relevant_directives: tuple[RequirementDirectiveV1, ...] = Field(default=(), max_length=256)
    accepted_element_summaries: tuple[str, ...] = Field(default=(), max_length=32)
    direct_text_inputs: tuple[str, ...] = Field(default=(), max_length=32)
    warnings: tuple[str, ...] = Field(default=(), max_length=64)
    included_directive_ids: tuple[str, ...] = Field(default=(), max_length=256)
    omitted_directives: tuple[OmittedRequirementDirectiveV1, ...] = Field(
        default=(), max_length=256
    )


class RequirementApplicationDeltaV1(_FrozenModel):
    changed_control_names: tuple[RequirementControlNameV1, ...] = ()
    added_directive_ids: tuple[str, ...] = ()
    superseded_directive_ids: tuple[str, ...] = ()
    changed_element_kinds: tuple[RequirementElementKindV1, ...] = ()
    conflict_ids: tuple[str, ...] = ()


class RequirementApplicationResultV1(_FrozenModel):
    revision: RequirementLedgerRevisionV1
    delta: RequirementApplicationDeltaV1
    changed: bool


def _validate_scope(
    scope_kind: RequirementScopeKindV1,
    capability_ids: tuple[CapabilityIdV1, ...],
    target_node_ids: tuple[str, ...],
) -> None:
    if scope_kind == "global" and (capability_ids or target_node_ids):
        raise ValueError("Global directives forbid capability and node targets.")
    if scope_kind == "capability" and (not capability_ids or target_node_ids):
        raise ValueError("Capability directives require capability targets only.")
    if scope_kind == "node" and (not target_node_ids or capability_ids):
        raise ValueError("Node directives require node targets only.")
