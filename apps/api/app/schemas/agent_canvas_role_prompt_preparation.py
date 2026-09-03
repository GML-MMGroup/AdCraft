"""Strict contracts for role-specific Agent Canvas prompt preparation."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_reference_conditioning import ReferenceConditioningPlanV1
from app.schemas.agent_canvas_identity_safety import IdentitySafetyDecisionV1
from app.schemas.agent_canvas_prompt_assertion import PromptAssertionEvidenceV1
from app.schemas.agent_canvas_requirements import CharacterAuthoringPhaseV1
from app.schemas.language import BCP47Tag


RolePromptVariantV2 = Literal[
    "world_view",
    "product_main",
    "product_multiview",
    "prop",
    "character_main",
    "character_turnaround",
    "scene_board",
    "script",
    "storyboard_grid",
    "video_segment",
    "bgm",
    "free_text",
    "free_image",
    "free_video",
    "free_audio",
]
RoleParameterSourceKindV2 = Literal[
    "explicit_user",
    "bound_text",
    "node_parameter",
    "storyboard_plan",
    "style_advice",
    "installation_default",
]
RolePromptContextSourceKindV2 = Literal[
    "requirements",
    "selected_direction",
    "user_prompt",
    "style",
    "world_view",
    "bindings",
    "documents",
    "installation",
]
RolePromptContextOwnershipV2 = Literal["compiler", "user", "unknown"]
RolePromptContextDispositionV2 = Literal[
    "preserve",
    "duplicate_candidate",
    "retain_unknown",
]
RolePromptCompactionOutcomeV2 = Literal["preserved", "compacted"]
VideoRepresentationModeV2 = Literal["illustrated", "illustration_to_live_action"]
CharacterGenderPresentationV1 = Literal["masculine", "feminine", "androgynous", "unspecified"]


class _RolePromptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditablePromptProjectionV1(_RolePromptModel):
    """The revision-bound editable prompt view exposed by a prepared Node."""

    text: str = Field(min_length=1, max_length=32_768)
    locale: BCP47Tag
    source: Literal["agent_authored", "deterministic_projection", "user_edited"]
    revision: int = Field(ge=1)
    brief_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _require_editable_prompt_in_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict) or "editable_prompt" not in properties:
        return
    properties["editable_prompt"] = {
        "title": "Editable Prompt",
        "type": "string",
        "minLength": 1,
        "maxLength": 32_768,
    }
    required = schema.setdefault("required", [])
    if "editable_prompt" not in required:
        required.append("editable_prompt")


class _RoleBriefModel(_RolePromptModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra=_require_editable_prompt_in_schema,
    )

    editable_prompt: str | None = Field(default=None, max_length=32_768)


class RoleBindingSnapshotV2(_RolePromptModel):
    binding_id: str = Field(min_length=1, max_length=160)
    binding_revision: int = Field(ge=1)
    source_node_id: str | None = Field(default=None, max_length=160)
    source_node_revision: int | None = Field(default=None, ge=1)
    source_role: str | None = Field(default=None, max_length=80)
    asset_id: str | None = Field(default=None, min_length=1, max_length=160)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    reference_purpose: str = Field(min_length=1, max_length=80)
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    requirement_revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    requirement_revision_no: int | None = Field(default=None, ge=1)
    source_sequence_id: str | None = Field(default=None, min_length=1, max_length=160)
    display_order: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_asset_identity(self) -> "RoleBindingSnapshotV2":
        if (self.asset_id is None) != (self.asset_version_id is None):
            raise ValueError("Binding Asset and version identities must be supplied together.")
        character_values = (
            self.occurrence_id,
            self.character_phase,
            self.requirement_revision_id,
            self.requirement_revision_no,
        )
        if any(value is not None for value in character_values) and not all(
            value is not None for value in character_values
        ):
            raise ValueError("Character Binding provenance must be supplied together.")
        return self


class RoleBoundTextControlV2(_RolePromptModel):
    name: str = Field(min_length=1, max_length=80)
    value: JsonValue
    binding_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)


class RolePromptContextBlockV2(_RolePromptModel):
    """Safe identity metadata for one preserved prompt-context block."""

    schema_version: Literal["1"] = "1"
    block_id: str = Field(min_length=1, max_length=160)
    source_kind: RolePromptContextSourceKindV2
    source_id: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    ownership: RolePromptContextOwnershipV2
    precedence: int = Field(ge=0, le=128)
    effective_constraints_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    disposition: RolePromptContextDispositionV2 = "retain_unknown"
    retained_block_id: str | None = Field(default=None, max_length=160)
    retained_precedence: int | None = Field(default=None, ge=0, le=128)

    @model_validator(mode="after")
    def validate_compaction_candidate(self) -> "RolePromptContextBlockV2":
        if self.disposition == "duplicate_candidate" and (
            self.ownership != "compiler"
            or not self.retained_block_id
            or self.retained_precedence is None
        ):
            raise ValueError(
                "Only compiler-owned blocks with retained identity and precedence may be compacted."
            )
        if self.ownership == "user" and self.disposition != "preserve":
            raise ValueError("User-owned context blocks must be preserved.")
        return self


class RolePromptCompactionPolicyV2(_RolePromptModel):
    """Versioned, opt-in policy for lossless compiler-owned duplicate removal."""

    schema_version: Literal["1"] = "1"
    policy_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=32)
    enabled: bool = False
    eligible_source_kinds: tuple[RolePromptContextSourceKindV2, ...] = Field(
        default=(), max_length=8
    )
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class RolePromptCompactionDecisionV2(_RolePromptModel):
    """Non-content provenance for one context-block disposition."""

    block_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    precedence: int = Field(ge=0, le=128)
    outcome: RolePromptCompactionOutcomeV2
    retained_block_id: str | None = Field(default=None, max_length=160)
    retained_precedence: int | None = Field(default=None, ge=0, le=128)
    reason: Literal[
        "policy_disabled",
        "not_eligible",
        "ownership_unknown",
        "identity_unproven",
        "exact_duplicate",
        "preserved_authority",
    ]


def _projection_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: item.model_dump(mode="json"),
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


class CharacterIdentityAuthorityProjectionV1(_RolePromptModel):
    """Frozen identity authority projected from one Character Main occurrence."""

    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_asset_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    occurrence_id: str = Field(min_length=1, max_length=160)
    identity: str = Field(min_length=1, max_length=4_096)
    face_and_hair: str = Field(min_length=1, max_length=2_048)
    silhouette_and_proportions: str = Field(min_length=1, max_length=2_048)
    wardrobe: str = Field(min_length=1, max_length=2_048)
    accessories: str = Field(max_length=1_024)
    rendering_mode: Literal["detailed_semi_realistic_commercial_illustration"] = (
        "detailed_semi_realistic_commercial_illustration"
    )
    gender_presentation: CharacterGenderPresentationV1 = "unspecified"
    projection_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @classmethod
    def build(cls, **values: object) -> "CharacterIdentityAuthorityProjectionV1":
        payload = dict(values)
        payload.pop("projection_digest", None)
        payload.setdefault("gender_presentation", "unspecified")
        payload.setdefault("rendering_mode", "detailed_semi_realistic_commercial_illustration")
        return cls.model_validate({**payload, "projection_digest": _projection_digest(payload)})

    @model_validator(mode="after")
    def validate_projection_digest(self) -> "CharacterIdentityAuthorityProjectionV1":
        payload = self.model_dump(mode="json", exclude={"projection_digest"})
        if self.projection_digest != _projection_digest(payload):
            raise ValueError("Character identity projection digest does not match its payload.")
        if (self.source_asset_id is None) != (self.source_asset_version_id is None):
            raise ValueError("Character identity Asset and version identities must match.")
        return self


class SceneEnvironmentViewV1(_RolePromptModel):
    """One bounded, typed environment-only Scene view."""

    view_or_zone: str = Field(min_length=1, max_length=1_024)
    spatial_details: str = Field(min_length=1, max_length=4_096)
    allowed_environment_elements: tuple[str, ...] = Field(default=(), max_length=32)


class SceneEnvironmentProjectionV1(_RolePromptModel):
    """Frozen environment authority with no entity or narrative action references."""

    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    environment_identity: str = Field(min_length=1, max_length=4_096)
    spatial_logic: str = Field(min_length=1, max_length=4_096)
    lighting: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    atmosphere: str = Field(min_length=1, max_length=2_048)
    views: tuple[SceneEnvironmentViewV1, ...] = Field(min_length=1, max_length=9)
    entity_references: tuple[str, ...] = Field(default=(), max_length=32)
    action_references: tuple[str, ...] = Field(default=(), max_length=32)
    environment_only: Literal[True] = True
    projection_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @classmethod
    def build(cls, **values: object) -> "SceneEnvironmentProjectionV1":
        payload = dict(values)
        payload.pop("projection_digest", None)
        payload.setdefault("environment_only", True)
        return cls.model_validate({**payload, "projection_digest": _projection_digest(payload)})

    @model_validator(mode="after")
    def validate_projection(self) -> "SceneEnvironmentProjectionV1":
        payload = self.model_dump(mode="json", exclude={"projection_digest"})
        if self.projection_digest != _projection_digest(payload):
            raise ValueError("Scene environment projection digest does not match its payload.")
        return self


class RolePromptPreparationContextV2(_RolePromptModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    role_variant: RolePromptVariantV2
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    character_identity_projection: CharacterIdentityAuthorityProjectionV1 | None = None
    scene_environment_projection: SceneEnvironmentProjectionV1 | None = None
    requirement_facts: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)
    document_revisions: dict[str, int] = Field(default_factory=dict, max_length=16)
    selected_direction: str | None = Field(default=None, max_length=8_192)
    user_prompt: str | None = Field(default=None, max_length=16_384)
    response_locale: str = Field(default="und", min_length=2, max_length=35)
    internal_skill_ref: str = Field(min_length=1, max_length=320)
    style_projection: str | None = Field(default=None, max_length=8_192)
    world_view_projection: str | None = Field(default=None, max_length=8_192)
    bindings: tuple[RoleBindingSnapshotV2, ...] = Field(default=(), max_length=32)
    context_blocks: tuple[RolePromptContextBlockV2, ...] = Field(default=(), max_length=64)
    world_view_block_id: str | None = Field(default=None, max_length=160)
    explicit_controls: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    bound_text_controls: tuple[RoleBoundTextControlV2, ...] = Field(default=(), max_length=32)
    node_parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    storyboard_parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    style_parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    installation_parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    video_representation_mode: VideoRepresentationModeV2 | None = None
    video_representation_source: str | None = Field(default=None, max_length=160)
    video_representation_source_id: str | None = Field(default=None, max_length=160)
    video_representation_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    identity_safety_decision: IdentitySafetyDecisionV1 | None = None
    identity_safety_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    model_policy_revision: int = Field(ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_binding_snapshots(self) -> "RolePromptPreparationContextV2":
        identities = tuple(item.binding_id for item in self.bindings)
        if len(identities) != len(set(identities)):
            raise ValueError("Role prompt Binding snapshots must be unique.")
        if tuple(sorted(self.bindings, key=lambda item: (item.display_order, item.binding_id))) != (
            self.bindings
        ):
            raise ValueError("Role prompt Binding snapshots must use canonical order.")
        block_ids = tuple(item.block_id for item in self.context_blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Role prompt context block identities must be unique.")
        if tuple(
            sorted(self.context_blocks, key=lambda item: (item.precedence, item.block_id))
        ) != (self.context_blocks):
            raise ValueError("Role prompt context blocks must use canonical order.")
        if self.world_view_block_id is not None and self.world_view_block_id not in block_ids:
            raise ValueError("WorldView block identity must refer to a context block.")
        control_names = tuple(item.name for item in self.bound_text_controls)
        if len(control_names) != len(set(control_names)):
            raise ValueError("Bound Text controls must have unique canonical names.")
        expected_phase = {
            "character_main": "main",
            "character_turnaround": "turnaround",
        }.get(self.role_variant)
        if expected_phase is not None and (
            self.occurrence_id is None or self.character_phase != expected_phase
        ):
            raise ValueError("Character prompt context requires one occurrence and exact phase.")
        if expected_phase is None and (
            self.occurrence_id is not None or self.character_phase is not None
        ):
            raise ValueError("Non-Character prompt context cannot carry Character identity.")
        if self.role_variant == "character_turnaround":
            projection = self.character_identity_projection
            if projection is not None and projection.occurrence_id != self.occurrence_id:
                raise ValueError("Character Turnaround projection occurrence does not match context.")
            if self.scene_environment_projection is not None:
                raise ValueError("Character context cannot carry Scene environment projection.")
        elif self.role_variant == "scene_board":
            if self.character_identity_projection is not None:
                raise ValueError("Scene context cannot carry Character identity projection.")
        elif self.character_identity_projection is not None or self.scene_environment_projection is not None:
            raise ValueError("Role context carries a projection for an unrelated role.")
        if self.role_variant == "video_segment":
            character_bindings = tuple(
                item for item in self.bindings if item.source_role == "character"
            )
            occurrence_ids = tuple(item.occurrence_id for item in character_bindings)
            if any(
                item.occurrence_id is None or item.character_phase != "turnaround"
                for item in character_bindings
            ) or len(occurrence_ids) != len(set(occurrence_ids)):
                raise ValueError(
                    "Video Character references require distinct Turnaround occurrences."
                )
        return self


class RolePromptPreparationRequestV2(_RolePromptModel):
    operation_id: str = Field(min_length=1, max_length=160)
    recipe_id: str = Field(min_length=1, max_length=160)
    recipe_version: str = Field(min_length=1, max_length=32)
    recipe_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context: RolePromptPreparationContextV2


class NodePromptPreparationV2(_RolePromptModel):
    status: Literal["queued", "working", "ready", "failed", "superseded"]
    operation_id: str = Field(min_length=1, max_length=160)
    presentation_stream_id: str | None = Field(default=None, max_length=160)
    attempt_no: int = Field(ge=0)
    role_variant: RolePromptVariantV2
    recipe_id: str = Field(min_length=1, max_length=160)
    recipe_version: str = Field(min_length=1, max_length=32)
    recipe_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_revision: int = Field(ge=1)
    requirement_revision_id: str = Field(min_length=1, max_length=160)
    requirement_revision_no: int = Field(ge=1)
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    character_phase: CharacterAuthoringPhaseV1 | None = None
    document_revisions: dict[str, int] = Field(default_factory=dict, max_length=16)
    binding_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    style_projection_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    model_policy_revision: int = Field(ge=1)
    context_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    brief_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    prompt_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    parameter_origins: tuple["ResolvedNodeParameterV2", ...] = Field(
        default=(),
        max_length=32,
    )
    compaction_policy_version: str | None = Field(default=None, max_length=32)
    compaction_policy_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    compaction_decisions: tuple[RolePromptCompactionDecisionV2, ...] = Field(
        default=(), max_length=64
    )
    attempt_stage: str | None = Field(default=None, max_length=80)
    error: CanvasNodeErrorV2 | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_status(self) -> "NodePromptPreparationV2":
        if self.status == "ready" and (
            self.context_digest is None
            or self.binding_digest is None
            or self.brief_digest is None
            or self.prompt_digest is None
        ):
            raise ValueError("Ready role prompt preparation requires complete provenance.")
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed role prompt preparation requires a safe error.")
        if self.status not in {"failed", "superseded"} and self.error is not None:
            raise ValueError("Only failed or superseded preparation may carry an error.")
        return self


class WorldViewRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["world_view"] = "world_view"
    premise: str = Field(min_length=1, max_length=4_096)
    era_and_place: str = Field(min_length=1, max_length=2_048)
    world_rules: tuple[str, ...] = Field(min_length=1, max_length=16)
    visual_continuity: tuple[str, ...] = Field(min_length=1, max_length=16)


class ProductMainRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["product_main"] = "product_main"
    identity: str = Field(min_length=1, max_length=4_096)
    geometry: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    marks: str = Field(min_length=1, max_length=2_048)
    palette: str = Field(min_length=1, max_length=1_024)


class ProductMultiviewRoleBriefV2(ProductMainRoleBriefV2):
    role_variant: Literal["product_multiview"] = "product_multiview"
    views: tuple[str, ...] = Field(min_length=5, max_length=8)


class PropRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["prop"] = "prop"
    identity: str = Field(min_length=1, max_length=4_096)
    form: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    palette: str = Field(min_length=1, max_length=1_024)


class CharacterMainRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["character_main"] = "character_main"
    identity: str = Field(min_length=1, max_length=4_096)
    face_and_hair: str = Field(min_length=1, max_length=2_048)
    silhouette_and_proportions: str = Field(min_length=1, max_length=2_048)
    wardrobe: str = Field(min_length=1, max_length=2_048)
    accessories: str = Field(default="", max_length=1_024)
    gender_presentation: CharacterGenderPresentationV1 = "unspecified"
    rendering_mode: Literal["detailed_semi_realistic_commercial_illustration"] = (
        "detailed_semi_realistic_commercial_illustration"
    )


class CharacterTurnaroundRoleBriefV2(CharacterMainRoleBriefV2):
    role_variant: Literal["character_turnaround"] = "character_turnaround"
    views: tuple[Literal["front", "side", "back"], ...] = ("front", "side", "back")

    @model_validator(mode="after")
    def validate_views(self) -> "CharacterTurnaroundRoleBriefV2":
        if self.views != ("front", "side", "back"):
            raise ValueError("Character Turnaround views must be front, side, and back.")
        return self


class SceneBoardRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["scene_board"] = "scene_board"
    environment_identity: str = Field(min_length=1, max_length=4_096)
    spatial_logic: str = Field(min_length=1, max_length=4_096)
    lighting: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    atmosphere: str = Field(min_length=1, max_length=2_048)
    views: tuple[str, ...] = Field(min_length=9, max_length=9)
    entity_references: tuple[str, ...] = Field(default=(), max_length=32)
    action_references: tuple[str, ...] = Field(default=(), max_length=32)
    environment_only: Literal[True] = True


class ScriptRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["script"] = "script"
    narrative: str = Field(min_length=1, max_length=16_384)
    timing: str = Field(min_length=1, max_length=2_048)
    dialogue: str = Field(default="", max_length=8_192)
    voiceover: str = Field(default="", max_length=8_192)


class StoryboardGridRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["storyboard_grid"] = "storyboard_grid"
    sequence_summary: str = Field(min_length=1, max_length=8_192)
    beats: tuple[str, ...] = Field(min_length=9, max_length=9)
    visual_language: str = Field(min_length=1, max_length=4_096)


class VideoSegmentRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["video_segment"] = "video_segment"
    segment_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=15)
    action: str = Field(min_length=1, max_length=8_192)
    dialogue: str = Field(default="", max_length=8_192)
    voiceover: str = Field(default="", max_length=8_192)
    ambience: str = Field(default="", max_length=4_096)
    action_effects: str = Field(default="", max_length=4_096)
    target_style: str = Field(min_length=1, max_length=4_096)


class BgmRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["bgm"] = "bgm"
    music_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=3_600)
    pace: str = Field(min_length=1, max_length=1_024)
    energy_curve: str = Field(min_length=1, max_length=2_048)
    instrumentation: str = Field(min_length=1, max_length=2_048)
    mood: str = Field(min_length=1, max_length=1_024)


class FreeMediaRoleBriefV2(_RoleBriefModel):
    role_variant: Literal["free_text", "free_image", "free_video", "free_audio"]
    prompt: str = Field(min_length=1, max_length=16_384)


RoleCreativeBriefMemberV2: TypeAlias = Annotated[
    WorldViewRoleBriefV2
    | ProductMainRoleBriefV2
    | ProductMultiviewRoleBriefV2
    | PropRoleBriefV2
    | CharacterMainRoleBriefV2
    | CharacterTurnaroundRoleBriefV2
    | SceneBoardRoleBriefV2
    | ScriptRoleBriefV2
    | StoryboardGridRoleBriefV2
    | VideoSegmentRoleBriefV2
    | BgmRoleBriefV2
    | FreeMediaRoleBriefV2,
    Field(discriminator="role_variant"),
]


class RoleCreativeBriefV2(RootModel[RoleCreativeBriefMemberV2]):
    """Closed wrapper for every role-specific model-authored brief."""

    def __init__(self, **data: Any) -> None:
        if set(data) == {"root"}:
            super().__init__(root=data["root"])
            return
        super().__init__(root=data)

    @property
    def role_variant(self) -> RolePromptVariantV2:
        return self.root.role_variant

    @model_validator(mode="after")
    def require_editable_prompt(self) -> RoleCreativeBriefV2:
        if not self.root.editable_prompt or not self.root.editable_prompt.strip():
            raise ValueError("Role brief must include a non-blank editable_prompt.")
        return self


class ResolvedNodeParameterV2(_RolePromptModel):
    name: str = Field(min_length=1, max_length=80)
    value: JsonValue
    source_kind: RoleParameterSourceKindV2
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)


class CompiledNodePromptV2(_RolePromptModel):
    role_variant: RolePromptVariantV2
    recipe_id: str = Field(min_length=1, max_length=160)
    recipe_version: str = Field(min_length=1, max_length=32)
    recipe_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reference_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    style_projection_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    brief_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    prompt: str = Field(min_length=1, max_length=32_768)
    editable_prompt: str | None = Field(default=None, max_length=32_768)
    negative_prompt: str = Field(default="", max_length=16_384)
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: tuple[ResolvedNodeParameterV2, ...] = Field(default=(), max_length=32)
    reference_purposes: tuple[str, ...] = Field(default=(), max_length=32)
    role_reference_policy_version: str | None = Field(default=None, max_length=64)
    reference_conditioning_plan: ReferenceConditioningPlanV1 | None = None
    assertion_evidence: PromptAssertionEvidenceV1
    compaction_policy_version: str = Field(min_length=1, max_length=32)
    compaction_policy_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    compaction_decisions: tuple[RolePromptCompactionDecisionV2, ...] = Field(
        default=(), max_length=64
    )
