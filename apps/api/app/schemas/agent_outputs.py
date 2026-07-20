from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RequirementsAnalysisOutput(BaseModel):
    core_selling_point: str
    target_audience: str
    campaign_goal: str
    desired_emotion: str
    duration_seconds: int = Field(ge=15, le=60)
    visual_style: str
    references: list[str] = Field(default_factory=list)


class ProductDesignOutput(BaseModel):
    showcase_focus: str
    presentation_strategy: str
    channels: list[str]


class CreativeDirectionOutput(BaseModel):
    concept: str
    key_message: str
    tone: str
    channels: list[str]


class ScriptBeat(BaseModel):
    order: int
    duration_seconds: int
    scene_intent: str
    location_hint: str
    visual_action: str
    product_action: str
    spoken_or_on_screen_text: str
    scene_id: str | None = None
    input_asset_ids: list[str] = Field(default_factory=list)


class ScriptOutput(BaseModel):
    hook: str
    body: str
    cta: str
    structure: list[str]
    script_structure: list[str] = Field(default_factory=list)
    subtitle_lines: list[str] = Field(default_factory=list)
    duration_seconds: int = Field(ge=15, le=60)
    shot_beats: list[ScriptBeat] = Field(default_factory=list)
    beats: list[ScriptBeat] = Field(default_factory=list)
    script_beats: list[ScriptBeat] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def copy_compatible_beat_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        beat_source = (
            payload.get("shot_beats") or payload.get("beats") or payload.get("script_beats")
        )
        if beat_source:
            payload.setdefault("shot_beats", beat_source)
            payload.setdefault("beats", beat_source)
            payload.setdefault("script_beats", beat_source)
        return payload

    @model_validator(mode="after")
    def fill_script_structure(self) -> "ScriptOutput":
        if not self.script_structure:
            self.script_structure = list(self.structure)
        if self.shot_beats:
            if not self.beats:
                self.beats = list(self.shot_beats)
            if not self.script_beats:
                self.script_beats = list(self.shot_beats)
        elif self.beats:
            self.shot_beats = list(self.beats)
            if not self.script_beats:
                self.script_beats = list(self.beats)
        elif self.script_beats:
            self.shot_beats = list(self.script_beats)
            self.beats = list(self.script_beats)
        return self


class CharacterSpec(BaseModel):
    name: str
    role: str
    appearance: str
    personality: str


class CharacterDesignOutput(BaseModel):
    characters: list[CharacterSpec]


class SceneSpec(BaseModel):
    scene_id: str | None = None
    order: int | None = None
    location: str
    lighting: str
    atmosphere: str
    spatial_layout: str | None = None
    visual_action: str | None = None


class SceneDesignOutput(BaseModel):
    scenes: list[SceneSpec]


class StoryboardScene(BaseModel):
    order: int
    scene_id: str | None = None
    shot: str
    visual: str
    text: str
    dialogue: str | None = None
    duration_seconds: float | None = None
    camera: str | None = None
    action: str | None = None
    input_asset_ids: list[str] = Field(default_factory=list)


class StoryboardShot(BaseModel):
    shot_id: str | None = None
    order: int
    shot_type: str | None = None
    prompt: str | None = None
    primary_scene_id: str | None = None
    scene_reference_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    product_reference_ids: list[str] = Field(default_factory=list)
    style_reference_ids: list[str] = Field(default_factory=list)
    no_scene_reason: str | None = None
    input_asset_ids: list[str] = Field(default_factory=list)
    visual: str | None = None
    text: str | None = None
    duration_seconds: float | None = None
    camera: str | None = None
    action: str | None = None


class StoryboardOutput(BaseModel):
    scenes: list[StoryboardScene] = Field(default_factory=list)
    shots: list[StoryboardShot] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_compatible_storyboard_aliases(self) -> "StoryboardOutput":
        if not self.shots and self.scenes:
            self.shots = [
                StoryboardShot(
                    shot_id=f"shot_{scene.order:03d}",
                    order=scene.order,
                    prompt=scene.visual,
                    primary_scene_id=scene.scene_id,
                    scene_reference_ids=[scene.scene_id] if scene.scene_id else [],
                    input_asset_ids=list(scene.input_asset_ids),
                    visual=scene.visual,
                    text=scene.text,
                    duration_seconds=scene.duration_seconds,
                    camera=scene.camera,
                    action=scene.action,
                )
                for scene in self.scenes
            ]
        return self


class SubtitleCue(BaseModel):
    cue_id: str
    scene: int = Field(ge=1)
    order: int = Field(ge=1)
    start_time: str
    end_time: str
    text: str
    cue_type: Literal["dialogue", "narrator", "on_screen_text", "cta"]
    speaker_hint: str | None = None


class SubtitleGenerationOutput(BaseModel):
    asset_id: str
    local_path: str
    format: Literal["srt"] = "srt"
    source: dict[str, Any]
    cues: list[SubtitleCue]
    srt_path: str
    status: str = "ready"


class SoundEffectTrack(BaseModel):
    scene: int = Field(ge=1)
    order: int = Field(ge=1)
    start_time: str
    end_time: str
    sound_type: Literal[
        "environment",
        "action",
        "object",
        "transition",
        "product_interaction",
    ]
    description: str
    intensity: Literal["low", "medium", "high"]
    generation_prompt: str
    sync_notes: str


class SoundEffectsOutput(BaseModel):
    sound_effect_tracks: list[SoundEffectTrack]
    sync_notes: str


class VoiceTrack(BaseModel):
    cue_id: str
    scene: int = Field(ge=1)
    order: int = Field(ge=1)
    start_time: str
    end_time: str
    text: str
    voice_type: Literal["character", "narrator", "no_voice"]
    character_name: str | None = None
    voice_profile: str
    emotion: str
    speed: str
    volume: str
    generation_prompt: str
    sync_notes: str


class VoiceoverOutput(BaseModel):
    has_voiceover: bool
    voice_tracks: list[VoiceTrack]
    sync_notes: str


class BgmOutput(BaseModel):
    music_style: str
    mood: str
    tempo: str
    instruments: list[str]
    structure: list[str]
    start_time: str
    end_time: str
    fade_in: str
    fade_out: str
    generation_prompt: str
    sync_notes: str


class PromptOptimizationOutput(BaseModel):
    optimized_generation_prompt: str
    provider_prompt: str
    negative_prompt: str | None = None
    asset_references: list[str] = Field(default_factory=list)
    quality_notes: str | None = None


class FinalVideoInputAsset(BaseModel):
    asset_id: str
    asset_type: str
    local_path: str | None = None
    url: str | None = None
    remote_url: str | None = None
    mime_type: str | None = None
    role: str | None = None
    source: str
    source_node: str | None = None
    source_type: str | None = None
    source_node_id: str | None = None
    entity_id: str | None = None
    entity_type: str | None = None
    semantic_type: str | None = None
    display_name: str | None = None
    is_primary: bool | None = None
    reference_mode: str | None = None
    use_as_prompt: bool | None = None
    lock_identity: bool | None = None
    allow_style_transfer: bool | None = None
    download_status: str | None = None
    model_input_type: str | None = None
    model_input_value: str | None = None
    conversion_status: str | None = None
    conversion_warning: str | None = None
    conversion_error: str | None = None


class FinalVideoScenePrompt(BaseModel):
    order: int = Field(ge=1)
    scene_id: str | None = None
    prompt: str
    duration_seconds: float
    input_asset_ids: list[str] = Field(default_factory=list)


class FinalVideoGenerationOutput(BaseModel):
    final_video_prompt: str
    negative_prompt: str
    input_assets: list[FinalVideoInputAsset]
    scene_prompts: list[FinalVideoScenePrompt]
    duration_seconds: int = Field(ge=15, le=60)
    aspect_ratio: str
    output_resolution: str = "480p"
    style: str
    camera_motion: str
    continuity_notes: str
    audio_strategy: str
    generation_provider_hint: str
    status: Literal["ready", "submitted", "failed"] = "ready"
