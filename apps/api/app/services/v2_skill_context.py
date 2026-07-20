from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.skills.loader import SkillLoadError, load_skill


SCRIPT_WRITER_SKILLS = (
    "short_ad_script_structure",
    "storyboard_beat_extraction",
    "dialogue_copy_generation",
)

SPECIALIST_SKILLS: dict[tuple[str, str], tuple[str, ...]] = {
    ("product_designer", "product_main_image"): (
        "product_info_extraction",
        "selling_point_extraction",
        "reference_asset_selection",
    ),
    ("product_designer", "product_multi_view_grid"): (
        "product_info_extraction",
        "selling_point_extraction",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("character_designer", "character_main_image"): (
        "character_spec_extraction",
        "character_prompt_expansion",
        "reference_asset_selection",
    ),
    ("character_designer", "character_three_view"): (
        "character_spec_extraction",
        "character_prompt_expansion",
        "character_turnaround_prompt",
        "visual_continuity_check",
    ),
    ("scene_designer", "scene_main_image"): (
        "scene_spec_extraction",
        "pure_scene_prompt_expansion",
        "reference_asset_selection",
    ),
    ("scene_designer", "scene_multi_view_grid"): (
        "scene_spec_extraction",
        "pure_scene_prompt_expansion",
        "multi_view_scene_prompt",
        "visual_continuity_check",
    ),
    ("storyboard_artist", "shot_cell_1"): (
        "storyboard_beat_extraction",
        "storyboard_image_prompt_generation",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("storyboard_artist", "shot_cell_2"): (
        "storyboard_beat_extraction",
        "storyboard_image_prompt_generation",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("storyboard_artist", "shot_cell_3"): (
        "storyboard_beat_extraction",
        "storyboard_image_prompt_generation",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("storyboard_artist", "shot_cell_4"): (
        "storyboard_beat_extraction",
        "storyboard_image_prompt_generation",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("video_director", "shot_video_segment"): (
        "storyboard_video_prompt_generation",
        "dialogue_copy_generation",
        "reference_asset_selection",
        "visual_continuity_check",
    ),
    ("sound_director", "bgm_audio"): (
        "bgm_prompt_generation",
        "mood_and_duration_matching",
    ),
    ("composition_tool", "final_video"): ("ffmpeg_composition_planning",),
}


class V2SkillContext(BaseModel):
    skill_ids: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class V2SkillContextService:
    def skill_context_for_script_writer(self) -> V2SkillContext:
        return self._load_context(SCRIPT_WRITER_SKILLS)

    def skill_context_for_specialist(
        self,
        *,
        specialist: str,
        slot_type: str,
        media_type: str,
    ) -> V2SkillContext:
        del media_type
        skill_ids = SPECIALIST_SKILLS.get((specialist, slot_type), ())
        return self._load_context(skill_ids)

    def skill_context_for_storyboard_detail(self) -> V2SkillContext:
        return self._load_context(
            (
                "storyboard_video_prompt_generation",
                "dialogue_copy_generation",
                "visual_continuity_check",
            )
        )

    def _load_context(self, skill_ids: tuple[str, ...]) -> V2SkillContext:
        names: list[str] = []
        instructions: list[str] = []
        source_paths: list[str] = []
        warnings: list[dict[str, Any]] = []
        loaded_ids: list[str] = []
        for skill_id in skill_ids:
            try:
                skill = load_skill(skill_id)
            except SkillLoadError as exc:
                warnings.append(
                    {
                        "code": "v2_skill_pack_missing",
                        "skill_id": skill_id,
                        "message": str(exc),
                    }
                )
                continue
            loaded_ids.append(skill.skill_id)
            names.append(skill.name)
            source_paths.append(skill.source_path.as_posix())
            instructions.append(str(sanitize_context_for_llm_text(skill.markdown)))
        return V2SkillContext(
            skill_ids=loaded_ids,
            skill_names=names,
            instructions=instructions,
            source_paths=source_paths,
            warnings=warnings,
        )
