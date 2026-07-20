from pathlib import Path
from typing import Any
from uuid import uuid4

from agno.team import Team

from app.schemas.ad_workflow import (
    AdWorkflowGenerateRequest,
    AdWorkflowResponse,
    WorkflowEdge,
    WorkflowNode,
)
from app.schemas.agent_outputs import (
    BgmOutput,
    FinalVideoGenerationOutput,
    SoundEffectsOutput,
    SubtitleGenerationOutput,
    VoiceoverOutput,
)
from app.tools.media import MediaProvider
from app.services.input_modality import (
    assets_for_prompt_target,
    classify_input_modality,
    selected_asset_summary,
)
from app.services.asset_library_references import (
    normalize_asset_references,
    reference_context_for_node,
)
from app.services.media_inputs import convert_assets_for_model_input, role_for_workflow_asset
from app.services.media_paths import (
    input_assets_from_content,
    output_assets_from_content,
    with_public_urls,
)
from app.services.script_beats import build_default_script_beats, ensure_script_beat_aliases

LEGACY_REFERENCE_NODE_IDS = {
    "script",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
    "final-composition",
}


def _format_timeline_time(seconds: int) -> str:
    minutes, whole_seconds = divmod(seconds, 60)
    return f"00:{minutes:02}:{whole_seconds:02},000"


def _build_mock_script(
    request: AdWorkflowGenerateRequest,
    channels: str,
) -> dict[str, Any]:
    shot_beats = build_default_script_beats(
        product_name=request.product_name,
        desired_emotion=request.desired_emotion,
        duration_seconds=request.duration_seconds,
        target_audience=request.target_audience,
        campaign_goal=request.campaign_goal,
    )
    if "柠檬茶" in request.product_name or "柠檬茶" in request.product_description:
        hook = "夏天来了，来一口清爽柠檬茶。"
        body = "清新柠檬香气，冰爽解渴，陪你从通勤到课间都保持轻松活力。"
        cta = "这个夏天，和柠檬茶一起清爽出发。"
        for beat, line in zip(
            shot_beats,
            [
                hook,
                "冰块、柠檬和茶香一起唤醒清爽。",
                body,
                "朋友聚在一起，分享同一份夏日轻松。",
                cta,
                cta,
            ],
            strict=False,
        ):
            beat["spoken_or_on_screen_text"] = line
    else:
        hook = f"{request.product_name}，让这一刻更{request.desired_emotion}。"
        body = f"专为{request.target_audience}打造，带来更{request.desired_emotion}的使用体验。"
        cta = f"现在就和{request.product_name}一起出发。"

    return {
        "hook": hook,
        "body": body,
        "cta": cta,
        "channels": channels,
        "structure": [beat["scene_intent"] for beat in shot_beats],
        "script_structure": [beat["scene_intent"] for beat in shot_beats],
        "subtitle_lines": [beat["spoken_or_on_screen_text"] for beat in shot_beats],
        "duration_seconds": request.duration_seconds,
        "shot_beats": shot_beats,
        "beats": shot_beats,
        "script_beats": shot_beats,
    }


def _aspect_ratio_for_channels(channels: list[str]) -> str:
    normalized_channels = {channel.lower() for channel in channels}
    if {"tiktok", "reels", "shorts", "social"} & normalized_channels:
        return "9:16"
    if {"landing-page", "youtube"} & normalized_channels:
        return "16:9"
    return "16:9"


def _aspect_ratio_for_request(request: AdWorkflowGenerateRequest) -> str:
    return request.aspect_ratio or _aspect_ratio_for_channels(request.channels)


def _storyboard_segment_durations(duration_seconds: int) -> list[int]:
    if duration_seconds % 5 != 0:
        raise ValueError(
            "Cannot normalize storyboard video duration into Seedance 5 or 10 second "
            f"segments: got {duration_seconds} seconds."
        )
    ten_second_count, remainder = divmod(duration_seconds, 10)
    durations = [10] * ten_second_count
    if remainder:
        durations.append(5)
    return durations


def _default_storyboard_scene(
    request: AdWorkflowGenerateRequest,
    index: int,
    duration_seconds: int,
) -> dict[str, Any]:
    templates = [
        {
            "shot": "wide shot",
            "visual": "Audience problem and usage context",
            "text": "Need a better way?",
            "camera": "smooth establishing move",
            "action": "Show the target audience in a relatable moment.",
        },
        {
            "shot": "product close-up",
            "visual": request.product_name,
            "text": "Meet the solution.",
            "camera": "clean push-in and product detail close-ups",
            "action": "Reveal the product and show the core selling point clearly.",
        },
        {
            "shot": "closing hero shot",
            "visual": "Product benefit and call to action",
            "text": request.campaign_goal,
            "camera": "confident hero framing with a clear CTA",
            "action": "End with the product, benefit, and next step.",
        },
    ]
    template = templates[min(index - 1, len(templates) - 1)]
    scene_reference_id = f"scene-reference-{index}"
    return {
        "order": index,
        "scene_id": scene_reference_id,
        "duration_seconds": duration_seconds,
        "input_asset_ids": [scene_reference_id],
        **template,
    }


def _normalize_storyboard_scenes(
    raw_scenes: list[dict[str, Any]],
    request: AdWorkflowGenerateRequest,
    script: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    script_beats = (
        ensure_script_beat_aliases(script).get("shot_beats", []) if isinstance(script, dict) else []
    )
    _storyboard_segment_durations(request.duration_seconds)
    if not raw_scenes and isinstance(script_beats, list) and script_beats:
        return [
            {
                "order": index,
                "scene_id": beat.get("scene_id") or f"scene-reference-{index}",
                "shot": _default_storyboard_scene(
                    request,
                    index,
                    int(beat.get("duration_seconds") or 6),
                )["shot"],
                "visual": (
                    f"{beat.get('scene_intent', '')}: {beat.get('visual_action', '')}"
                ).strip(": "),
                "text": beat.get("spoken_or_on_screen_text") or "",
                "camera": "smooth commercial camera movement",
                "action": beat.get("product_action") or "",
                "duration_seconds": int(beat.get("duration_seconds") or 6),
                "input_asset_ids": beat.get("input_asset_ids")
                or [beat.get("scene_id") or f"scene-reference-{index}"],
            }
            for index, beat in enumerate(script_beats, start=1)
            if isinstance(beat, dict)
        ]
    durations = _storyboard_segment_durations(request.duration_seconds)
    normalized_scenes = []
    for index, duration in enumerate(durations, start=1):
        source_scene = raw_scenes[index - 1] if index <= len(raw_scenes) else {}
        if not isinstance(source_scene, dict):
            source_scene = {}
        default_scene = _default_storyboard_scene(request, index, duration)
        normalized_scenes.append(
            {
                **default_scene,
                **source_scene,
                "order": index,
                "scene_id": source_scene.get("scene_id") or f"scene-reference-{index}",
                "duration_seconds": duration,
                "input_asset_ids": source_scene.get("input_asset_ids")
                or [source_scene.get("scene_id") or f"scene-reference-{index}"],
            }
        )
    return normalized_scenes


def _storyboard_input_assets(storyboard_images: dict[str, Any]) -> list[dict[str, Any]]:
    assets = []
    for asset in storyboard_images.get("assets", []):
        assets.append(
            {
                "asset_id": asset["asset_id"],
                "asset_type": "image",
                "local_path": asset.get("local_path"),
                "url": asset.get("url"),
                "mime_type": asset.get("mime_type") or "application/json",
                "role": "storyboard",
                "source": "storyboard-image-generation",
                "source_node": "storyboard-image-generation",
            }
        )
    return assets


def _character_turnaround_input_assets(
    character_turnaround_images: dict[str, Any],
) -> list[dict[str, Any]]:
    assets = []
    for asset in character_turnaround_images.get("assets", []):
        assets.append(
            {
                "asset_id": asset["asset_id"],
                "asset_type": "image",
                "local_path": asset.get("local_path"),
                "url": asset.get("url"),
                "mime_type": asset.get("mime_type") or "image/png",
                "role": "character_turnaround",
                "source": "character-image-generation",
                "source_node": "character-image-generation",
                "character_name": asset.get("character_name"),
            }
        )
    return assets


def _scene_reference_input_assets(
    scene_reference_images: dict[str, Any],
) -> list[dict[str, Any]]:
    assets = []
    for asset in scene_reference_images.get("assets", []):
        assets.append(
            {
                "asset_id": asset["asset_id"],
                "asset_type": "image",
                "local_path": asset.get("local_path"),
                "url": asset.get("url"),
                "remote_url": asset.get("remote_url"),
                "mime_type": asset.get("mime_type") or "image/png",
                "role": "scene_reference",
                "source": "scene-image-generation",
                "source_node": "scene-image-generation",
            }
        )
    return assets


def _selected_input_assets(selected_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "asset_id": asset["asset_id"],
            "asset_type": asset["asset_type"],
            "local_path": asset.get("local_path"),
            "url": asset.get("url"),
            "mime_type": asset.get("mime_type"),
            "role": role_for_workflow_asset(asset.get("asset_role")),
            "source": "selected_assets",
            "source_node": "selected_assets",
        }
        for asset in selected_assets
        if asset.get("use_as_prompt") is True
    ]


def _legacy_reference_contexts(
    data_dir: Path,
    request: AdWorkflowGenerateRequest,
    workflow_id: str,
) -> dict[str, dict[str, Any]]:
    references = normalize_asset_references(
        data_dir,
        request.asset_references,
        library_entity_ids=request.library_entity_ids,
        available_node_ids=LEGACY_REFERENCE_NODE_IDS,
        workflow_id=workflow_id,
    )
    return {
        node_id: reference_context_for_node(references, node_id)
        for node_id in LEGACY_REFERENCE_NODE_IDS
    }


def _combined_reference_context(
    reference_contexts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    combined: dict[str, list[dict[str, Any]]] = {
        "asset_references": [],
        "prompt_context_assets": [],
        "provider_reference_assets": [],
        "display_input_assets": [],
    }
    seen: set[tuple[str, str]] = set()
    for context in reference_contexts.values():
        references = context.get("asset_references")
        for reference in references if isinstance(references, list) else []:
            if not isinstance(reference, dict):
                continue
            key = (
                str(reference.get("entity_id") or ""),
                ",".join(str(asset_id) for asset_id in reference.get("asset_ids", [])),
            )
            if key in seen:
                continue
            seen.add(key)
            combined["asset_references"].append(reference)
        for field in (
            "prompt_context_assets",
            "provider_reference_assets",
            "display_input_assets",
        ):
            assets = context.get(field)
            for asset in assets if isinstance(assets, list) else []:
                if isinstance(asset, dict):
                    combined[field].append(asset)
    return combined


def _reference_assets(context: dict[str, Any]) -> list[dict[str, Any]]:
    assets = context.get("display_input_assets")
    return (
        [asset for asset in assets if isinstance(asset, dict)] if isinstance(assets, list) else []
    )


def _with_reference_context(
    payload: dict[str, Any],
    context: dict[str, Any],
    *,
    input_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    references = context.get("asset_references")
    if not references and not input_assets:
        return payload
    updated = dict(payload)
    for key in (
        "asset_references",
        "prompt_context_assets",
        "provider_reference_assets",
        "display_input_assets",
        "source_mappings",
    ):
        value = context.get(key)
        if value:
            updated[key] = value
    if input_assets:
        updated["input_assets"] = [*updated.get("input_assets", []), *input_assets]
    return updated


def _reference_input_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key in (
            "asset_references",
            "prompt_context_assets",
            "provider_reference_assets",
            "display_input_assets",
            "source_mappings",
        )
        if (value := context.get(key))
    }


def _build_final_video_generation_output(
    *,
    request: AdWorkflowGenerateRequest,
    requirements_analysis: dict[str, Any],
    creative_direction: dict[str, Any],
    script: dict[str, Any],
    subtitle_generation: dict[str, Any],
    storyboard_scenes: list[dict[str, Any]],
    storyboard_images: dict[str, Any],
    character_turnaround_images: dict[str, Any],
    scene_reference_images: dict[str, Any],
    character_design: dict[str, Any],
    scene_design: dict[str, Any],
    selected_assets: list[dict[str, Any]],
    library_reference_assets: list[dict[str, Any]],
    library_reference_context: dict[str, Any],
    visual_style: str,
    skip_audio_agents: bool,
    data_dir: Path,
) -> dict[str, Any]:
    character_turnaround_assets = _character_turnaround_input_assets(character_turnaround_images)
    scene_reference_assets = _scene_reference_input_assets(scene_reference_images)
    raw_input_assets = (
        _storyboard_input_assets(storyboard_images)
        + character_turnaround_assets
        + scene_reference_assets
        + _selected_input_assets(selected_assets)
        + library_reference_assets
    )
    input_assets = convert_assets_for_model_input(data_dir, raw_input_assets)
    input_asset_ids = [asset["asset_id"] for asset in input_assets]
    scene_prompts = [
        {
            "order": scene["order"],
            "scene_id": scene.get("scene_id") or f"scene-{scene['order']}",
            "prompt": (
                f"Scene {scene['order']}: {scene.get('shot', 'shot')} showing "
                f"{scene.get('visual', '')}. On-screen or spoken copy: {scene.get('text', '')}. "
                f"Dialogue: {scene.get('dialogue') or scene.get('text', '')}. "
                f"Camera/action: {scene.get('camera', '')} {scene.get('action', '')}. "
                "Use product, character turnaround, scene reference, and storyboard images "
                "for product, identity, environment, and shot consistency. "
                f"Maintain {visual_style} style and campaign tone."
            ),
            "duration_seconds": scene.get("duration_seconds"),
            "input_asset_ids": _video_scene_prompt_input_asset_ids(
                scene,
                input_assets,
                fallback_asset_ids=input_asset_ids,
            ),
        }
        for scene in storyboard_scenes
    ]
    subtitle_lines = script.get("subtitle_lines") or [
        script.get("hook", ""),
        script.get("body", ""),
        script.get("cta", ""),
    ]
    subtitle_cues = [
        {
            "start_time": cue.get("start_time"),
            "end_time": cue.get("end_time"),
            "text": cue.get("text"),
        }
        for cue in subtitle_generation.get("cues", [])
    ]
    final_video_prompt = (
        f"Prepare formal storyboard video segment prompts for a "
        f"{request.duration_seconds}-second advertisement for "
        f"{request.product_name}. Requirements: {requirements_analysis}. Creative direction: "
        f"{creative_direction}. Script lines: {subtitle_lines}. Subtitle timing plan: "
        f"{subtitle_cues}. Character design: "
        f"{character_design}. Character turnaround assets: {character_turnaround_assets}. "
        f"Scene design: {scene_design}. Scene reference assets: {scene_reference_assets}. "
        "Use storyboard, product reference, character turnaround, scene reference, and selected "
        "assets as multimodal references. Keep product packaging, colors, logo, shape, and "
        "proportions consistent. Use the same character turnaround references in "
        "every storyboard video segment to preserve identity and the same scene references to "
        "preserve environment continuity. Keep segment transitions coherent "
        "so FFmpeg can concatenate them into one finished ad video."
    )
    audio_strategy = (
        "Skip dedicated sound effects, voiceover, BGM, audio generation, and audio-video sync. "
        "Generate the final video directly from the multimodal visual prompt; use silent or "
        "model-native audio if the video provider supports it."
        if skip_audio_agents
        else (
            "Current main path can use silent or model-native audio. Sound effects, voiceover, "
            "and BGM agents remain available for later professional audio composition."
        )
    )
    output = FinalVideoGenerationOutput.model_validate(
        {
            "final_video_prompt": final_video_prompt,
            "negative_prompt": (
                "low quality, distorted faces, inconsistent character identity, unreadable text, "
                "extra limbs, abrupt scene changes, off-brand colors"
            ),
            "input_assets": input_assets,
            "scene_prompts": scene_prompts,
            "duration_seconds": request.duration_seconds,
            "aspect_ratio": _aspect_ratio_for_request(request),
            "output_resolution": request.output_resolution or "480p",
            "style": visual_style,
            "camera_motion": "smooth commercial camera movement with clear product emphasis",
            "continuity_notes": (
                "Use character turnaround references to keep character identity consistent. "
                "Keep character face shape, hair, outfit, body type, age, and temperament "
                "consistent across every storyboard beat. Also keep product appearance, "
                "lighting, and scene transitions consistent."
            ),
            "audio_strategy": audio_strategy,
            "generation_provider_hint": "volcengine-video-generation",
            "status": "ready",
        }
    ).model_dump()
    return _with_reference_context(output, library_reference_context)


def _video_scene_prompt_input_asset_ids(
    scene: dict[str, Any],
    input_assets: list[dict[str, Any]],
    *,
    fallback_asset_ids: list[str],
) -> list[str]:
    available_ids = {
        str(asset.get("asset_id") or "")
        for asset in input_assets
        if str(asset.get("asset_id") or "").strip()
    }
    if not available_ids:
        return fallback_asset_ids
    order = int(scene.get("order") or 1)
    explicit_ids = (
        [str(asset_id) for asset_id in scene.get("input_asset_ids", []) if str(asset_id).strip()]
        if isinstance(scene.get("input_asset_ids"), list)
        else []
    )
    scoped_ids = [
        str(asset.get("asset_id"))
        for asset in input_assets
        if asset.get("role") in {"product_reference", "character_turnaround"}
        and asset.get("asset_id")
    ]
    scoped_ids.extend(explicit_ids)
    storyboard_asset_id = f"storyboard-image-{order}"
    if storyboard_asset_id in available_ids:
        scoped_ids.append(storyboard_asset_id)
    deduped = [asset_id for asset_id in dict.fromkeys(scoped_ids) if asset_id in available_ids]
    return deduped or fallback_asset_ids


def build_ad_workflow_graph(
    request: AdWorkflowGenerateRequest,
    team: Team,
    data_dir: Path,
    workflow_id: str,
    media_provider: MediaProvider,
    agent_outputs: dict[str, dict[str, Any]] | None = None,
    skip_audio_agents: bool = False,
) -> AdWorkflowResponse:
    team_name = team.name or "AdCraft Creative Team"
    channels = ", ".join(request.channels)
    selling_point = request.core_selling_point or request.product_description
    visual_style = request.visual_style or "brand-aligned commercial style"
    input_modality = classify_input_modality(request.selected_assets)
    selected_assets = selected_asset_summary(request.selected_assets)
    reference_contexts = _legacy_reference_contexts(data_dir, request, workflow_id)
    all_reference_context = _combined_reference_context(reference_contexts)
    character_reference_context = reference_contexts["character-generation"]
    scene_reference_context = reference_contexts["scene-generation"]
    storyboard_reference_context = reference_contexts["storyboard"]
    storyboard_video_reference_context = reference_contexts["storyboard-video-generation"]
    bgm_reference_context = reference_contexts["bgm"]
    final_reference_context = reference_contexts["final-composition"]
    common_metadata = {
        "mode": "real" if agent_outputs else "mock",
        "media_mode": media_provider.mode,
        "team": team_name,
        "input_modality": input_modality,
        "skip_audio_agents": skip_audio_agents,
    }
    member_models = {
        member.name: getattr(member.model, "id", None)
        for member in team.members
        if getattr(member, "name", None) is not None
    }
    outputs = agent_outputs or {}
    requirements_analysis = outputs.get(
        "requirements-analysis",
        {
            "product": request.product_name,
            "core_selling_point": selling_point,
            "target_audience": request.target_audience,
            "campaign_goal": request.campaign_goal,
            "desired_emotion": request.desired_emotion,
            "duration_seconds": request.duration_seconds,
            "visual_style": visual_style,
            "references": request.references,
            "input_modality": input_modality,
            "selected_assets": selected_assets,
        },
    )
    requirements_analysis = _with_reference_context(requirements_analysis, all_reference_context)
    product_design = outputs.get(
        "product-design",
        {
            "showcase_focus": selling_point,
            "presentation_strategy": (
                f"Present {request.product_name} as a clear solution for {request.target_audience}."
            ),
            "channels": request.channels,
            "asset_prompt_context": assets_for_prompt_target(
                request.selected_assets,
                "product_design",
            ),
        },
    )
    product_design = _with_reference_context(product_design, storyboard_reference_context)
    creative_direction = outputs.get(
        "creative-direction",
        {
            "concept": f"Show how {request.product_name} helps {request.target_audience}.",
            "key_message": f"{request.product_name}: a practical answer to a real need.",
            "tone": request.desired_emotion,
            "channels": request.channels,
        },
    )
    script = outputs.get(
        "script",
        _build_mock_script(request, channels),
    )
    character_design = outputs.get(
        "character-design",
        {
            "characters": [
                {
                    "name": "Audience Representative",
                    "role": "Main character",
                    "appearance": "Approachable and aligned with the target audience.",
                    "personality": f"Expresses a {request.desired_emotion} brand tone.",
                }
            ],
            "asset_prompt_context": assets_for_prompt_target(
                request.selected_assets,
                "character_design",
            ),
        },
    )
    character_design = _with_reference_context(character_design, character_reference_context)
    scene_design = outputs.get(
        "scene-design",
        {
            "scenes": [
                {
                    "scene_id": "scene-reference-1",
                    "order": 1,
                    "location": "Everyday workspace",
                    "lighting": "Natural, slightly muted before the product reveal.",
                    "atmosphere": "Relatable and focused on the audience problem.",
                },
                {
                    "scene_id": "scene-reference-2",
                    "order": 2,
                    "location": "Product showcase",
                    "lighting": "Clean and bright after the reveal.",
                    "atmosphere": request.desired_emotion,
                },
                {
                    "scene_id": "scene-reference-3",
                    "order": 3,
                    "location": "Lifestyle proof environment",
                    "lighting": "Warm, open, and visually distinct from the showcase.",
                    "atmosphere": f"{request.desired_emotion} with social proof.",
                },
            ],
            "asset_prompt_context": assets_for_prompt_target(
                request.selected_assets,
                "scene_design",
            ),
        },
    )
    scene_design = _with_reference_context(scene_design, scene_reference_context)
    storyboard_scenes = _normalize_storyboard_scenes(
        outputs.get("storyboard", {}).get("scenes", []),
        request,
        script,
    )
    subtitle_generation = outputs.get(
        "subtitle-generation"
    ) or media_provider.generate_subtitle_asset(
        script,
        request.duration_seconds,
        workflow_id,
    )
    subtitle_generation = SubtitleGenerationOutput.model_validate(subtitle_generation).model_dump()
    sound_effects_plan = outputs.get(
        "sound-effects",
        {
            "sound_effect_tracks": [
                {
                    "scene": 1,
                    "order": 1,
                    "start_time": "00:00:00,000",
                    "end_time": "00:00:05,000",
                    "sound_type": "environment",
                    "description": "Subtle ambient sounds for the opening problem moment.",
                    "intensity": "low",
                    "generation_prompt": "Generate subtle commercial ambient room tone.",
                    "sync_notes": "Keep below voice and music levels.",
                },
                {
                    "scene": 2,
                    "order": 2,
                    "start_time": "00:00:05,000",
                    "end_time": "00:00:10,000",
                    "sound_type": "product_interaction",
                    "description": "Soft transition accent for the product reveal.",
                    "intensity": "medium",
                    "generation_prompt": "Generate a clean product reveal accent.",
                    "sync_notes": "Align with the product close-up.",
                },
            ],
            "sync_notes": "Align effects to storyboard cuts and avoid voices or music.",
        },
    )
    sound_effects_plan = SoundEffectsOutput.model_validate(sound_effects_plan).model_dump()
    voiceover_plan = outputs.get(
        "voiceover",
        {
            "has_voiceover": True,
            "voice_tracks": [
                {
                    "cue_id": cue["cue_id"],
                    "scene": cue["scene"],
                    "order": cue["order"],
                    "start_time": cue["start_time"],
                    "end_time": cue["end_time"],
                    "text": cue["text"],
                    "voice_type": "narrator",
                    "character_name": None,
                    "voice_profile": "Warm, clear commercial narrator",
                    "emotion": request.desired_emotion,
                    "speed": "normal",
                    "volume": "medium",
                    "generation_prompt": (
                        "Read this subtitle text exactly as written with a clear "
                        f"{request.desired_emotion} commercial tone: {cue['text']}"
                    ),
                    "sync_notes": "Follow subtitle cue timing exactly.",
                }
                for cue in subtitle_generation["cues"]
            ],
            "sync_notes": "Use subtitle timings as the source of truth.",
        },
    )
    voiceover_plan = VoiceoverOutput.model_validate(voiceover_plan).model_dump()
    bgm_plan = outputs.get(
        "bgm",
        {
            "music_style": "brand-safe commercial background music",
            "mood": request.desired_emotion,
            "tempo": "medium",
            "instruments": ["soft synth", "light percussion", "warm pad"],
            "structure": ["intro hook", "product showcase lift", "CTA resolution"],
            "start_time": "00:00:00,000",
            "end_time": _format_timeline_time(request.duration_seconds),
            "fade_in": "00:00:01,000",
            "fade_out": "00:00:02,000",
            "generation_prompt": (
                f"Generate {request.desired_emotion} background music for a "
                f"{request.duration_seconds}-second ad with no voices and no sound effects."
            ),
            "sync_notes": "Keep room for voiceover and align lifts to visual transitions.",
        },
    )
    bgm_plan = BgmOutput.model_validate(bgm_plan).model_dump()
    bgm_plan = _with_reference_context(bgm_plan, bgm_reference_context)
    character_reference_input_assets = convert_assets_for_model_input(
        data_dir,
        _reference_assets(character_reference_context),
    )
    character_turnaround_images = media_provider.generate_character_turnaround_images(
        character_design,
        workflow_id,
    )
    character_turnaround_images = _with_reference_context(
        character_turnaround_images,
        character_reference_context,
        input_assets=character_reference_input_assets,
    )
    character_turnaround_images.setdefault(
        "output_assets",
        character_turnaround_images.get("assets", []),
    )
    scene_reference_input_assets = convert_assets_for_model_input(
        data_dir,
        _reference_assets(scene_reference_context),
    )
    scene_reference_images = media_provider.generate_scene_reference_images(
        scene_design,
        workflow_id,
    )
    scene_reference_images = _with_reference_context(
        scene_reference_images,
        scene_reference_context,
        input_assets=scene_reference_input_assets,
    )
    storyboard_reference_assets = _reference_assets(storyboard_reference_context)
    pre_storyboard_input_assets = convert_assets_for_model_input(
        data_dir,
        _character_turnaround_input_assets(character_turnaround_images)
        + _scene_reference_input_assets(scene_reference_images)
        + _selected_input_assets(selected_assets)
        + storyboard_reference_assets,
    )
    storyboard_images = media_provider.generate_storyboard_images(
        storyboard_scenes,
        workflow_id,
        input_assets=pre_storyboard_input_assets,
        context={
            "script": script,
            "character_design": character_design,
            "scene_design": scene_design,
            "product_design": product_design,
            "creative_direction": creative_direction,
        },
    )
    storyboard_images = _with_reference_context(
        storyboard_images,
        storyboard_reference_context,
        input_assets=convert_assets_for_model_input(data_dir, storyboard_reference_assets),
    )
    final_video_generation_agent = outputs.get(
        "final-video-generation-agent"
    ) or _build_final_video_generation_output(
        request=request,
        requirements_analysis=requirements_analysis,
        creative_direction=creative_direction,
        script=script,
        subtitle_generation=subtitle_generation,
        storyboard_scenes=storyboard_scenes,
        storyboard_images=storyboard_images,
        character_turnaround_images=character_turnaround_images,
        scene_reference_images=scene_reference_images,
        character_design=character_design,
        scene_design=scene_design,
        selected_assets=selected_assets,
        library_reference_assets=_reference_assets(storyboard_video_reference_context),
        library_reference_context=storyboard_video_reference_context,
        visual_style=visual_style,
        skip_audio_agents=skip_audio_agents,
        data_dir=data_dir,
    )
    final_video_generation_agent = FinalVideoGenerationOutput.model_validate(
        final_video_generation_agent
    ).model_dump()
    storyboard_video = media_provider.generate_storyboard_video(
        final_video_generation_agent,
        workflow_id,
    )
    storyboard_video = _with_reference_context(
        storyboard_video,
        storyboard_video_reference_context,
        input_assets=convert_assets_for_model_input(
            data_dir,
            _reference_assets(storyboard_video_reference_context),
        ),
    )
    if skip_audio_agents:
        audio_assets = {
            "provider": "skipped-audio-generation",
            "asset_id": "audio-package",
        }
        synchronized_video = {
            "provider": "skipped-audio-video-sync",
            "asset_id": "synchronized-preview-video",
        }
    else:
        audio_assets = media_provider.generate_audio_assets(
            sound_effects_plan,
            voiceover_plan,
            bgm_plan,
            workflow_id,
        )
        synchronized_video = media_provider.synchronize_audio_video(
            storyboard_video, audio_assets, workflow_id
        )
    final_video = media_provider.compose_final_video(
        storyboard_video,
        request.duration_seconds,
        workflow_id,
    )
    final_video = _with_reference_context(
        final_video,
        final_reference_context,
        input_assets=convert_assets_for_model_input(
            data_dir,
            _reference_assets(final_reference_context),
        ),
    )

    nodes = [
        WorkflowNode(
            id="requirements-analysis",
            type="agent",
            title="Requirements Analysis",
            description="Clarify selling points, audience, emotion, duration, and references.",
            content=requirements_analysis,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "requirements",
                "agent": "Product Analyst Agent",
                "model": member_models.get("Product Analyst Agent"),
            },
        ),
        WorkflowNode(
            id="product-design",
            type="agent",
            title="Commercial Product Design",
            description="Translate product value into a marketable showcase strategy.",
            content=product_design,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "requirements",
                "agent": "Product Designer Agent",
                "model": member_models.get("Product Designer Agent"),
            },
        ),
        WorkflowNode(
            id="creative-direction",
            type="agent",
            title="Creative Direction",
            description="Shape a simple campaign concept from the product analysis.",
            content=creative_direction,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "script-planning",
                "agent": "Creative Director Agent",
                "model": member_models.get("Creative Director Agent"),
            },
        ),
        WorkflowNode(
            id="script",
            type="agent",
            title="Ad Script",
            description="Create short-form copy for the selected campaign channels.",
            content=script,
            status="completed",
            input_context=_reference_input_context(reference_contexts["script"]),
            metadata={
                **common_metadata,
                "stage": "script-planning",
                "agent": "Script Writer Agent",
                "model": member_models.get("Script Writer Agent"),
            },
        ),
        WorkflowNode(
            id="subtitle-generation",
            type="tool",
            title="Subtitle Generation",
            description="Convert the script into timed subtitle cues and a mock SRT asset.",
            content=subtitle_generation,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "script-planning",
                "tool": "mock-subtitle-generator",
            },
        ),
        WorkflowNode(
            id="character-design",
            type="agent",
            title="Character Design",
            description="Define the appearance and personality of the main character.",
            content=character_design,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "visual-presentation",
                "agent": "Character Designer Agent",
                "model": member_models.get("Character Designer Agent"),
            },
        ),
        WorkflowNode(
            id="scene-design",
            type="agent",
            title="Scene Design",
            description="Define layouts, lighting, and atmosphere for the short film.",
            content=scene_design,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "visual-presentation",
                "agent": "Scene Designer Agent",
                "model": member_models.get("Scene Designer Agent"),
            },
        ),
        WorkflowNode(
            id="character-image-generation",
            type="tool",
            title="Character Turnaround Image Generation",
            description="Generate pure front, side, and back character reference views.",
            content=character_turnaround_images,
            status="completed",
            input_context=_reference_input_context(character_reference_context),
            input_assets=character_reference_input_assets,
            metadata={
                **common_metadata,
                "stage": "visual-presentation",
                "tool": character_turnaround_images["provider"],
            },
        ),
        WorkflowNode(
            id="scene-image-generation",
            type="tool",
            title="Scene Reference Image Generation",
            description="Generate pure scene reference images without people.",
            content=scene_reference_images,
            status="completed",
            input_context=_reference_input_context(scene_reference_context),
            input_assets=scene_reference_input_assets,
            metadata={
                **common_metadata,
                "stage": "visual-presentation",
                "tool": scene_reference_images["provider"],
            },
        ),
        WorkflowNode(
            id="storyboard",
            type="agent",
            title="Storyboard",
            description="Map the script into shots, framing, and dynamic visual effects.",
            content={"scenes": storyboard_scenes},
            status="completed",
            input_context=_reference_input_context(storyboard_reference_context),
            metadata={
                **common_metadata,
                "stage": "visual-presentation",
                "agent": "Storyboard Agent",
                "model": member_models.get("Storyboard Agent"),
            },
        ),
        WorkflowNode(
            id="storyboard-image-generation",
            type="tool",
            title="Storyboard Image Generation",
            description="Generate storyboard image assets from the approved shot plan.",
            content=storyboard_images,
            status="completed",
            input_context=_reference_input_context(storyboard_reference_context),
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "tool": storyboard_images["provider"],
            },
        ),
        WorkflowNode(
            id="final-video-generation-agent",
            type="agent",
            title="Final Video Generation Prompt",
            description="Organize script, storyboard, designs, and image assets into a multimodal video prompt.",
            content=final_video_generation_agent,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "agent": "Final Video Generation Agent",
                "model": member_models.get("Final Video Generation Agent"),
            },
        ),
        WorkflowNode(
            id="storyboard-video-generation",
            type="tool",
            title="Storyboard Video Generation",
            description="Generate formal ordered video segments from each storyboard prompt.",
            content=storyboard_video,
            status="completed",
            input_context=_reference_input_context(storyboard_video_reference_context),
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "tool": storyboard_video["provider"],
            },
        ),
        WorkflowNode(
            id="sound-effects",
            type="agent",
            title="Sound Effects",
            description="Plan non-voice, non-music sound effects aligned to storyboard beats.",
            content=sound_effects_plan,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "agent": "Sound Effects Agent",
                "model": member_models.get("Sound Effects Agent"),
            },
        ),
        WorkflowNode(
            id="voiceover",
            type="agent",
            title="Voiceover / Dubbing",
            description="Plan human voice tracks from subtitle cues without rewriting text.",
            content=voiceover_plan,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "agent": "Voiceover / Dubbing Agent",
                "model": member_models.get("Voiceover / Dubbing Agent"),
            },
        ),
        WorkflowNode(
            id="bgm",
            type="agent",
            title="Background Music",
            description="Plan whole-ad background music without voices or sound effects.",
            content=bgm_plan,
            status="completed",
            input_context=_reference_input_context(bgm_reference_context),
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "agent": "BGM Agent",
                "model": member_models.get("BGM Agent"),
            },
        ),
        WorkflowNode(
            id="audio-generation",
            type="tool",
            title="Audio Generation",
            description="Generate separate sound effects, voiceover, and BGM assets.",
            content=audio_assets,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "tool": audio_assets["provider"],
            },
        ),
        WorkflowNode(
            id="audio-video-sync",
            type="tool",
            title="Audio Video Synchronization",
            description="Align storyboard video transitions with music and sound cues.",
            content=synchronized_video,
            status="completed",
            metadata={
                **common_metadata,
                "stage": "audiovisual-production",
                "tool": synchronized_video["provider"],
            },
        ),
        WorkflowNode(
            id="final-composition",
            type="tool",
            title="Final Video Composition",
            description="Assemble generated assets on an editing timeline without LLM generation.",
            content=final_video,
            status="completed",
            input_context=_reference_input_context(final_reference_context),
            metadata={
                **common_metadata,
                "stage": "post-production",
                "tool": final_video["provider"],
            },
        ),
    ]

    edges = [
        WorkflowEdge(source="requirements-analysis", target="product-design", label="requirements"),
        WorkflowEdge(source="product-design", target="creative-direction", label="product brief"),
        WorkflowEdge(source="creative-direction", target="script", label="concept"),
        WorkflowEdge(source="script", target="subtitle-generation", label="subtitle cues"),
        WorkflowEdge(source="script", target="character-design", label="character brief"),
        WorkflowEdge(source="script", target="scene-design", label="scene brief"),
        WorkflowEdge(
            source="character-design",
            target="character-image-generation",
            label="character specs",
        ),
        WorkflowEdge(
            source="scene-design",
            target="scene-image-generation",
            label="scene specs",
        ),
        WorkflowEdge(
            source="character-image-generation",
            target="storyboard",
            label="character references",
        ),
        WorkflowEdge(
            source="scene-image-generation",
            target="storyboard",
            label="scene references",
        ),
        WorkflowEdge(source="scene-design", target="storyboard", label="scenes"),
        WorkflowEdge(source="storyboard", target="storyboard-image-generation", label="shot plan"),
        WorkflowEdge(
            source="character-image-generation",
            target="storyboard-image-generation",
            label="character references",
        ),
        WorkflowEdge(
            source="scene-image-generation",
            target="storyboard-image-generation",
            label="scene references",
        ),
        WorkflowEdge(
            source="storyboard-image-generation",
            target="storyboard-video-generation",
            label="visual assets",
        ),
        WorkflowEdge(
            source="requirements-analysis",
            target="final-video-generation-agent",
            label="requirements",
        ),
        WorkflowEdge(
            source="creative-direction",
            target="final-video-generation-agent",
            label="creative direction",
        ),
        WorkflowEdge(source="script", target="final-video-generation-agent", label="script"),
        WorkflowEdge(
            source="character-design",
            target="final-video-generation-agent",
            label="characters",
        ),
        WorkflowEdge(
            source="character-image-generation",
            target="final-video-generation-agent",
            label="character turnaround assets",
        ),
        WorkflowEdge(source="scene-design", target="final-video-generation-agent", label="scenes"),
        WorkflowEdge(
            source="scene-image-generation",
            target="final-video-generation-agent",
            label="scene reference assets",
        ),
        WorkflowEdge(
            source="storyboard",
            target="final-video-generation-agent",
            label="storyboard",
        ),
        WorkflowEdge(
            source="storyboard-image-generation",
            target="final-video-generation-agent",
            label="visual assets",
        ),
        WorkflowEdge(
            source="subtitle-generation",
            target="final-video-generation-agent",
            label="subtitles",
        ),
        WorkflowEdge(
            source="final-video-generation-agent",
            target="storyboard-video-generation",
            label="segment prompts",
        ),
        WorkflowEdge(
            source="character-image-generation",
            target="storyboard-video-generation",
            label="character image references",
        ),
        WorkflowEdge(
            source="scene-image-generation",
            target="storyboard-video-generation",
            label="scene image references",
        ),
        WorkflowEdge(
            source="storyboard-image-generation",
            target="storyboard-video-generation",
            label="storyboard image references",
        ),
        WorkflowEdge(source="storyboard", target="sound-effects", label="storyboard cues"),
        WorkflowEdge(source="scene-design", target="sound-effects", label="scene atmosphere"),
        WorkflowEdge(source="subtitle-generation", target="voiceover", label="subtitle cues"),
        WorkflowEdge(source="character-design", target="voiceover", label="voice profiles"),
        WorkflowEdge(source="storyboard", target="voiceover", label="storyboard timing"),
        WorkflowEdge(source="requirements-analysis", target="bgm", label="requirements"),
        WorkflowEdge(source="creative-direction", target="bgm", label="tone"),
        WorkflowEdge(source="script", target="bgm", label="script rhythm"),
        WorkflowEdge(source="storyboard", target="bgm", label="visual rhythm"),
        WorkflowEdge(source="sound-effects", target="audio-generation", label="sound effects"),
        WorkflowEdge(source="voiceover", target="audio-generation", label="voice tracks"),
        WorkflowEdge(source="bgm", target="audio-generation", label="background music"),
        WorkflowEdge(
            source="storyboard-video-generation",
            target="audio-video-sync",
            label="video segments",
        ),
        WorkflowEdge(source="audio-generation", target="audio-video-sync", label="audio assets"),
        WorkflowEdge(
            source="storyboard-video-generation",
            target="final-composition",
            label="ordered video segments",
        ),
        WorkflowEdge(source="audio-video-sync", target="final-composition", label="timed assets"),
    ]

    if skip_audio_agents:
        skipped_node_ids = {
            "sound-effects",
            "voiceover",
            "bgm",
            "audio-generation",
            "audio-video-sync",
        }
        nodes = [node for node in nodes if node.id not in skipped_node_ids]
        edges = [
            edge
            for edge in edges
            if edge.source not in skipped_node_ids and edge.target not in skipped_node_ids
        ]

    nodes = [_frontend_workflow_node(node) for node in nodes]
    return AdWorkflowResponse(workflow_id=workflow_id, nodes=nodes, edges=edges)


def _frontend_workflow_node(node: WorkflowNode) -> WorkflowNode:
    content = with_public_urls(node.content)
    return node.model_copy(
        update={
            "content": content,
            "input_assets": input_assets_from_content(content),
            "output_assets": output_assets_from_content(content),
        }
    )


def create_workflow_id() -> str:
    return f"adwf_{uuid4().hex[:12]}"
