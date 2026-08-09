"""Pure deterministic rendering of private Proposal Draft Seeds."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_ad_media import VisualStyleContractV2
from app.schemas.agent_canvas_draft_seeds import (
    BgmDraftSeedV1,
    CharacterDraftSeedV1,
    DraftSeedCapabilityIdV1,
    DraftSeedEnvelopeV1,
    ProductDraftSeedV1,
    PropDraftSeedV1,
    SceneDraftSeedV1,
    ScriptDraftSeedV1,
    StoryboardDraftSeedV1,
    VideoDraftSeedV1,
    WorldSettingDraftSeedV1,
)
from app.schemas.agent_canvas_materialization import (
    BgmMaterializationResultV1,
    CapabilityMaterializationResultV1,
    CharacterMaterializationResultV1,
    ProductMaterializationResultV1,
    PropMaterializationResultV1,
    SceneMaterializationResultV1,
    ScriptMaterializationResultV1,
    StoryboardMaterializationResultV1,
    VideoMaterializationResultV1,
    WorldSettingMaterializationResultV1,
)


_CAPABILITY_IDENTITY: dict[
    DraftSeedCapabilityIdV1,
    tuple[Literal["text", "script", "image", "video", "audio"], str],
] = {
    "world_setting": ("text", "world_setting"),
    "product_design": ("image", "product"),
    "prop_design": ("image", "prop"),
    "character_design": ("image", "character"),
    "scene_design": ("image", "scene"),
    "script_authoring": ("script", "script"),
    "storyboard_design": ("image", "storyboard_sequence"),
    "video_direction": ("video", "storyboard_video"),
    "bgm_direction": ("audio", "bgm"),
}


class _RenderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftSeedRenderContextV1(_RenderModel):
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    style_prompt: str = Field(min_length=1, max_length=8_192)
    style_source: Literal["user", "video_skill", "references", "platform_default"]


class RenderedDraftSeedV1(_RenderModel):
    capability_id: DraftSeedCapabilityIdV1
    node_type: Literal["text", "script", "image", "video", "audio"]
    creative_role: str = Field(min_length=1, max_length=160)
    result: CapabilityMaterializationResultV1


class DraftSeedRendererRegistry:
    """Map one validated Seed to a complete editable Draft without I/O."""

    def render(
        self,
        envelope: DraftSeedEnvelopeV1,
        context: DraftSeedRenderContextV1,
    ) -> RenderedDraftSeedV1:
        return self.render_for_capability(envelope.capability_id, envelope, context)

    def render_for_capability(
        self,
        capability_id: DraftSeedCapabilityIdV1,
        envelope: DraftSeedEnvelopeV1,
        context: DraftSeedRenderContextV1,
    ) -> RenderedDraftSeedV1:
        if capability_id != envelope.capability_id or envelope.seed.seed_kind != capability_id:
            raise _error("Proposal Draft Seed capability is invalid.")
        identity = _CAPABILITY_IDENTITY.get(capability_id)
        if identity is None:
            raise _error("Proposal Draft Seed capability is unsupported.")
        result = _render_result(envelope, context)
        return RenderedDraftSeedV1(
            capability_id=capability_id,
            node_type=identity[0],
            creative_role=identity[1],
            result=result,
        )


def _render_result(
    envelope: DraftSeedEnvelopeV1,
    context: DraftSeedRenderContextV1,
) -> CapabilityMaterializationResultV1:
    seed = envelope.seed
    style = VisualStyleContractV2(
        style_prompt=context.style_prompt,
        source=context.style_source,
    )
    if isinstance(seed, WorldSettingDraftSeedV1):
        content = _join(
            seed.premise,
            f"Era and place: {seed.era_and_place}",
            "World rules:",
            *(f"- {item}" for item in seed.world_rules),
            "Visual continuity:",
            *(f"- {item}" for item in seed.visual_continuity),
            f"Creative direction: {seed.prompt_brief}",
        )
        return WorldSettingMaterializationResultV1(
            title="World Setting",
            summary_prompt=seed.premise,
            structured_content={
                "content": content,
                "core": {
                    "premise": seed.premise,
                    "era_and_place": seed.era_and_place,
                    "world_rules": seed.world_rules,
                    "visual_continuity": seed.visual_continuity,
                },
            },
        )
    if isinstance(seed, ProductDraftSeedV1):
        prompt = _design_prompt(
            kind="product",
            identity=seed.identity,
            purpose=seed.selling_focus,
            form=seed.form,
            materials=seed.materials,
            colors=seed.color_palette,
            presentation=seed.presentation_intent,
            exclusions=seed.exclusions,
            style_prompt=context.style_prompt,
        )
        return ProductMaterializationResultV1(
            title=_display_title(seed.identity),
            summary_prompt=_join(seed.identity, seed.selling_focus),
            generation_prompt=prompt,
            structured_content={
                "subject_identity": seed.identity,
                "design_summary": _join(
                    seed.selling_focus,
                    seed.form,
                    seed.presentation_intent,
                ),
                "style": style,
                "explicit_inclusions": (*seed.materials, *seed.color_palette),
                "negative_constraints": seed.exclusions,
            },
        )
    if isinstance(seed, PropDraftSeedV1):
        prompt = _design_prompt(
            kind="prop",
            identity=seed.identity,
            purpose=seed.function,
            form=seed.form,
            materials=seed.materials,
            colors=seed.color_palette,
            presentation=seed.presentation_intent,
            exclusions=seed.exclusions,
            style_prompt=context.style_prompt,
        )
        return PropMaterializationResultV1(
            title=_display_title(seed.identity),
            summary_prompt=_join(seed.identity, seed.function),
            generation_prompt=prompt,
            structured_content={
                "subject_identity": seed.identity,
                "design_summary": _join(seed.function, seed.form, seed.presentation_intent),
                "style": style,
                "explicit_inclusions": (*seed.materials, *seed.color_palette),
                "negative_constraints": seed.exclusions,
            },
        )
    if isinstance(seed, CharacterDraftSeedV1):
        summary = _join(
            seed.identity,
            seed.appearance,
            seed.wardrobe,
            seed.performance_role,
        )
        return CharacterMaterializationResultV1(
            title=_display_title(seed.identity),
            summary_prompt=summary,
            generation_prompt=_join(
                "Create one still full-body character identity design.",
                summary,
                f"Visual medium: {seed.visual_medium}",
                f"Presentation: {seed.presentation_intent}",
                f"Visual style: {context.style_prompt}",
                _negative_line(seed.exclusions),
            ),
            structured_content={
                "subject_identity": seed.identity,
                "design_summary": summary,
                "style": style,
                "explicit_inclusions": (
                    seed.appearance,
                    seed.wardrobe,
                    seed.performance_role,
                ),
                "negative_constraints": seed.exclusions,
            },
        )
    if isinstance(seed, SceneDraftSeedV1):
        summary = _join(seed.identity, seed.spatial_layout, seed.atmosphere)
        panels = tuple(
            {
                "panel_index": index,
                "view_or_zone": f"Spatial view {index}",
                "spatial_description": f"{seed.spatial_layout} View {index} preserves {seed.identity}.",
                "lighting_material_detail": f"{seed.lighting} Materials: {seed.materials}.",
            }
            for index in range(1, 10)
        )
        return SceneMaterializationResultV1(
            title=_display_title(seed.identity),
            summary_prompt=summary,
            generation_prompt=_join(
                "Create one static 3x3 scene design board with exactly nine distinct views.",
                summary,
                f"Lighting: {seed.lighting}",
                f"Materials: {seed.materials}",
                f"Time of day: {seed.time_of_day}",
                f"Visual style: {context.style_prompt}",
                _negative_line(seed.exclusions),
            ),
            structured_content={
                "scene_identity": seed.identity,
                "environment_summary": summary,
                "layout": seed.spatial_layout,
                "lighting": seed.lighting,
                "materials": seed.materials,
                "time_of_day": seed.time_of_day,
                "style": style,
                "panels": panels,
                "explicit_entity_reference_ids": (),
                "exclude_unreferenced_entities": True,
                "no_narrative_progression": True,
            },
        )
    if isinstance(seed, ScriptDraftSeedV1):
        content = _join(
            seed.premise,
            f"Audience objective: {seed.audience_objective}",
            f"Target duration: {seed.duration_seconds:g} seconds",
            "Narrative beats:",
            *(f"{index}. {beat}" for index, beat in enumerate(seed.narrative_beats, 1)),
            f"Dialogue direction: {seed.dialogue_direction}",
        )
        return ScriptMaterializationResultV1(
            title="Script Draft",
            summary_prompt=_join(seed.premise, seed.audience_objective),
            structured_content={"content": content},
        )
    if isinstance(seed, StoryboardDraftSeedV1):
        panels = tuple(panel.model_dump(mode="json") for panel in seed.panel_beats)
        return StoryboardMaterializationResultV1(
            title="Storyboard Sequence",
            summary_prompt=seed.sequence_summary,
            generation_prompt=_join(
                "Create one ordered 3x3 storyboard grid with exactly nine frames.",
                seed.sequence_summary,
                f"Camera language: {seed.camera_language}",
                *(
                    f"Frame {panel.panel_index}: {panel.beat}; {panel.composition}; {panel.camera}; {panel.subject_action}; {panel.continuity_from_previous}."
                    for panel in seed.panel_beats
                ),
                f"Continuity anchors: {', '.join(seed.continuity_anchors)}",
                _negative_line((*seed.exclusions, "generated text")),
            ),
            structured_content={
                "sequence_summary": seed.sequence_summary,
                "narrative_goal": seed.sequence_summary,
                "style": style,
                "panels": panels,
                "no_generated_text": True,
            },
        )
    if isinstance(seed, VideoDraftSeedV1):
        timing = tuple(
            f"{beat.start_seconds:g}-{beat.end_seconds:g}s: {beat.action}"
            for beat in seed.timing_beats
        )
        return VideoMaterializationResultV1(
            title="Video Segment",
            summary_prompt=seed.segment_summary,
            generation_prompt=_join(
                seed.segment_summary,
                f"Timing: {'; '.join(timing)}",
                f"Camera: {seed.camera_language}",
                f"Motion: {seed.motion}",
                f"Native audio: {seed.native_audio_direction}",
                f"Target style: {seed.target_style}",
                "Do not add background music during video generation.",
            ),
            structured_content={
                "segment_summary": seed.segment_summary,
                "duration_seconds": seed.duration_seconds,
                "storyboard_content": "; ".join(timing),
                "dialogue": "",
                "voice_style": "",
                "environment_sound": seed.native_audio_direction,
                "action_effects": seed.motion,
                "negative_constraints": "Do not add background music.",
                "background_music": False,
            },
        )
    if isinstance(seed, BgmDraftSeedV1):
        return BgmMaterializationResultV1(
            title="Background Music",
            summary_prompt=_join(seed.mood, seed.energy_curve),
            generation_prompt=_join(
                f"Mood: {seed.mood}",
                f"Instrumentation: {seed.instrumentation}",
                f"Pace: {seed.pace}",
                f"Energy curve: {seed.energy_curve}",
                f"Duration: {seed.duration_seconds:g} seconds",
                "Instrumental only. No vocals. No lyrics.",
            ),
            structured_content={
                "music_summary": _join(seed.mood, seed.energy_curve),
                "duration_seconds": seed.duration_seconds,
                "pace": seed.pace,
                "energy_curve": seed.energy_curve,
                "instrumentation": seed.instrumentation,
                "mood": seed.mood,
                "instrumental_only": True,
                "no_vocals": True,
            },
        )
    raise _error("Proposal Draft Seed capability is unsupported.")


def _display_title(value: str) -> str:
    title = " ".join(value.split())
    if len(title) <= 256:
        return title
    return f"{title[:253].rstrip()}..."


def _design_prompt(
    *,
    kind: str,
    identity: str,
    purpose: str,
    form: str,
    materials: tuple[str, ...],
    colors: tuple[str, ...],
    presentation: str,
    exclusions: tuple[str, ...],
    style_prompt: str,
) -> str:
    return _join(
        f"Create one still advertising {kind} design of {identity}",
        f"Purpose: {purpose}",
        f"Form: {form}",
        f"Materials: {', '.join(materials)}",
        f"Color palette: {', '.join(colors)}",
        f"Presentation: {presentation}",
        f"Visual style: {style_prompt}",
        _negative_line(exclusions),
    )


def _negative_line(exclusions: tuple[str, ...]) -> str:
    return f"Exclude: {', '.join(dict.fromkeys(exclusions))}" if exclusions else ""


def _join(*parts: str) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "proposal_draft_seed_invalid",
        message,
        stage="draft_seed_renderer",
    )
