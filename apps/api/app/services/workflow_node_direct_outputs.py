import json
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.agent_outputs import (
    BgmOutput,
    CharacterDesignOutput,
    SceneDesignOutput,
    ScriptOutput,
    StoryboardOutput,
)
from app.schemas.workflow_nodes import WorkflowNodeRunRequest
from app.services.script_beats import build_default_script_beats
from app.services.workflow_graph import load_graph
from app.services.workflow_node_errors import WorkflowNodeInputError
from app.services.workflow_node_media_generators import scene_design_from_provider_prompt


def _ad_request_for_direct_node(
    request: WorkflowNodeRunRequest,
    workflow_id: str,
    settings: Settings,
) -> AdWorkflowGenerateRequest:
    graph = load_graph(settings.media_data_dir, workflow_id) if workflow_id else None
    if graph is not None and graph.ad_request:
        return _validate_ad_request_mapping(graph.ad_request, workflow_id, "workflow graph")
    return _validate_ad_request_mapping(
        _ad_request_payload_from_context(request.input_context),
        workflow_id,
        "node input_context",
    )


def _validate_ad_request_mapping(
    raw_ad_request: Any,
    workflow_id: str,
    source: str,
) -> AdWorkflowGenerateRequest:
    try:
        return AdWorkflowGenerateRequest.model_validate(raw_ad_request)
    except ValidationError as exc:
        raise WorkflowNodeInputError(
            f"invalid_ad_request: {source} for {workflow_id} cannot run deterministic node. {exc}"
        ) from exc


def _ad_request_payload_from_context(context: dict[str, Any]) -> dict[str, Any]:
    requirements = context.get("requirements")
    if not isinstance(requirements, dict):
        requirements = context
    product_name = str(requirements.get("product") or requirements.get("product_name") or "Product")
    product_description = str(
        requirements.get("product_description")
        or requirements.get("core_selling_point")
        or "Product description"
    )
    return {
        "product_name": product_name,
        "product_description": product_description,
        "core_selling_point": requirements.get("core_selling_point"),
        "target_audience": requirements.get("target_audience") or "Target audience",
        "campaign_goal": requirements.get("campaign_goal") or "Increase qualified interest",
        "desired_emotion": requirements.get("desired_emotion") or "confident",
        "duration_seconds": int(requirements.get("duration_seconds") or 30),
        "visual_style": requirements.get("visual_style"),
        "references": requirements.get("references") or [],
        "channels": requirements.get("channels") or ["social"],
        "audio_mode": requirements.get("audio_mode") or "bgm_only",
        "output_resolution": requirements.get("output_resolution"),
        "aspect_ratio": requirements.get("aspect_ratio"),
    }


def _requirements_analysis_output(
    request: WorkflowNodeRunRequest,
    workflow_id: str,
    settings: Settings,
) -> dict[str, Any]:
    raw_requirements = request.input_context.get("requirements")
    if not isinstance(raw_requirements, dict) or not raw_requirements:
        graph = load_graph(settings.media_data_dir, workflow_id)
        raw_requirements = graph.ad_request if graph is not None else {}
    if not isinstance(raw_requirements, dict) or not raw_requirements:
        raise WorkflowNodeInputError("missing required input: requirements")
    return _requirements_output_from_mapping(raw_requirements)


def _requirements_output_from_mapping(requirements: dict[str, Any]) -> dict[str, Any]:
    product_name = str(requirements.get("product") or requirements.get("product_name") or "Product")
    product_description = str(requirements.get("product_description") or "")
    return {
        "product": product_name,
        "core_selling_point": requirements.get("core_selling_point")
        or product_description
        or "Clear product benefit",
        "target_audience": requirements.get("target_audience") or "Target audience",
        "campaign_goal": requirements.get("campaign_goal") or "Increase qualified interest",
        "desired_emotion": requirements.get("desired_emotion") or "confident",
        "duration_seconds": int(requirements.get("duration_seconds") or 30),
        "visual_style": requirements.get("visual_style") or "brand-aligned commercial style",
        "references": requirements.get("references") or [],
        "selected_assets": requirements.get("selected_assets") or [],
    }


def _mock_agent_output(
    node_type: str, context: dict[str, Any], override_prompt: str | None
) -> dict[str, Any]:
    if node_type == "script":
        requirements = context.get("requirements")
        if not isinstance(requirements, dict) or not requirements:
            requirements = context.get("ad_request")
        if not isinstance(requirements, dict) or not requirements:
            director_context = context.get("director_context")
            if isinstance(director_context, dict):
                requirements = director_context.get("ad_request") or director_context.get(
                    "strategy"
                )
        if not isinstance(requirements, dict) or not requirements:
            raise WorkflowNodeInputError("missing required input: requirements")
        product_name = str(
            requirements.get("product") or requirements.get("product_name") or "Product"
        )
        desired_emotion = str(requirements.get("desired_emotion") or "confident")
        duration_seconds = int(requirements.get("duration_seconds") or 30)
        shot_beats = build_default_script_beats(
            product_name=product_name,
            desired_emotion=desired_emotion,
            duration_seconds=duration_seconds,
            target_audience=str(requirements.get("target_audience") or ""),
            campaign_goal=str(requirements.get("campaign_goal") or ""),
        )
        output = {
            "hook": f"Meet {product_name}, built for a clearer moment.",
            "body": f"Show the core benefit with a {desired_emotion} rhythm.",
            "cta": f"Try {product_name} today.",
            "structure": [beat["scene_intent"] for beat in shot_beats],
            "script_structure": [beat["scene_intent"] for beat in shot_beats],
            "subtitle_lines": [beat["spoken_or_on_screen_text"] for beat in shot_beats],
            "duration_seconds": duration_seconds,
            "shot_beats": shot_beats,
            "beats": shot_beats,
            "script_beats": shot_beats,
        }
        return ScriptOutput.model_validate(output).model_dump()
    if node_type == "character-design":
        appearance = _task_with_override(
            "Brand-aligned main character matching the target audience.",
            override_prompt,
        )
        return CharacterDesignOutput.model_validate(
            {
                "characters": [
                    {
                        "name": "Audience Representative",
                        "role": "Main character",
                        "appearance": appearance,
                        "personality": "Approachable, expressive, and consistent.",
                    }
                ]
            }
        ).model_dump()
    if node_type == "scene-design":
        script = context.get("script") if isinstance(context.get("script"), dict) else {}
        provider_prompt = _task_with_override("Brand-safe commercial atmosphere.", override_prompt)
        return SceneDesignOutput.model_validate(
            scene_design_from_provider_prompt(
                provider_prompt,
                {"script": script, "provider_prompt": provider_prompt},
            )
        ).model_dump()
    if node_type == "storyboard":
        script = context["script"]
        duration_seconds = int(script.get("duration_seconds") or 30)
        scenes = []
        for index, duration in enumerate(_segment_durations(duration_seconds), start=1):
            scenes.append(
                {
                    "order": index,
                    "scene_id": f"scene-{index}",
                    "shot": "wide shot" if index == 1 else "product close-up",
                    "visual": f"Storyboard beat {index} for the campaign.",
                    "text": _script_line(script, index),
                    "duration_seconds": duration,
                    "camera": "smooth commercial camera movement",
                    "action": _task_with_override(
                        "Show the planned action clearly.", override_prompt
                    ),
                    "input_asset_ids": [],
                }
            )
        return StoryboardOutput.model_validate({"scenes": scenes}).model_dump()
    raise WorkflowNodeInputError(f"unsupported agent node_type: {node_type}")


def _product_design_output(
    request: AdWorkflowGenerateRequest,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    selling_point = request.core_selling_point or request.product_description
    return {
        "showcase_focus": selling_point,
        "presentation_strategy": (
            f"Present {request.product_name} as a clear solution for {request.target_audience}."
        ),
        "channels": request.channels,
        "requirements": requirements,
    }


def _creative_direction_output(
    request: AdWorkflowGenerateRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "concept": f"Show how {request.product_name} helps {request.target_audience}.",
        "key_message": f"{request.product_name}: a practical answer to a real need.",
        "tone": request.desired_emotion,
        "channels": request.channels,
        "requirements": context.get("requirements", {}),
        "product_design": context.get("product_design", {}),
    }


def _bgm_output(
    request: AdWorkflowGenerateRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    base_prompt = (
        f"Generate {request.desired_emotion} background music for a "
        f"{request.duration_seconds}-second ad with no voices and no sound effects."
    )
    override_prompt = context.get("override_prompt")
    override_text = str(override_prompt) if override_prompt else None
    payload = {
        "music_style": "brand-safe commercial background music",
        "mood": request.desired_emotion,
        "tempo": "medium",
        "instruments": ["soft synth", "light percussion", "warm pad"],
        "structure": ["intro hook", "product showcase lift", "CTA resolution"],
        "start_time": "00:00:00,000",
        "end_time": f"00:00:{request.duration_seconds:02},000",
        "fade_in": "00:00:01,000",
        "fade_out": "00:00:02,000",
        "generation_prompt": _task_with_override(base_prompt, override_text),
        "sync_notes": "Keep room for visuals and align lifts to visual transitions.",
        "requirements": context.get("requirements", {}),
        "creative_direction": context.get("creative_direction", {}),
        "script": context.get("script", {}),
    }
    return BgmOutput.model_validate(payload).model_dump()


def _task_with_override(task: str, override_prompt: str | None) -> str:
    if not override_prompt:
        return task
    return f"{task} Additional node prompt constraints: {override_prompt}"


def _with_override_in_character_design(
    character_design: dict[str, Any], override_prompt: str | None
) -> dict[str, Any]:
    if not override_prompt:
        return character_design
    updated = json.loads(json.dumps(character_design, ensure_ascii=False))
    for character in updated.get("characters", []):
        if isinstance(character, dict):
            character["appearance"] = _task_with_override(
                str(character.get("appearance") or ""), override_prompt
            )
    return updated


def _with_override_in_scene_design(
    scene_design: dict[str, Any], override_prompt: str | None
) -> dict[str, Any]:
    if not override_prompt:
        return scene_design
    updated = json.loads(json.dumps(scene_design, ensure_ascii=False))
    for scene in updated.get("scenes", []):
        if isinstance(scene, dict):
            scene["atmosphere"] = _task_with_override(
                str(scene.get("atmosphere") or ""), override_prompt
            )
    return updated


def _with_override_in_storyboard_scenes(
    scenes: list[dict[str, Any]], override_prompt: str | None
) -> list[dict[str, Any]]:
    if not override_prompt:
        return scenes
    updated = json.loads(json.dumps(scenes, ensure_ascii=False))
    for scene in updated:
        scene["action"] = _task_with_override(str(scene.get("action") or ""), override_prompt)
    return updated


def _storyboard_scenes(context: dict[str, Any]) -> list[dict[str, Any]]:
    storyboard = context.get("storyboard", {})
    scenes = storyboard.get("scenes") if isinstance(storyboard, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise WorkflowNodeInputError("missing required input: storyboard.scenes")
    return [scene for scene in scenes if isinstance(scene, dict)]


def _segment_durations(duration_seconds: int) -> list[int]:
    if duration_seconds <= 10:
        return [duration_seconds]
    count, remainder = divmod(duration_seconds, 10)
    durations = [10] * count
    if remainder:
        durations.append(remainder)
    return durations


def _script_line(script: dict[str, Any], index: int) -> str:
    lines = script.get("subtitle_lines")
    if isinstance(lines, list) and lines:
        return str(lines[min(index - 1, len(lines) - 1)])
    return str(script.get("hook") or script.get("body") or script.get("cta") or "")


ad_request_for_direct_node = _ad_request_for_direct_node
validate_ad_request_mapping = _validate_ad_request_mapping
ad_request_payload_from_context = _ad_request_payload_from_context
requirements_analysis_output = _requirements_analysis_output
requirements_output_from_mapping = _requirements_output_from_mapping
mock_agent_output = _mock_agent_output
product_design_output = _product_design_output
creative_direction_output = _creative_direction_output
bgm_output = _bgm_output
task_with_override = _task_with_override
with_override_in_character_design = _with_override_in_character_design
with_override_in_scene_design = _with_override_in_scene_design
with_override_in_storyboard_scenes = _with_override_in_storyboard_scenes
storyboard_scenes = _storyboard_scenes
