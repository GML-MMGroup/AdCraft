from dataclasses import dataclass, field

from app.core.config import Settings
from app.services.v2_specialist_ownership import ownership_scope_for


@dataclass(frozen=True)
class V2SpecialistConfig:
    specialist: str
    display_name: str
    system_prompt: str
    allowed_slot_types: frozenset[str]
    model_id: str | None = None
    profile_id: str = ""
    profile_version: str = "v2"
    model_env_key: str | None = None
    allowed_node_types: frozenset[str] = frozenset()
    allowed_item_types: frozenset[str] = frozenset()
    allowed_actions: frozenset[str] = frozenset()
    skill_pack_ids: tuple[str, ...] = field(default_factory=tuple)
    output_contracts: tuple[str, ...] = field(default_factory=tuple)
    quality_gate_id: str = "v2_prompt_contract_quality"
    is_llm_specialist: bool = True

    def supports_target(self, slot_type: str, media_type: str | None = None) -> bool:
        if slot_type != "free_output":
            return slot_type in self.allowed_slot_types
        if self.specialist == "quick_image_generator":
            return media_type == "image"
        if self.specialist == "quick_video_generator":
            return media_type == "video"
        if self.specialist == "quick_audio_generator":
            return media_type == "audio"
        return False


REQUIRED_OUTPUT_KEYS = (
    "summary_prompt",
    "specialist_prompt",
    "detail_prompts",
    "provider_prompt",
    "negative_prompt",
    "negative_constraints",
    "reference_asset_ids",
    "warnings",
)


def specialist_config_for(
    specialist: str,
    settings: Settings,
) -> V2SpecialistConfig | None:
    model_env_key, model_id = _specialist_model(specialist, settings)
    config = _SPECIALIST_CONFIGS.get(specialist)
    scope = ownership_scope_for(specialist)
    if config is None:
        return None
    if scope is None:
        return None
    return V2SpecialistConfig(
        profile_id=config.profile_id or config.specialist,
        specialist=config.specialist,
        profile_version=config.profile_version,
        display_name=config.display_name,
        system_prompt=config.system_prompt,
        model_id=model_id,
        model_env_key=model_env_key,
        allowed_node_types=frozenset(scope.node_types),
        allowed_item_types=frozenset(scope.item_types),
        allowed_slot_types=frozenset(scope.slot_types),
        allowed_actions=frozenset(scope.actions),
        skill_pack_ids=config.skill_pack_ids,
        output_contracts=config.output_contracts
        or tuple(_contract_name(slot) for slot in scope.slot_types),
        quality_gate_id=config.quality_gate_id,
        is_llm_specialist=scope.is_llm_specialist,
    )


def _contract_name(slot_type: str) -> str:
    return {
        "product_main_image": "V2ProductMainPromptPlan",
        "product_multi_view_grid": "V2ProductMultiViewPromptPlan",
        "character_main_image": "V2CharacterMainPromptPlan",
        "character_three_view": "V2CharacterThreeViewPromptPlan",
        "scene_main_image": "V2SceneMainPromptPlan",
        "scene_multi_view_grid": "V2SceneMultiViewPromptPlan",
        "shot_cell_1": "V2ShotCellPromptPlan",
        "shot_cell_2": "V2ShotCellPromptPlan",
        "shot_cell_3": "V2ShotCellPromptPlan",
        "shot_cell_4": "V2ShotCellPromptPlan",
        "shot_video_segment": "V2ShotVideoPromptPlan",
        "bgm_audio": "V2BgmPromptPlan",
        "final_video": "V2FinalCompositionPlan",
        "free_output": "V2FreePromptPlan",
    }.get(slot_type, "V2GenericProviderPayload")


def _specialist_model(specialist: str, settings: Settings) -> tuple[str | None, str | None]:
    env_key = specialist_model_env_key_for(specialist)
    if specialist == "product_designer":
        return env_key, settings.llm_product_design_model or None
    if specialist == "character_designer":
        return env_key, settings.llm_character_model or None
    if specialist == "scene_designer":
        return env_key, settings.llm_scene_model or None
    if specialist == "storyboard_artist":
        return env_key, settings.llm_storyboard_model or None
    if specialist == "video_director":
        return env_key, settings.llm_final_video_model or None
    if specialist == "sound_director":
        if settings.llm_bgm_model:
            return "LLM_BGM_MODEL", settings.llm_bgm_model
        return "LLM_SOUND_MODEL", settings.llm_sound_effects_model or None
    if specialist == "quick_image_generator":
        return env_key, settings.llm_creative_model or None
    if specialist == "quick_video_generator":
        return env_key, settings.llm_final_video_model or None
    if specialist == "quick_audio_generator":
        if settings.llm_bgm_model:
            return "LLM_BGM_MODEL", settings.llm_bgm_model
        return "LLM_SOUND_MODEL", settings.llm_sound_effects_model or None
    return None, None


def specialist_model_env_key_for(specialist: str) -> str | None:
    return {
        "front_desk": "LLM_FRONT_DESK_MODEL",
        "script_writer": "LLM_SCRIPT_MODEL",
        "product_designer": "LLM_PRODUCT_DESIGN_MODEL",
        "character_designer": "LLM_CHARACTER_MODEL",
        "scene_designer": "LLM_SCENE_MODEL",
        "storyboard_artist": "LLM_STORYBOARD_MODEL",
        "video_director": "LLM_FINAL_VIDEO_MODEL",
        "sound_director": "LLM_BGM_MODEL",
        "quick_image_generator": "LLM_CREATIVE_MODEL",
        "quick_video_generator": "LLM_FINAL_VIDEO_MODEL",
        "quick_audio_generator": "LLM_BGM_MODEL",
    }.get(specialist)


def required_json_contract_prompt() -> str:
    keys = "\n".join(f"- {key}" for key in REQUIRED_OUTPUT_KEYS)
    return (
        "Return one JSON object only. Do not return markdown. Do not wrap JSON in "
        "code fences. The JSON object must include these keys:\n"
        f"{keys}\n"
        "Do not invent asset ids. Preserve provided reference asset ids unless a "
        "controlled warning explains why an id is omitted. Generate exactly one "
        "provider_prompt for the target slot. Do not ask follow-up questions."
    )


def _system_prompt(role: str, rules: str) -> str:
    return f"{role}\n\n{required_json_contract_prompt()}\n\n{rules}"


_SPECIALIST_CONFIGS: dict[str, V2SpecialistConfig] = {
    "product_designer": V2SpecialistConfig(
        specialist="product_designer",
        display_name="Product Designer",
        model_id="",
        allowed_slot_types=frozenset({"product_main_image", "product_multi_view_grid"}),
        skill_pack_ids=("product_info_extraction", "selling_point_extraction"),
        system_prompt=_system_prompt(
            "You are the Product Designer for an advertising generation workflow.",
            "Refine product prompts while preserving product identity, packaging, label, "
            "logo, shape, color, and brand-readable details. Use strict reference mode "
            "when product reference assets are provided. For product_multi_view_grid, "
            "create one multi-view product prompt using the selected product main image.",
        ),
    ),
    "character_designer": V2SpecialistConfig(
        specialist="character_designer",
        display_name="Character Designer",
        model_id="",
        allowed_slot_types=frozenset({"character_main_image", "character_three_view"}),
        skill_pack_ids=(
            "character_spec_extraction",
            "character_prompt_expansion",
            "character_turnaround_prompt",
        ),
        system_prompt=_system_prompt(
            "You are the Character Designer for an advertising generation workflow.",
            "Preserve wardrobe, silhouette, age, expression, identity, and style. For "
            "character_three_view, create one three-view prompt using the selected "
            "character main image. Do not create Face ID or avatar requirements.",
        ),
    ),
    "scene_designer": V2SpecialistConfig(
        specialist="scene_designer",
        display_name="Scene Designer",
        model_id="",
        allowed_slot_types=frozenset({"scene_main_image", "scene_multi_view_grid"}),
        skill_pack_ids=(
            "scene_spec_extraction",
            "pure_scene_prompt_expansion",
            "multi_view_scene_prompt",
        ),
        system_prompt=_system_prompt(
            "You are the Scene Designer for an advertising generation workflow.",
            "Refine scene prompts around spatial layout, lighting, props, camera "
            "readability, and visual style. For scene_multi_view_grid, create one "
            "four-view scene prompt. Do not confuse scene grids with storyboard cells.",
        ),
    ),
    "storyboard_artist": V2SpecialistConfig(
        specialist="storyboard_artist",
        display_name="Storyboard Artist",
        model_id="",
        allowed_slot_types=frozenset({"shot_cell_1", "shot_cell_2", "shot_cell_3", "shot_cell_4"}),
        skill_pack_ids=(
            "storyboard_beat_extraction",
            "storyboard_image_prompt_generation",
            "visual_continuity_check",
        ),
        system_prompt=_system_prompt(
            "You are the Storyboard Artist for an advertising generation workflow.",
            "Produce one complete prompt for one single image. Preserve same-shot "
            "continuity using the shared context and logical cell role. Do not include "
            "sibling cell full prompts. Do not request grids, collages, split images, "
            "multi-frame images, or combined cell descriptions.",
        ),
    ),
    "video_director": V2SpecialistConfig(
        specialist="video_director",
        display_name="Video Director",
        model_id="",
        allowed_slot_types=frozenset({"shot_video_segment"}),
        skill_pack_ids=("storyboard_video_prompt_generation",),
        system_prompt=_system_prompt(
            "You are the Video Director for storyboard video segments.",
            "Produce one video prompt for one shot video segment. Use selected same-shot "
            "cell assets as references. Include motion, timing, camera movement, "
            "transition, dialogue, audio description, voice style, and negative "
            "constraints when provided. Do not produce a full-ad video prompt.",
        ),
    ),
    "sound_director": V2SpecialistConfig(
        specialist="sound_director",
        display_name="Sound Director",
        model_id="",
        allowed_slot_types=frozenset({"bgm_audio"}),
        skill_pack_ids=("bgm_prompt_generation", "mood_and_duration_matching"),
        system_prompt=_system_prompt(
            "You are the Sound Director for background music generation.",
            "Produce one music generation prompt. Respect workflow duration, ad tone, "
            "brand emotion, and audio mode. Do not add sound effects or voiceover "
            "requirements unless the slot schema provides them.",
        ),
    ),
    "composition_tool": V2SpecialistConfig(
        specialist="composition_tool",
        display_name="Composition Tool",
        model_id="",
        allowed_slot_types=frozenset({"final_video"}),
        system_prompt=_system_prompt(
            "You are a deterministic final composition tool planner.",
            "Return composition metadata only. Do not create a media provider prompt "
            "for text-to-video generation. The backend timeline and local composition "
            "tool assemble the final ad.",
        ),
    ),
    "quick_image_generator": V2SpecialistConfig(
        specialist="quick_image_generator",
        display_name="Quick Image Generator",
        model_id="",
        allowed_slot_types=frozenset({"free_output"}),
        system_prompt=_system_prompt(
            "You lightly clean prompts for standalone free image generation.",
            "Do not infer product, character, or scene ownership from media type alone.",
        ),
    ),
    "quick_video_generator": V2SpecialistConfig(
        specialist="quick_video_generator",
        display_name="Quick Video Generator",
        model_id="",
        allowed_slot_types=frozenset({"free_output"}),
        system_prompt=_system_prompt(
            "You lightly clean prompts for standalone free video generation.",
            "Do not infer product, character, or scene ownership from media type alone.",
        ),
    ),
    "quick_audio_generator": V2SpecialistConfig(
        specialist="quick_audio_generator",
        display_name="Quick Audio Generator",
        model_id="",
        allowed_slot_types=frozenset({"free_output"}),
        system_prompt=_system_prompt(
            "You lightly clean prompts for standalone free audio generation.",
            "Do not infer product, character, or scene ownership from media type alone.",
        ),
    ),
}
