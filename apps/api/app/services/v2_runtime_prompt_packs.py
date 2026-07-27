from __future__ import annotations

from collections.abc import Callable
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
