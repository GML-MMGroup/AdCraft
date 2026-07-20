from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.workflow_v2_planning import (
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptScene,
)


V2ScriptSourceAction = Literal["initial_planning", "script_editor_confirm", "agent_chat_edit"]
V2SpecialistRole = Literal["product", "character", "scene", "storyboard", "bgm"]
V2AspectRatio = Literal["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"]


class V2ScriptDialogueLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue_id: str
    character_id: str
    performance_cue: str | None = None
    text: str

    @field_validator("dialogue_id", "character_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _required_id(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @field_validator("performance_cue")
    @classmethod
    def validate_performance_cue(cls, value: str | None) -> str | None:
        return _optional_user_text(value)


class V2ScriptShotV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    scene_id: str
    shot_index: int = Field(ge=1)
    product_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    reference_item_ids: list[str] = Field(default_factory=list)
    description: str
    dialogue: list[V2ScriptDialogueLine] = Field(default_factory=list)
    narration: str | None = None
    visual_prompt: str
    duration_seconds: int = Field(ge=1)

    @field_validator("shot_id", "scene_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _required_id(value)

    @field_validator("product_ids", "character_ids", "scene_ids", "reference_item_ids")
    @classmethod
    def validate_reference_ids(cls, value: list[str]) -> list[str]:
        cleaned = [_required_id(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("reference ID values must be unique")
        return cleaned

    @field_validator("description", "visual_prompt")
    @classmethod
    def validate_required_user_text(cls, value: str) -> str:
        return _required_user_text(value)

    @field_validator("narration")
    @classmethod
    def validate_narration(cls, value: str | None) -> str | None:
        return _optional_user_text(value)

    @model_validator(mode="after")
    def validate_reference_union(self) -> "V2ScriptShotV2":
        expected_non_scene = list(dict.fromkeys([*self.product_ids, *self.character_ids]))
        actual_non_scene = [
            item_id for item_id in self.reference_item_ids if not item_id.startswith("scene-")
        ]
        if actual_non_scene != expected_non_scene:
            raise ValueError("reference_item_ids must equal the canonical reference union")
        self.scene_ids = [self.scene_id]
        self.reference_item_ids = list(dict.fromkeys([*expected_non_scene, self.scene_id]))
        return self


class V2ScriptPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_plan_version: Literal[2] = 2
    script_brief_id: str
    script_version_id: str
    language: str
    script_title: str
    script_text: str = ""
    scenes: list[V2ScriptScene] = Field(min_length=1)
    shots: list[V2ScriptShotV2] = Field(min_length=1)
    characters: list[V2ScriptCharacter] = Field(default_factory=list)
    locations: list[V2ScriptLocation] = Field(default_factory=list)
    product_beats: list[str] = Field(default_factory=list)
    tone: str
    visual_style: str
    duration_seconds: int = Field(ge=1)
    aspect_ratio: V2AspectRatio
    materializer_mode: Literal["real", "mock"]
    model_id: str | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    selected_skill_paths: list[str] = Field(default_factory=list)
    skill_context_warnings: list[dict[str, Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    materializer_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("script_brief_id", "script_version_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _required_id(value)

    @field_validator("language", "script_title", "tone", "visual_style")
    @classmethod
    def validate_required_user_text(cls, value: str) -> str:
        return _required_user_text(value)

    @field_validator("script_text")
    @classmethod
    def preserve_script_text(cls, value: str) -> str:
        return str(value)

    @model_validator(mode="after")
    def validate_screenplay_contract(self) -> "V2ScriptPlanV2":
        _require_unique([item.scene_id for item in self.scenes], "scene_id")
        _require_unique([item.shot_id for item in self.shots], "shot_id")
        _require_unique([item.character_id for item in self.characters], "character_id")
        _require_unique([item.location_id for item in self.locations], "location_id")
        dialogue_ids = [line.dialogue_id for shot in self.shots for line in shot.dialogue]
        _require_unique(dialogue_ids, "dialogue_id")

        expected_indexes = list(range(1, len(self.shots) + 1))
        if [shot.shot_index for shot in self.shots] != expected_indexes:
            raise ValueError("shot_index values must be contiguous")
        if sum(shot.duration_seconds for shot in self.shots) != self.duration_seconds:
            raise ValueError("shot durations must equal screenplay duration")

        scene_ids = {item.scene_id for item in self.scenes}
        character_ids = {item.character_id for item in self.characters}
        location_ids = {item.location_id for item in self.locations}
        for scene in self.scenes:
            if scene.location_id and scene.location_id not in location_ids:
                raise ValueError(f"unknown scene location_id: {scene.location_id}")
            owning_shots = [shot for shot in self.shots if shot.scene_id == scene.scene_id]
            if scene.shot_ids != [shot.shot_id for shot in owning_shots]:
                raise ValueError(f"scene shot_ids do not match owning shots: {scene.scene_id}")
            if scene.duration_seconds != sum(shot.duration_seconds for shot in owning_shots):
                raise ValueError(f"scene duration does not match owning shots: {scene.scene_id}")

        for shot in self.shots:
            if shot.scene_id not in scene_ids or any(
                scene_id not in scene_ids for scene_id in shot.scene_ids
            ):
                raise ValueError(f"unknown shot scene_id: {shot.scene_id}")
            unknown_characters = [
                character_id
                for character_id in shot.character_ids
                if character_id not in character_ids
            ]
            if unknown_characters:
                raise ValueError(f"unknown shot character_id: {unknown_characters[0]}")
            for line in shot.dialogue:
                if line.character_id not in character_ids:
                    raise ValueError(f"unknown dialogue character_id: {line.character_id}")
        return self


class _EditableIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_key: str | None = None

    @field_validator("client_key")
    @classmethod
    def validate_client_key(cls, value: str | None) -> str | None:
        return _optional_id(value)


class V2EditableScriptDialogue(_EditableIdentity):
    dialogue_id: str | None = None
    character_id: str
    performance_cue: str | None = None
    text: str

    @field_validator("dialogue_id")
    @classmethod
    def validate_dialogue_id(cls, value: str | None) -> str | None:
        return _optional_id(value)

    @field_validator("character_id")
    @classmethod
    def validate_character_reference(cls, value: str) -> str:
        return _required_id(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @field_validator("performance_cue")
    @classmethod
    def validate_cue(cls, value: str | None) -> str | None:
        return _optional_user_text(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "V2EditableScriptDialogue":
        _require_existing_or_new(self.dialogue_id, self.client_key, "dialogue")
        return self


class V2EditableScriptShot(_EditableIdentity):
    shot_id: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    description: str
    dialogue: list[V2EditableScriptDialogue] = Field(default_factory=list)
    narration: str | None = None
    visual_prompt: str
    duration_seconds: int = Field(ge=1)

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, value: str | None) -> str | None:
        return _optional_id(value)

    @field_validator("product_ids", "character_ids", "scene_ids")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        cleaned = [_required_id(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("editable reference values must be unique")
        return cleaned

    @field_validator("description", "visual_prompt")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @field_validator("narration")
    @classmethod
    def validate_narration(cls, value: str | None) -> str | None:
        return _optional_user_text(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "V2EditableScriptShot":
        _require_existing_or_new(self.shot_id, self.client_key, "shot")
        return self


class V2EditableScriptScene(_EditableIdentity):
    scene_id: str | None = None
    title: str
    description: str
    location_id: str | None = None
    location_type: str | None = None
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None
    shots: list[V2EditableScriptShot] = Field(min_length=1)

    @field_validator("scene_id", "location_id")
    @classmethod
    def validate_optional_reference(cls, value: str | None) -> str | None:
        return _optional_id(value)

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "V2EditableScriptScene":
        _require_existing_or_new(self.scene_id, self.client_key, "scene")
        return self


class V2EditableScriptCharacter(_EditableIdentity):
    character_id: str | None = None
    display_name: str
    description: str
    role: str
    visual_notes: str
    gender: str | None = None

    @field_validator("character_id")
    @classmethod
    def validate_character_id(cls, value: str | None) -> str | None:
        return _optional_id(value)

    @field_validator("display_name", "description", "role", "visual_notes")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "V2EditableScriptCharacter":
        _require_existing_or_new(self.character_id, self.client_key, "character")
        return self


class V2EditableScriptLocation(_EditableIdentity):
    location_id: str | None = None
    display_name: str
    description: str
    visual_notes: str
    location_type: str | None = None
    time_of_day: str | None = None
    setting_type: Literal["interior", "exterior"] | None = None

    @field_validator("location_id")
    @classmethod
    def validate_location_id(cls, value: str | None) -> str | None:
        return _optional_id(value)

    @field_validator("display_name", "description", "visual_notes")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "V2EditableScriptLocation":
        _require_existing_or_new(self.location_id, self.client_key, "location")
        return self


class V2EditableScriptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_title: str
    language: str
    characters: list[V2EditableScriptCharacter] = Field(default_factory=list)
    locations: list[V2EditableScriptLocation] = Field(default_factory=list)
    scenes: list[V2EditableScriptScene] = Field(min_length=1)
    product_beats: list[str] = Field(default_factory=list)
    tone: str
    visual_style: str
    aspect_ratio: V2AspectRatio

    @field_validator("script_title", "language", "tone", "visual_style")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_user_text(value)

    @model_validator(mode="after")
    def validate_document_keys(self) -> "V2EditableScriptDocument":
        namespaces = {
            "character": [(item.character_id, item.client_key) for item in self.characters],
            "location": [(item.location_id, item.client_key) for item in self.locations],
            "scene": [(item.scene_id, item.client_key) for item in self.scenes],
            "shot": [
                (shot.shot_id, shot.client_key) for scene in self.scenes for shot in scene.shots
            ],
            "dialogue": [
                (line.dialogue_id, line.client_key)
                for scene in self.scenes
                for shot in scene.shots
                for line in shot.dialogue
            ],
        }
        for namespace, identities in namespaces.items():
            keys = [canonical_id or client_key or "" for canonical_id, client_key in identities]
            _require_unique(keys, f"{namespace} canonical ID or client_key")
        return self


class V2ScriptConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_script_version_id: str
    document: V2EditableScriptDocument
    source_action: Literal["script_editor_confirm", "agent_chat_edit"] = "script_editor_confirm"

    @field_validator("base_script_version_id")
    @classmethod
    def validate_base_id(cls, value: str) -> str:
        return _required_id(value)


class V2ScriptSelectVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_selected_script_version_id: str

    @field_validator("base_selected_script_version_id")
    @classmethod
    def validate_base_id(cls, value: str) -> str:
        return _required_id(value)


class V2ScriptStructuralDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_character_ids: list[str] = Field(default_factory=list)
    archived_character_ids: list[str] = Field(default_factory=list)
    reactivated_character_ids: list[str] = Field(default_factory=list)
    updated_character_ids: list[str] = Field(default_factory=list)
    added_location_ids: list[str] = Field(default_factory=list)
    archived_location_ids: list[str] = Field(default_factory=list)
    reactivated_location_ids: list[str] = Field(default_factory=list)
    updated_location_ids: list[str] = Field(default_factory=list)
    added_scene_ids: list[str] = Field(default_factory=list)
    archived_scene_ids: list[str] = Field(default_factory=list)
    reactivated_scene_ids: list[str] = Field(default_factory=list)
    updated_scene_ids: list[str] = Field(default_factory=list)
    added_shot_ids: list[str] = Field(default_factory=list)
    archived_shot_ids: list[str] = Field(default_factory=list)
    reactivated_shot_ids: list[str] = Field(default_factory=list)
    updated_shot_ids: list[str] = Field(default_factory=list)
    added_dialogue_ids: list[str] = Field(default_factory=list)
    archived_dialogue_ids: list[str] = Field(default_factory=list)
    updated_dialogue_ids: list[str] = Field(default_factory=list)
    order_changed: bool = False

    def structure_changed(self) -> bool:
        return bool(
            self.order_changed
            or self.added_character_ids
            or self.archived_character_ids
            or self.reactivated_character_ids
            or self.added_location_ids
            or self.archived_location_ids
            or self.reactivated_location_ids
            or self.added_scene_ids
            or self.archived_scene_ids
            or self.reactivated_scene_ids
            or self.added_shot_ids
            or self.archived_shot_ids
            or self.reactivated_shot_ids
        )


class V2LinkedContextSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated_node_ids: list[str] = Field(default_factory=list)
    updated_item_ids: list[str] = Field(default_factory=list)
    updated_slot_ids: list[str] = Field(default_factory=list)
    updated_fields: list[str] = Field(default_factory=list)
    selected_asset_versions_changed: Literal[False] = False
    provider_execution_started: Literal[False] = False
    refresh: list[str] = Field(default_factory=list)


class V2ScriptReadResponse(BaseModel):
    workflow_id: str
    selected_script_version_id: str
    script: V2ScriptPlanV2
    events_cursor: int = Field(ge=0)


class V2ScriptConfirmResponse(V2ScriptReadResponse):
    structural_diff: V2ScriptStructuralDiff
    linked_context: V2LinkedContextSummary


class V2ScriptSelectVersionResponse(V2ScriptReadResponse):
    structural_diff: V2ScriptStructuralDiff
    linked_context: V2LinkedContextSummary


class V2ScriptVersionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_version_id: str
    parent_script_version_id: str | None = None
    created_at: str
    source_action: V2ScriptSourceAction
    script_title: str
    content_hash: str
    structural_diff_summary: dict[str, Any] = Field(default_factory=dict)


class V2ScriptVersionListResponse(BaseModel):
    workflow_id: str
    selected_script_version_id: str
    versions: list[V2ScriptVersionSummary] = Field(default_factory=list)
    events_cursor: int = Field(ge=0)


class V2ScriptVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    script_version_id: str
    parent_script_version_id: str | None = None
    created_at: str
    source_action: V2ScriptSourceAction
    script: V2ScriptPlanV2
    structural_diff: V2ScriptStructuralDiff
    content_hash: str
    migration_source: str | None = None


class V2ScriptVersionIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    selected_script_version_id: str
    versions: list[V2ScriptVersionSummary] = Field(default_factory=list)


class V2ScriptTransactionEventIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class V2ScriptPendingTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    prior_selected_script_version_id: str | None = None
    target_script_version_id: str
    prepared_at: str
    event_intents: list[V2ScriptTransactionEventIntent] = Field(default_factory=list)


class V2SelectedReferenceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    version_id: str
    media_type: str
    semantic_type: str | None = None
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    display_name: str | None = None
    media_handle: str


class V2ScreenplaySlice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_version_id: str
    specialist: V2SpecialistRole
    source_scene_ids: list[str] = Field(default_factory=list)
    source_shot_ids: list[str] = Field(default_factory=list)
    product_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    title: str
    summary: str
    product_beats: list[str] = Field(default_factory=list)
    products: list[dict[str, Any]] = Field(default_factory=list)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    shots: list[dict[str, Any]] = Field(default_factory=list)
    cell_plan: list[dict[str, Any]] = Field(default_factory=list)
    timing: list[dict[str, Any]] = Field(default_factory=list)


class V2SpecialistHandoffContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    specialist: V2SpecialistRole
    node_id: str
    item_id: str | None = None
    slot_id: str | None = None
    script_version_id: str
    screenplay_slice: V2ScreenplaySlice
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    system_suggested_prompt: str
    user_prompt: str | None = None
    latest_user_instruction: str | None = None
    selected_references: list[V2SelectedReferenceDescriptor] = Field(default_factory=list)


class V2GenerationLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_version_id: str
    source_scene_ids: list[str] = Field(default_factory=list)
    source_shot_ids: list[str] = Field(default_factory=list)
    system_prompt_hash: str
    user_prompt_hash: str
    selected_reference_version_ids: list[str] = Field(default_factory=list)
    generation_context_hash: str


def _required_id(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("ID must not be empty")
    return text


def _optional_id(value: Any) -> str | None:
    if value is None:
        return None
    return _required_id(value)


def _required_user_text(value: Any) -> str:
    text = str(value)
    if not text.strip():
        raise ValueError("field must not be empty")
    return text


def _optional_user_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def _require_existing_or_new(
    canonical_id: str | None,
    client_key: str | None,
    label: str,
) -> None:
    if bool(canonical_id) == bool(client_key):
        raise ValueError(f"editable {label} requires exactly one canonical ID or client_key")
