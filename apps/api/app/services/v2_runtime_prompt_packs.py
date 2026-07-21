from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from app.schemas.workflow_v2_prompt_registry import (
    V2PromptContentProfile,
    V2PromptContentProfileMetadata,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_prompt_registry import PROVIDER_SLOT_PROMPT_IDS


@dataclass(frozen=True)
class V2PromptPackTemplate:
    prompt_id: str
    required_context_keys: tuple[str, ...]
    render: Callable[[dict[str, Any]], str]


class V2PromptContentProfileService:
    def __init__(self) -> None:
        self._profiles = _build_profiles()

    def get_profile(self, prompt_id: str) -> V2PromptContentProfile:
        return self._profiles[prompt_id]

    def maybe_profile(self, prompt_id: str) -> V2PromptContentProfile | None:
        return self._profiles.get(prompt_id)

    def metadata_for_render(
        self,
        *,
        prompt_id: str,
        prompt_text: str,
    ) -> V2PromptContentProfileMetadata | None:
        profile = self.maybe_profile(prompt_id)
        if profile is None:
            return None
        word_count = _word_count(prompt_text)
        return V2PromptContentProfileMetadata(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            prompt_id=profile.prompt_id,
            stage=profile.stage,
            sections=list(profile.required_sections),
            word_count=word_count,
            budget_status=_budget_status(
                word_count,
                min_words=profile.target_min_words,
                max_words=profile.target_max_words,
            ),
        )


def prompt_pack_for(prompt_id: str) -> V2PromptPackTemplate | None:
    return PROMPT_PACKS.get(prompt_id)


def prompt_content_profile_for(prompt_id: str) -> V2PromptContentProfile | None:
    return V2PromptContentProfileService().maybe_profile(prompt_id)


def prompt_content_profile_metadata(
    *,
    prompt_id: str,
    prompt_text: str,
) -> dict[str, Any] | None:
    metadata = V2PromptContentProfileService().metadata_for_render(
        prompt_id=prompt_id,
        prompt_text=prompt_text,
    )
    return metadata.model_dump(mode="json") if metadata is not None else None


def render_provider_contract_prompt(context: dict[str, Any], *, prompt_id: str) -> str:
    sections = _clean_sections(context.get("sections"))
    slot_type = _slot_type_for_provider_prompt(prompt_id)
    media_profile = _provider_media_profile(slot_type)
    sections = _compact_provider_sections(
        sections, slot_type=slot_type, media_profile=media_profile
    )
    boundary_sections = _provider_boundary_sections(slot_type, media_profile)
    return _join_sections([*sections, *boundary_sections])


def render_script_writer_system_prompt(context: dict[str, Any]) -> str:
    required_fields = _csv(context.get("required_top_level_fields"))
    canonical_fields = _csv(context.get("canonical_id_fields"))
    forbidden_aliases = _csv(context.get("forbidden_alias_only_fields"))
    return _join_sections(
        [
            "Role\nYou are the V2 Script Writer for an advertising production team.",
            (
                "Mission\nTransform the user's ad request, normalized planning context, skill context, "
                "and lightweight input asset descriptors into a complete commercial script plan. "
                "Write the creative structure that downstream product, character, scene, storyboard, "
                "audio, and composition specialists can use."
            ),
            (
                "Input Contract\nRead the sanitized request, product name, duration, aspect ratio, audio mode, "
                "front-desk normalized request, planning constraints, and summarized asset descriptors. "
                "System instructions are English. User-visible script copy may use the user's language."
            ),
            (
                "Output Contract\nReturn exactly one JSON object matching V2ScriptPlan. Required top-level "
                f"fields include: {required_fields}. Canonical nested id fields include: {canonical_fields}. "
                f"Do not use alias-only id fields: {forbidden_aliases}. Do not return markdown or code fences."
            ),
            (
                "Commercial Story Requirements\nCreate a real ad script with a title, script text, concrete scenes, "
                "shots, characters, locations, product beats, tone, visual style, duration seconds, aspect ratio, "
                "and dialogue or narration when useful."
            ),
            (
                "Scene And Shot Planning Rules\nBuild a clear progression from opening hook to product proof, "
                "emotional payoff, and brand-readable ending. Every shot needs a shot id, scene id, shot index, "
                "duration, description, and visual prompt."
            ),
            (
                "Product Integration Rules\nShow product benefits through commercial action and visual evidence. "
                "Do not let product references disappear into generic lifestyle text."
            ),
            (
                "Character And Location Rules\nDefine reusable character identities and reusable location identities. "
                "Characters and locations must be concrete enough for later media specialists."
            ),
            (
                "Dialogue/Narration Rules\nUse dialogue or narration only when it improves the ad. Keep copy concise, "
                "brand-safe, and compatible with the requested language."
            ),
            (
                "Forbidden Behavior\nDo not copy, wrap, or lightly rephrase the raw user prompt as the script. "
                "Do not add only a title before the user prompt. Do not return partial JSON. Do not serialize media "
                "bytes, base64, data URLs, local file contents, or secrets."
            ),
            (
                "Quality Rubric\nA strong answer has concrete scene and shot progression, clear product beats, "
                "distinct characters and locations, usable downstream visual prompts, duration math that fits the "
                "requested length, and no anonymous placeholder wording."
            ),
            (
                "Example\nFor a phone night-photography ad, create three shots: a neon street hook, a stabilized "
                "video proof beat, and a premium everyday payoff. Include product beats, character roles, location "
                "identity, tone, visual style, and concise narration."
            ),
            (
                "Anti-example\nInvalid: a JSON object whose script_text is only 'Create a 30-second phone ad for young "
                "people' with no scenes, no shots, no characters, and no product beat progression."
            ),
        ]
    )


def render_expert_brief_system_prompt(context: dict[str, Any]) -> str:
    constraints = context.get("inventory_constraints")
    constraints = constraints if isinstance(constraints, Mapping) else {}
    product_count = _count_phrase(constraints.get("product_count"), "product")
    character_count = _count_phrase(constraints.get("character_count"), "character")
    scene_count = _count_phrase(constraints.get("scene_count"), "scene")
    shot_count = _count_phrase(constraints.get("shot_count"), "shot")
    duration = constraints.get("duration_seconds") or "requested"
    aspect_ratio = constraints.get("aspect_ratio") or "requested"
    return _join_sections(
        [
            "Role\nYou are the V2 Expert Brief Planner for an advertising production team.",
            (
                "Mission\nTurn the validated V2ScriptPlan into separate handoffs for Product Designer, Character "
                "Designer, Scene Designer, and Sound Director/BGM. Keep each expert brief useful for its owner."
            ),
            (
                "Source Inputs\nUse the script plan, request, normalized front-desk context, planning constraints, "
                "and lightweight input assets. Do not generate media or provider tasks."
            ),
            (
                "Inventory Constraints\nPreserve the requested inventory: "
                f"{product_count}, {character_count}, {scene_count}, {shot_count}, {duration} seconds, "
                f"aspect ratio {aspect_ratio}. Preserve product identity, requested scene styles, BGM direction, "
                "duration, shot count, character inventory, and scene inventory."
            ),
            (
                "Product Brief Rules\nProduct briefs describe product identity, recognizable silhouette, brand or "
                "packaging cues, hero selling points, material finish, and product-only slot prompts."
            ),
            (
                "Character Brief Rules\nCharacter briefs describe identity, age impression, wardrobe, silhouette, "
                "facial features, posture, emotion arc, and character-only reference slots. They must not include "
                "product usage or scene action."
            ),
            (
                "Scene Brief Rules\nScene briefs describe location identity, spatial layout, lighting, materials, "
                "time of day, atmosphere, and environment-only slot prompts. They must not include foreground "
                "characters, product manipulation, dialogue, or narrative activity."
            ),
            (
                "BGM Brief Rules\nBGM briefs describe instrumental mood, pace, energy curve, duration, commercial "
                "fit, and no vocals or lyrics unless the request explicitly asks for vocals or lyrics."
            ),
            (
                "Slot Prompt Rules\nPopulate asset_prompts and slot_prompts with slot-scoped prompts. Product, "
                "character, scene, storyboard, video, BGM, and final composition prompts must not copy sibling prompts."
            ),
            (
                "Forbidden Behavior\nProduct, character, scene, and BGM briefs must not be identical or generic copies. "
                "Do not paste one generic campaign summary into every expert brief. Do not serialize media bytes, "
                "base64, data URLs, local file contents, or secrets."
            ),
            (
                "Quality Rubric\nA strong plan preserves inventory counts, assigns source scene and shot ids, keeps "
                "asset prompts slot-specific, and gives every expert enough detail to produce reusable assets."
            ),
            (
                "Example\nProduct brief focuses on the phone body and camera module. Character brief focuses on one "
                "young creator. Scene brief focuses on a neon night street. BGM brief focuses on instrumental tempo."
            ),
            (
                "Anti-example\nInvalid: product, character, scene, and BGM all say only 'premium youthful commercial "
                "with cinematic energy' with no owned scope or slot-specific guidance."
            ),
        ]
    )


def render_specialist_materializer_prompt(context: dict[str, Any]) -> str:
    specialist = str(context.get("specialist") or "current specialist").replace("_", " ")
    slot_type = str(context.get("slot_type") or "current slot")
    return _join_sections(
        [
            f"Specialist Role\nYou are the {specialist} for the V2 advertising workflow.",
            (
                "Owned Scope\nWrite only for the current target slot. Do not copy sibling slot prompts. "
                "Do not write prompts for other specialists."
            ),
            "Allowed Context\nUse the sanitized request, route, item summary, slot summary, selected references, and skill context.",
            f"Slot Boundary\nCurrent slot type: {slot_type}. Respect the slot contract and media type.",
            "Reference Rules\nPreserve allowed reference asset ids. Do not invent asset ids.",
            "Prompt Writing Rules\nReturn exactly one provider prompt for this slot plus safe negative constraints.",
            "Forbidden Behavior\nNo base64, data URLs, media bytes, secrets, full workflow dumps, or sibling full prompts.",
            "Quality Checklist\nThe prompt is slot-specific, concise, reference-aware, and owned by the current specialist.",
        ]
    )


def render_storyboard_detail_system_prompt(_context: dict[str, Any]) -> str:
    return _join_sections(
        [
            "Role\nYou are the V2 Storyboard Detail Materializer for an advertising production team.",
            (
                "Mission\nTurn one editable shot summary plus script, product, character, scene, and reference context "
                "into exactly four distinct same-shot cell prompts and one timeline-based video detail prompt."
            ),
            "Input Summary\nUse the shot summary as context, but the shot summary itself is not the provider prompt.",
            (
                "Shot Cell Progression Rules\nCreate four cell prompts by default: establishing, action, detail, "
                "and payoff. Each cell is one standalone full-frame keyframe, not a collage or storyboard sheet."
            ),
            (
                "Same-shot Continuity Rules\nEvery cell preserves selected product, character, scene, lighting, time of "
                "day, camera logic, and same-shot continuity while advancing the action."
            ),
            (
                "Video Timeline Rules\nCreate one shot video detail with time segments, motion, camera movement, duration, "
                "aspect ratio, continuity sources, and a timeline that follows the selected cell images."
            ),
            "Dialogue Rules\nInclude dialogue constraints when dialogue or narration is present; otherwise state no spoken dialogue.",
            (
                "Audio Description Rules\nDescribe production sound only: diegetic movement, "
                "product interaction, room tone, and tactile action cues. Leave whole-ad audio beds "
                "to the dedicated audio slot."
            ),
            (
                "Negative Video Constraints\nProduction-audio cues only, subtitles only when requested, no watermarks, "
                "no static slideshow motion, no distorted product labels, and no identity drift."
            ),
            "Forbidden Behavior\nDo not generate media, submit provider tasks, return markdown, or serialize media bytes.",
            (
                "Example\nCell 1 establishes the environment and product. Cell 2 advances the action. Cell 3 focuses on the "
                "product or character detail. Cell 4 resolves the emotion and transition. The video detail uses a matching "
                "0-5s or 0-10s timeline."
            ),
            "Anti-example\nInvalid: four identical cell prompts or a video prompt that simply repeats the shot summary.",
        ]
    )


def render_visual_style_scope_repair_prompt(context: dict[str, Any]) -> str:
    product_name = str(context.get("product_name") or "the canonical product").strip()
    return _join_sections(
        [
            "Role\nYou normalize a V2 workflow visual style contract.",
            (
                "Mission\nSeparate reusable rendering direction from product identity constraints. "
                "The rendering style is injected into every visual slot, while product constraints "
                "belong only to the existing product identity path."
            ),
            (
                f"Canonical Product\nThe product identity is {product_name}. Do not include this "
                "product, its recognizability requirements, packaging cues, or selling points in "
                "rendering_style."
            ),
            (
                "Output Contract\nReturn exactly one JSON object matching "
                "V2VisualStyleScopeRepairOutput. rendering_style must contain only reusable visual "
                "direction. product_identity_constraints must contain bounded product-specific "
                "requirements."
            ),
            (
                "Forbidden Behavior\nDo not return markdown, raw user-request wrappers, provider "
                "prompts, credentials, media bytes, or base64 data."
            ),
        ]
    )


def render_structured_repair_prompt(context: dict[str, Any]) -> str:
    contract_name = str(context.get("contract_name") or "the registered output contract").strip()
    contract_rules: list[str] = []
    if contract_name == "V2IntentPlan":
        contract_rules.append(
            "V2IntentPlan Scene Contract\nRead original_request.explicit_constraints.scene_count. "
            "When it is present, return exactly that many scenes. Map every natural-language scene "
            "description to a concise English snake_case scene kind matching "
            "^[a-z][a-z0-9_]{0,63}$. Keep setting_type and time_of_day as separate technical facets."
        )
    return _join_sections(
        [
            "Role\nYou repair structured V2 generation output.",
            (
                f"Mission\nRepair the previous output so it validates against {contract_name}, preserves the original "
                "advertising intent, and satisfies the stage quality rules."
            ),
            "Repair Rules\nReturn one complete JSON object only. Do not explain. Do not include markdown or partial patches.",
            *contract_rules,
            "Forbidden Behavior\nDo not serialize media bytes, base64, data URLs, local file contents, secrets, or full workflow dumps.",
        ]
    )


def render_deterministic_fallback_prompt(context: dict[str, Any]) -> str:
    stage_name = str(context.get("stage_name") or "structured generation").strip()
    return _join_sections(
        [
            "Role\nYou describe deterministic V2 fallback behavior for traceability.",
            (
                f"Mission\nUse the deterministic V2 fallback builder for {stage_name}; keep output schema-safe, "
                "sanitized, and free of provider-visible legacy prompts."
            ),
            "Fallback Rules\nPreserve product, character, scene, shot, duration, aspect ratio, and reference constraints when present.",
        ]
    )


def _provider_pack(prompt_id: str) -> V2PromptPackTemplate:
    return V2PromptPackTemplate(
        prompt_id=prompt_id,
        required_context_keys=("sections",),
        render=lambda context: render_provider_contract_prompt(context, prompt_id=prompt_id),
    )


PROMPT_PACKS: dict[str, V2PromptPackTemplate] = {
    **{prompt_id: _provider_pack(prompt_id) for prompt_id in PROVIDER_SLOT_PROMPT_IDS.values()},
    "v2.provider.shot_cell.v1": _provider_pack("v2.provider.shot_cell.v1"),
    "v2.script_writer.plan.v1": V2PromptPackTemplate(
        prompt_id="v2.script_writer.plan.v1",
        required_context_keys=(
            "required_top_level_fields",
            "canonical_id_fields",
            "forbidden_alias_only_fields",
        ),
        render=render_script_writer_system_prompt,
    ),
    "v2.expert_brief.plan.v1": V2PromptPackTemplate(
        prompt_id="v2.expert_brief.plan.v1",
        required_context_keys=("inventory_constraints",),
        render=render_expert_brief_system_prompt,
    ),
    "v2.specialist.materializer.v1": V2PromptPackTemplate(
        prompt_id="v2.specialist.materializer.v1",
        required_context_keys=("specialist", "slot_type"),
        render=render_specialist_materializer_prompt,
    ),
    "v2.storyboard.detail.v1": V2PromptPackTemplate(
        prompt_id="v2.storyboard.detail.v1",
        required_context_keys=(),
        render=render_storyboard_detail_system_prompt,
    ),
    "v2.visual_style.scope_repair.v1": V2PromptPackTemplate(
        prompt_id="v2.visual_style.scope_repair.v1",
        required_context_keys=("product_name", "raw_visual_style", "identity_terms"),
        render=render_visual_style_scope_repair_prompt,
    ),
    "v2.repair.structured_generation.v1": V2PromptPackTemplate(
        prompt_id="v2.repair.structured_generation.v1",
        required_context_keys=("contract_name",),
        render=render_structured_repair_prompt,
    ),
    "v2.fallback.deterministic_generation.v1": V2PromptPackTemplate(
        prompt_id="v2.fallback.deterministic_generation.v1",
        required_context_keys=("stage_name",),
        render=render_deterministic_fallback_prompt,
    ),
}


def sanitized_context(context: dict[str, Any]) -> dict[str, Any]:
    return sanitize_context_for_llm_text(context)


def _build_profiles() -> dict[str, V2PromptContentProfile]:
    profiles = {
        "v2.script_writer.plan.v1": _profile(
            "script-writer-commercial-plan-v1",
            "v2.script_writer.plan.v1",
            "script_writer",
            min_words=100,
            sections=[
                "Role",
                "Mission",
                "Input Contract",
                "Output Contract",
                "Commercial Story Requirements",
                "Scene And Shot Planning Rules",
                "Product Integration Rules",
                "Character And Location Rules",
                "Dialogue/Narration Rules",
                "Forbidden Behavior",
                "Quality Rubric",
                "Example",
                "Anti-example",
            ],
        ),
        "v2.expert_brief.plan.v1": _profile(
            "expert-brief-planner-v1",
            "v2.expert_brief.plan.v1",
            "expert_brief",
            min_words=100,
            sections=[
                "Role",
                "Mission",
                "Source Inputs",
                "Inventory Constraints",
                "Product Brief Rules",
                "Character Brief Rules",
                "Scene Brief Rules",
                "BGM Brief Rules",
                "Slot Prompt Rules",
                "Forbidden Behavior",
                "Quality Rubric",
                "Example",
                "Anti-example",
            ],
        ),
        "v2.specialist.materializer.v1": _profile(
            "specialist-materializer-owned-scope-v1",
            "v2.specialist.materializer.v1",
            "specialist_materializer",
            sections=[
                "Specialist Role",
                "Owned Scope",
                "Allowed Context",
                "Slot Boundary",
                "Reference Rules",
                "Prompt Writing Rules",
                "Forbidden Behavior",
                "Quality Checklist",
            ],
        ),
        "v2.storyboard.detail.v1": _profile(
            "storyboard-detail-materializer-v1",
            "v2.storyboard.detail.v1",
            "storyboard_detail_prompts",
            min_words=100,
            sections=[
                "Role",
                "Mission",
                "Input Summary",
                "Shot Cell Progression Rules",
                "Same-shot Continuity Rules",
                "Video Timeline Rules",
                "Dialogue Rules",
                "Audio Description Rules",
                "Negative Video Constraints",
                "Forbidden Behavior",
                "Example",
                "Anti-example",
            ],
        ),
        "v2.visual_style.scope_repair.v1": _profile(
            "visual-style-scope-repair-v1",
            "v2.visual_style.scope_repair.v1",
            "visual_style_scope_repair",
            sections=[
                "Role",
                "Mission",
                "Canonical Product",
                "Output Contract",
                "Forbidden Behavior",
            ],
        ),
        "v2.repair.structured_generation.v1": _profile(
            "structured-generation-repair-v1",
            "v2.repair.structured_generation.v1",
            "repair",
            sections=["Role", "Mission", "Repair Rules", "Forbidden Behavior"],
        ),
        "v2.fallback.deterministic_generation.v1": _profile(
            "deterministic-generation-fallback-v1",
            "v2.fallback.deterministic_generation.v1",
            "fallback",
            sections=["Role", "Mission", "Fallback Rules"],
        ),
    }
    for slot_type, prompt_id in PROVIDER_SLOT_PROMPT_IDS.items():
        profiles[prompt_id] = _provider_profile(prompt_id, slot_type)
    profiles["v2.provider.shot_cell.v1"] = _provider_profile(
        "v2.provider.shot_cell.v1",
        "shot_cell",
    )
    return profiles


def _profile(
    profile_id: str,
    prompt_id: str,
    stage: str,
    *,
    sections: list[str],
    min_words: int | None = None,
    max_words: int | None = None,
) -> V2PromptContentProfile:
    return V2PromptContentProfile(
        profile_id=profile_id,
        profile_version="1.0.0",
        prompt_id=prompt_id,
        stage=stage,
        target_min_words=min_words,
        target_max_words=max_words,
        required_sections=sections,
        quality_rules=["slot_specific", "traceable", "sanitized", "English system instructions"],
        forbidden_behaviors=[
            "raw prompt wrapper",
            "sibling prompt copy",
            "media bytes",
            "base64",
            "data URLs",
            "secrets",
        ],
        example_blocks=["Use one compact positive example where the prompt stage needs it."],
        anti_example_blocks=["Reject generic copies, raw wrappers, or cross-slot contamination."],
    )


def _provider_profile(prompt_id: str, slot_type: str) -> V2PromptContentProfile:
    media_profile = _provider_media_profile(slot_type)
    if media_profile == "video":
        return _profile(
            "provider-video-prompt-v1",
            prompt_id,
            "provider_payload",
            min_words=350,
            max_words=900,
            sections=[
                "Slot Contract",
                "Current Prompt",
                "References",
                "Timeline",
                "Negative Constraints",
            ],
        )
    if media_profile == "audio":
        return _profile(
            "provider-bgm-prompt-v1",
            prompt_id,
            "provider_payload",
            min_words=60,
            max_words=180,
            sections=["Slot Contract", "Current Prompt", "Music Direction", "Negative Constraints"],
        )
    return _profile(
        "provider-image-prompt-v1",
        prompt_id,
        "provider_payload",
        min_words=120,
        max_words=350,
        sections=["Slot Contract", "Current Prompt", "References", "Negative Constraints"],
    )


def _provider_boundary_sections(slot_type: str, media_profile: str) -> list[str]:
    base = [
        "Slot contract: Generate only the current slot output. Use the current provider prompt as the source of truth, not the full script, full expert brief, sibling prompts, or frontend notes.",
        "Reference policy: Use submitted references only when they are listed for this slot. Preserve identity, layout, continuity, and reference constraints without inventing new asset ids.",
        "Safety boundary: Do not include encoded media strings, inline data links, sensitive credentials, markdown, captions, UI overlays, diagrams, labels, watermarks, or unrelated content.",
    ]
    slot_specific = {
        "product_main_image": [
            "Product boundary: one reusable product-only hero/reference image with recognizable silhouette, packaging or brand cues, material finish, readable product hierarchy, and clean catalog-style presentation.",
        ],
        "product_multi_view_grid": [
            "Product multi-view boundary: multiple views of the same product, preserving the selected product identity, geometry, packaging, and material details in a controlled reference layout.",
        ],
        "character_main_image": [
            "Character boundary: one single character-only reusable reference with identity, wardrobe, silhouette, body language, neutral presentation, and no products, environment composition, multi-character action, panel-board wording, or multi-view language.",
        ],
        "character_three_view": [
            "Character turnaround boundary: front, side, and back views of the same selected character, preserving face identity, wardrobe, proportions, and silhouette across views.",
        ],
        "scene_main_image": [
            "Scene boundary: one reusable environment-only image with location identity, spatial layout, lighting, materials, time of day, atmosphere, and clean establishing-view presentation.",
        ],
        "scene_multi_view_grid": [
            "Scene multi-view boundary: multiple camera angles of the same empty environment, preserving layout, lighting, materials, atmosphere, and avoiding characters, product action, dialogue, and labels.",
        ],
        "shot_cell": [
            "Storyboard cell boundary: one single full-frame keyframe for the current shot cell, not a collage, contact sheet, split screen, or storyboard sheet. Preserve selected product, character, scene, lighting, and camera continuity.",
        ],
        "shot_video_segment": [
            "Video boundary: create one timeline-based shot video segment from selected same-shot cell images. Preserve product, character, environment, lighting, camera, and motion continuity. Include time segments, action beats, camera movement, dialogue constraints, production audio description, duration, aspect ratio, and negative video constraints.",
            "Video negative constraints: production-audio cues only, subtitles only when requested, no watermarks, no static slideshow motion, no unrelated characters, no unrelated products, no unrelated locations, no distorted product labels, and no identity drift.",
            "Timeline guidance: describe establishing, action, detail, and payoff beats with camera motion and physical continuity. The video prompt must not become a full-ad prompt and must not copy the entire Script Writer output or Expert Brief output.",
        ],
        "bgm_audio": [
            "BGM boundary: instrumental music only. Describe mood, pace, energy curve, duration, instrumentation, commercial fit, and ending feel. No vocals, no lyrics, no voiceover, no sound effects, no image prompt, and no video prompt.",
        ],
        "final_video": [
            "Final composition boundary: deterministic timeline and FFmpeg assembly only. Do not route final composition through an LLM image or video generation provider.",
        ],
        "free_output": [
            "Free output boundary: generate only the requested standalone media output. Do not infer product, character, or scene ownership unless explicit metadata says so.",
        ],
    }
    sections = [*base, *slot_specific.get(slot_type, [])]
    if media_profile == "video":
        sections.extend(
            [
                "Motion detail: specify camera movement, subject movement, timing, continuity sources, and transition behavior in bounded timeline language.",
                "Reference delivery: selected shot cell images are required visual references for this video segment and must control identity and composition continuity.",
            ]
        )
    elif media_profile == "audio":
        sections.append(
            "Music detail: keep the prompt musical and compact; focus on instrumental arrangement, tempo, rhythm, emotion, duration, and commercial lift."
        )
    else:
        sections.append(
            "Image detail: keep the image prompt compact, precise, and visual; describe the single reusable asset requested by the slot rather than a narrative sequence."
        )
    return sections


def _slot_type_for_provider_prompt(prompt_id: str) -> str:
    for slot_type, current_id in PROVIDER_SLOT_PROMPT_IDS.items():
        if current_id == prompt_id:
            return slot_type
    if prompt_id == "v2.provider.shot_cell.v1":
        return "shot_cell"
    return "free_output"


def _provider_media_profile(slot_type: str) -> str:
    if slot_type == "bgm_audio":
        return "audio"
    if slot_type in {"shot_video_segment", "final_video"}:
        return "video"
    return "image"


def _clean_sections(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(section).strip() for section in value if str(section).strip()]


def _compact_provider_sections(
    sections: list[str],
    *,
    slot_type: str,
    media_profile: str,
) -> list[str]:
    if not sections:
        return []
    limits = {
        "shot_cell": 90,
        "scene_main_image": 110,
        "product_main_image": 220,
        "product_multi_view_grid": 220,
        "character_main_image": 220,
        "character_three_view": 220,
        "scene_multi_view_grid": 220,
    }
    if media_profile == "video":
        limit = 520
    elif media_profile == "audio":
        limit = 90
    else:
        limit = limits.get(slot_type, 220)
    return [
        _truncate_words(section, limit) if index == 0 else section
        for index, section in enumerate(sections)
    ]


def _truncate_words(value: str, limit: int) -> str:
    words = value.split()
    if len(words) <= limit:
        return value
    return " ".join(words[:limit]).rstrip(" ,;:.") + "."


def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(dict.fromkeys(section.strip() for section in sections if section.strip()))


def _csv(value: Any) -> str:
    if not isinstance(value, list):
        return "none provided"
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return ", ".join(cleaned) if cleaned else "none provided"


def _count_phrase(value: Any, label: str) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return f"requested {label} count"
    word = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
    }.get(count, str(count))
    plural = label if count == 1 else f"{label}s"
    return f"{word} {plural}"


def _word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", value))


def _budget_status(
    word_count: int,
    *,
    min_words: int | None,
    max_words: int | None,
) -> str:
    if min_words is not None and word_count < min_words:
        return "under_minimum"
    if max_words is not None and word_count > max_words:
        return "over_maximum"
    return "within_budget"
