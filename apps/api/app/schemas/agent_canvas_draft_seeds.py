"""Private typed Draft Seeds for deterministic Agent Canvas publication."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


DraftSeedCapabilityIdV1: TypeAlias = Literal[
    "world_setting",
    "product_design",
    "prop_design",
    "character_design",
    "scene_design",
    "script_authoring",
    "storyboard_design",
    "video_direction",
    "bgm_direction",
]


class _DraftSeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


BoundedTextV1 = Annotated[str, Field(min_length=1, max_length=8_192)]
BoundedItemV1 = Annotated[str, Field(min_length=1, max_length=2_048)]


class AcceptedProposalCommitmentV1(_DraftSeedModel):
    normalized_meaning: str = Field(min_length=1, max_length=512)
    source_fragment: str = Field(min_length=1, max_length=512)
    strength: Literal["preference"] = "preference"


class WorldSettingDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["world_setting"]
    premise: BoundedTextV1
    era_and_place: BoundedTextV1
    world_rules: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=8)
    visual_continuity: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=8)
    prompt_brief: BoundedTextV1


class ProductDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["product_design"]
    identity: BoundedTextV1
    selling_focus: BoundedTextV1
    form: BoundedTextV1
    materials: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=16)
    color_palette: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=16)
    presentation_intent: BoundedTextV1
    exclusions: tuple[BoundedItemV1, ...] = Field(default=(), max_length=32)


class PropDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["prop_design"]
    identity: BoundedTextV1
    function: BoundedTextV1
    form: BoundedTextV1
    materials: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=16)
    color_palette: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=16)
    presentation_intent: BoundedTextV1
    exclusions: tuple[BoundedItemV1, ...] = Field(default=(), max_length=32)


class CharacterDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["character_design"]
    identity: BoundedTextV1
    appearance: BoundedTextV1
    wardrobe: BoundedTextV1
    performance_role: BoundedTextV1
    visual_medium: BoundedTextV1
    presentation_intent: BoundedTextV1
    exclusions: tuple[BoundedItemV1, ...] = Field(default=(), max_length=32)


class SceneDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["scene_design"]
    identity: BoundedTextV1
    spatial_layout: BoundedTextV1
    lighting: BoundedTextV1
    materials: BoundedTextV1
    time_of_day: BoundedItemV1
    atmosphere: BoundedTextV1
    exclusions: tuple[BoundedItemV1, ...] = Field(default=(), max_length=32)


class ScriptDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["script_authoring"]
    premise: BoundedTextV1
    audience_objective: BoundedTextV1
    narrative_beats: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=32)
    dialogue_direction: BoundedTextV1
    duration_seconds: float = Field(gt=0, le=3_600)


class StoryboardPanelSeedV1(_DraftSeedModel):
    panel_index: int = Field(ge=1, le=9)
    beat: BoundedItemV1
    composition: BoundedItemV1
    camera: BoundedItemV1
    subject_action: BoundedItemV1
    continuity_from_previous: BoundedItemV1


class StoryboardDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["storyboard_design"]
    sequence_summary: BoundedTextV1
    panel_beats: tuple[StoryboardPanelSeedV1, ...] = Field(min_length=9, max_length=9)
    continuity_anchors: tuple[BoundedItemV1, ...] = Field(min_length=1, max_length=16)
    camera_language: BoundedTextV1
    exclusions: tuple[BoundedItemV1, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_panel_order(self) -> "StoryboardDraftSeedV1":
        if tuple(panel.panel_index for panel in self.panel_beats) != tuple(range(1, 10)):
            raise ValueError("Storyboard Draft Seed panels must be ordered from 1 through 9.")
        return self


class VideoTimingBeatSeedV1(_DraftSeedModel):
    start_seconds: float = Field(ge=0, le=3_600)
    end_seconds: float = Field(gt=0, le=3_600)
    action: BoundedItemV1

    @model_validator(mode="after")
    def validate_time_range(self) -> "VideoTimingBeatSeedV1":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Video timing beats require end_seconds after start_seconds.")
        return self


class VideoDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["video_direction"]
    segment_summary: BoundedTextV1
    timing_beats: tuple[VideoTimingBeatSeedV1, ...] = Field(min_length=1, max_length=32)
    camera_language: BoundedTextV1
    motion: BoundedTextV1
    native_audio_direction: BoundedTextV1
    target_style: BoundedTextV1
    duration_seconds: float = Field(gt=0, le=3_600)

    @model_validator(mode="after")
    def validate_timing_beats(self) -> "VideoDraftSeedV1":
        if self.timing_beats[-1].end_seconds > self.duration_seconds:
            raise ValueError("Video timing beats cannot exceed the Seed duration.")
        if any(
            current.start_seconds < previous.end_seconds
            for previous, current in zip(self.timing_beats, self.timing_beats[1:])
        ):
            raise ValueError("Video timing beats cannot overlap or run out of order.")
        return self


class BgmDraftSeedV1(_DraftSeedModel):
    seed_kind: Literal["bgm_direction"]
    mood: BoundedItemV1
    instrumentation: BoundedTextV1
    pace: BoundedItemV1
    energy_curve: BoundedTextV1
    duration_seconds: float = Field(gt=0, le=3_600)
    instrumental_only: Literal[True] = True
    no_vocals: Literal[True] = True
    no_lyrics: Literal[True] = True


DraftSeedV1: TypeAlias = Annotated[
    WorldSettingDraftSeedV1
    | ProductDraftSeedV1
    | PropDraftSeedV1
    | CharacterDraftSeedV1
    | SceneDraftSeedV1
    | ScriptDraftSeedV1
    | StoryboardDraftSeedV1
    | VideoDraftSeedV1
    | BgmDraftSeedV1,
    Field(discriminator="seed_kind"),
]


class DraftSeedEnvelopeV1(_DraftSeedModel):
    schema_version: Literal["1"] = "1"
    capability_id: DraftSeedCapabilityIdV1
    seed: DraftSeedV1
    accepted_commitments: tuple[AcceptedProposalCommitmentV1, ...] = Field(
        min_length=1,
        max_length=16,
    )

    @model_validator(mode="after")
    def validate_capability_match(self) -> "DraftSeedEnvelopeV1":
        if self.seed.seed_kind != self.capability_id:
            raise ValueError("Draft Seed capability does not match its envelope.")
        return self


class DraftSeedPersistenceRecordV1(_DraftSeedModel):
    option_id: str = Field(min_length=1, max_length=160)
    draft_seed_schema: Literal["draft_seed_v1"] = "draft_seed_v1"
    draft_seed_json: str = Field(min_length=2, max_length=65_536)
    draft_seed_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def canonical_draft_seed_json(envelope: DraftSeedEnvelopeV1) -> str:
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def draft_seed_persistence_record(
    option_id: str,
    envelope: DraftSeedEnvelopeV1,
) -> DraftSeedPersistenceRecordV1:
    payload = canonical_draft_seed_json(envelope)
    return DraftSeedPersistenceRecordV1(
        option_id=option_id,
        draft_seed_json=payload,
        draft_seed_digest=sha256(payload.encode("utf-8")).hexdigest(),
    )
