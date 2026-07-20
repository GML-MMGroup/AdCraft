from typing import Any

# V1/legacy compatibility only. V2 high-risk provider, repair, fallback,
# and storyboard detail prompt paths must not import this module.

from app.services.script_beats import script_beats_from_script


TARGET_PROMPT_NODES = {"character-design", "scene-design", "storyboard", "bgm"}


def build_script_display_prompt(script: dict[str, Any], context: dict[str, Any]) -> str:
    ad_request = _mapping(context.get("ad_request"))
    lines = [
        "Ad Script",
        f"Product: {_text(ad_request.get('product_name'), 'Product')}",
        f"Target audience: {_text(ad_request.get('target_audience'), 'Target audience')}",
        f"Campaign goal: {_text(ad_request.get('campaign_goal'), 'Increase qualified interest')}",
        f"Tone: {_text(ad_request.get('desired_emotion'), 'confident')}",
        "",
        f"Hook: {_text(script.get('hook'))}",
        f"Body: {_text(script.get('body'))}",
        f"CTA: {_text(script.get('cta'))}",
        f"Duration: {_text(script.get('duration_seconds'), '30')} seconds",
        "",
        "Shot beats:",
    ]
    lines.extend(_shot_beat_lines(script))
    lines.extend(
        [
            "",
            "Subtitle lines:",
        ]
    )
    lines.extend(f"- {line}" for line in _string_list(script.get("subtitle_lines")))
    return _clean_lines(lines)


def build_downstream_prompt(
    target_node_id: str,
    script: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    if target_node_id == "character-design":
        return _character_prompt(script, context)
    if target_node_id == "scene-design":
        return _scene_prompt(script, context)
    if target_node_id == "storyboard":
        return _storyboard_prompt(script, context)
    if target_node_id == "bgm":
        return _bgm_prompt(script, context)
    return None


def build_downstream_context(
    target_node_id: str,
    script: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    target_prompt = build_downstream_prompt(target_node_id, script, context)
    requirements = _mapping(context.get("requirements_analysis"))
    product_design = _mapping(context.get("product_design"))
    creative_direction = _mapping(context.get("creative_direction"))
    return {
        "target_node_id": target_node_id,
        "target_node_type": target_node_id,
        "ad_request": _mapping(context.get("ad_request")),
        "requirements": requirements,
        "requirements_analysis": requirements,
        "product_design": product_design,
        "creative_direction": creative_direction,
        "script": script,
        "target_brief": target_prompt,
    }


def build_source_mappings(target_node_id: str) -> list[dict[str, str]]:
    return [
        {
            "source_node_id": "script",
            "target_node_id": target_node_id,
            "field": "script",
        },
        {
            "source_node_id": "hidden-planning-context",
            "target_node_id": target_node_id,
            "field": "planning_context",
        },
    ]


def build_projected_input_context(
    target_node_id: str,
    script: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    prompt = build_downstream_prompt(target_node_id, script, context)
    if prompt is None:
        return {}
    resolved_context = build_downstream_context(target_node_id, script, context)
    return {
        "materialized_prompt": prompt,
        "resolved_input_context": resolved_context,
        "source_mappings": build_source_mappings(target_node_id),
        "system_resolved_prompt_preview": _preview(prompt),
        "system_resolved_prompt_with_assets": prompt,
        "resolved_input_assets": [],
        "materialized_assets": [],
    }


def _character_prompt(script: dict[str, Any], context: dict[str, Any]) -> str:
    ad_request = _mapping(context.get("ad_request"))
    requirements = _mapping(context.get("requirements_analysis"))
    creative = _mapping(context.get("creative_direction"))
    return _clean_lines(
        [
            "Character design brief",
            f"Product and brand context: {_product_context(ad_request, context)}",
            f"Target audience: {_text(requirements.get('target_audience') or ad_request.get('target_audience'))}",
            f"Brand emotion and tone: {_text(creative.get('tone') or ad_request.get('desired_emotion'))}",
            f"Script role cues: Hook - {_text(script.get('hook'))}; Body - {_text(script.get('body'))}; CTA - {_text(script.get('cta'))}",
            "Character requirements:",
            "- Define the people or implied product users needed by the ad.",
            "- Describe each character's function in the commercial, personality, and appearance direction.",
            "- Keep the brief focused on character design only.",
        ]
    )


def _scene_prompt(script: dict[str, Any], context: dict[str, Any]) -> str:
    ad_request = _mapping(context.get("ad_request"))
    product = _mapping(context.get("product_design"))
    creative = _mapping(context.get("creative_direction"))
    requirements = _mapping(context.get("requirements_analysis"))
    lines = [
        "Scene design brief",
        f"Product showcase environment: {_text(product.get('presentation_strategy') or product.get('showcase_focus'))}",
        f"Script space and action: Hook - {_text(script.get('hook'))}; Body - {_text(script.get('body'))}; CTA - {_text(script.get('cta'))}",
        f"Visual style: {_text(requirements.get('visual_style') or ad_request.get('visual_style'), 'brand-aligned commercial style')}",
        f"Lighting and color direction: {_text(creative.get('tone') or ad_request.get('desired_emotion'))}",
        "",
        "Shot beats:",
    ]
    lines.extend(_shot_beat_lines(script))
    lines.extend(
        [
            "",
            "Scene requirements:",
            "- Create at least 3 distinct scene specs for a 30 second ad unless the script explicitly has only one location.",
            "- Assign stable scene ids such as scene_001, scene_002, scene_003 and keep asset ids separate.",
            "- Make locations, lighting, atmosphere, and spatial layout visibly different across scene specs.",
            "- CTA can reuse an earlier product scene only when the scene spec says it is a reuse.",
            "- Keep the brief focused on scene and environment design only.",
        ]
    )
    return _clean_lines(lines)


def _storyboard_prompt(script: dict[str, Any], context: dict[str, Any]) -> str:
    ad_request = _mapping(context.get("ad_request"))
    product = _mapping(context.get("product_design"))
    requirements = _mapping(context.get("requirements_analysis"))
    subtitle_lines = _string_list(script.get("subtitle_lines"))
    lines = [
        "Storyboard brief",
        f"Campaign goal: {_text(requirements.get('campaign_goal') or ad_request.get('campaign_goal'))}",
        f"Product showcase focus: {_text(product.get('showcase_focus') or ad_request.get('product_description'))}",
        f"Visual style: {_text(requirements.get('visual_style') or ad_request.get('visual_style'), 'brand-aligned commercial style')}",
        f"Duration: {_text(script.get('duration_seconds'), ad_request.get('duration_seconds') or '30')} seconds",
        "",
        f"Hook: {_text(script.get('hook'))}",
        f"Body: {_text(script.get('body'))}",
        f"CTA: {_text(script.get('cta'))}",
        "",
        "Shot beats:",
    ]
    lines.extend(_shot_beat_lines(script))
    lines.extend(
        [
            "",
            "Subtitle lines:",
        ]
    )
    lines.extend(f"- {line}" for line in subtitle_lines)
    lines.extend(
        [
            "",
            "Storyboard requirements:",
            "- Return canonical shots, one single keyframe plan per shot.",
            "- Each shot must include shot_id, order, prompt, primary_scene_id, scene_reference_ids, character_ids, product_reference_ids, duration_seconds, camera, action, and input_asset_ids.",
            "- Bind primary_scene_id and scene_reference_ids to available scene ids; include only the product, scene, and character asset ids needed by that shot.",
            "- A scene-free product packshot/title/abstract/transition shot must include no_scene_reason instead of inventing a scene id.",
            "- Do not describe a storyboard sheet, multi-panel layout, comic strip, collage, grid, or multiple frames in one shot.",
        ]
    )
    return _clean_lines(lines)


def _bgm_prompt(script: dict[str, Any], context: dict[str, Any]) -> str:
    ad_request = _mapping(context.get("ad_request"))
    creative = _mapping(context.get("creative_direction"))
    duration = _text(script.get("duration_seconds"), ad_request.get("duration_seconds") or "30")
    return _clean_lines(
        [
            "BGM music brief",
            f"Desired emotion: {_text(ad_request.get('desired_emotion') or creative.get('tone'), 'confident')}",
            f"Duration: {duration} seconds",
            f"Brand tone: {_text(creative.get('key_message') or creative.get('concept'))}",
            "Script rhythm:",
            f"- Intro / hook: {_text(script.get('hook'))}",
            f"- Product reveal / body: {_text(script.get('body'))}",
            f"- CTA lift: {_text(script.get('cta'))}",
            "Music structure:",
            "- Start with a concise intro that supports the hook.",
            "- Build energy during the product reveal without overpowering subtitles.",
            "- Resolve cleanly under the CTA.",
            "- Do not invent audio file paths or output assets.",
        ]
    )


def _product_context(ad_request: dict[str, Any], context: dict[str, Any]) -> str:
    product = _mapping(context.get("product_design"))
    parts = [
        _text(ad_request.get("product_name")),
        _text(ad_request.get("product_description")),
        _text(product.get("showcase_focus")),
    ]
    return " | ".join(part for part in parts if part) or "Product context"


def _shot_beat_lines(script: dict[str, Any]) -> list[str]:
    beats = script_beats_from_script(script)
    if not beats:
        return ["- No structured shot beats provided yet."]
    return [
        (
            f"- Beat {beat.get('order')}: {beat.get('duration_seconds')}s | "
            f"{_text(beat.get('scene_intent'))} | location: {_text(beat.get('location_hint'))} | "
            f"visual: {_text(beat.get('visual_action'))} | product: {_text(beat.get('product_action'))} | "
            f"copy: {_text(beat.get('spoken_or_on_screen_text'))}"
        )
        for beat in beats
    ]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value: Any, fallback: Any = "") -> str:
    if value is None:
        value = fallback
    text = str(value).strip()
    return text or str(fallback or "").strip()


def _preview(prompt: str) -> str:
    return prompt[:240] + ("..." if len(prompt) > 240 else "")


def _clean_lines(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines if line is not None).strip()
