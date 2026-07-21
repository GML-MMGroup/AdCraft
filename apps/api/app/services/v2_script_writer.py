from __future__ import annotations

import json
from hashlib import sha1
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_planning import (
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptScene,
)
from app.schemas.workflow_v2_screenplay import (
    V2EditableScriptDocument,
    V2ScriptPlanV2,
    V2ScriptShotV2,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_screenplay_renderer import V2ScreenplayRenderer
from app.services.v2_skill_context import V2SkillContext, V2SkillContextService
from app.services.v2_script_writer_output import (
    script_writer_output_schema,
    script_writer_system_prompt,
)
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)
from app.services.v2_structured_llm import V2StructuredLLMClient, V2StructuredLLMError
from app.services.v2_generation_integrity import planning_constraints_from_metadata
from app.services.v2_versioning import V2_SCRIPT_WRITER_VERSION


class V2ScriptWriterError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2ScriptWriterQualityError(V2ScriptWriterError):
    def __init__(
        self,
        failures: list[dict[str, Any]],
        message: str | None = None,
    ) -> None:
        super().__init__(
            "script_writer_output_quality_failed",
            message or "Script Writer output failed deterministic quality validation.",
        )
        self.failures = failures
        self.repair_details = {"failures": failures}


class V2ScriptWriterService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._skill_context = V2SkillContextService()
        self._structured_llm = V2StructuredLLMClient(settings)
        self._structured_runtime = StructuredGenerationRuntime(
            settings=settings,
            structured_llm=self._structured_llm,
        )

    def write_script(
        self,
        request: WorkflowV2PlanFromPromptRequest | dict[str, Any],
        *,
        workflow_id: str,
        input_asset_descriptors: list[dict[str, Any]],
        normalized_request: dict[str, Any] | None = None,
        force_mock: bool = False,
    ) -> V2ScriptPlanV2:
        request_model = _coerce_request(request)
        skill_context = self._skill_context.skill_context_for_script_writer()
        payload = self._build_llm_input(
            workflow_id=workflow_id,
            request=request_model,
            input_asset_descriptors=input_asset_descriptors,
            normalized_request=normalized_request,
            skill_context=skill_context,
        )
        if force_mock or self._settings.agno_mock_mode:
            return _with_script_writer_metadata(
                _mock_script_plan(
                    workflow_id=workflow_id,
                    request=request_model,
                    input_asset_descriptors=payload["input_asset_descriptors"],
                ),
                skill_context,
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise V2ScriptWriterError(
                "script_writer_unavailable",
                "LLM API key and base URL are required for V2 Script Writer real mode.",
            )
        try:
            spec = StructuredGenerationSpec[V2ScriptPlanV2](
                stage_name="script_writer",
                contract_name="V2ScriptPlanV2",
                model_id=self._settings.llm_script_model,
                system_prompt=script_writer_system_prompt(),
                input_payload=payload,
                output_model=V2ScriptPlanV2,
                quality_validator=lambda plan: _validate_script_plan_quality(
                    _render_screenplay(plan),
                    request_model,
                ),
                repair_context_builder=_script_writer_repair_context,
                fallback_builder=lambda error: _fallback_script_plan(
                    workflow_id=workflow_id,
                    request=request_model,
                    input_asset_descriptors=payload["input_asset_descriptors"],
                    original_error=error,
                ),
                trace_metadata={"workflow_id": workflow_id},
                temperature=0.4,
            )
            result = self._structured_runtime.run(spec)
            quality_notes: list[str] = []
            if result.mode == "repair":
                quality_notes.append("script_writer_output_repaired")
            if result.mode == "fallback":
                quality_notes.append("script_writer_fallback_used")
            return _with_script_writer_metadata(
                result.output,
                skill_context,
                quality_notes=quality_notes,
                warnings=result.warnings,
            )
        except StructuredGenerationRuntimeError as exc:
            raise V2ScriptWriterError(_script_writer_runtime_error_code(exc), str(exc)) from exc
        except Exception as exc:
            raise V2ScriptWriterError("script_writer_failed", str(exc)) from exc

    def build_deterministic_fallback(
        self,
        request: WorkflowV2PlanFromPromptRequest | dict[str, Any],
        *,
        workflow_id: str,
        input_asset_descriptors: list[dict[str, Any]],
        original_error_code: str,
    ) -> V2ScriptPlanV2:
        request_model = _coerce_request(request)
        skill_context = self._skill_context.skill_context_for_script_writer()
        error = V2StructuredLLMError(
            original_error_code,
            "Script reconciliation required deterministic fallback.",
        )
        plan = _fallback_script_plan(
            workflow_id=workflow_id,
            request=request_model,
            input_asset_descriptors=input_asset_descriptors,
            original_error=error,
        )
        plan = _render_screenplay(plan)
        _validate_script_plan_quality(plan, request_model)
        return _with_script_writer_metadata(
            plan,
            skill_context,
            quality_notes=["script_writer_fallback_used"],
            warnings=[
                {
                    "code": "script_writer_fallback_used",
                    "original_error_code": original_error_code,
                }
            ],
        )

    def normalize_edit_document(
        self,
        selected_script: V2ScriptPlanV2,
        instruction: str,
        *,
        workflow_id: str,
    ) -> V2EditableScriptDocument:
        current_document = _editable_document_from_script(selected_script)
        if self._settings.agno_mock_mode:
            payload = current_document.model_dump(mode="python")
            payload["scenes"][0]["shots"][0]["description"] = instruction
            return V2EditableScriptDocument.model_validate(payload)
        try:
            result = self._structured_llm.generate(
                model_id=self._settings.llm_script_model,
                system_prompt=(
                    "Normalize one user screenplay edit into a complete V2EditableScriptDocument. "
                    "Preserve every unchanged canonical ID and structure. Use client_key only for new "
                    "entities. Do not return script_text, markdown, explanations, workflow metadata, "
                    "provider payloads, or media data."
                ),
                user_payload={
                    "workflow_id": workflow_id,
                    "selected_script_version_id": selected_script.script_version_id,
                    "instruction": instruction,
                    "current_document": current_document.model_dump(mode="json"),
                },
                output_model=V2EditableScriptDocument,
                contract_name="V2EditableScriptDocument",
                temperature=0.2,
                repair_on_failure=True,
                stage_name="script_edit_normalization",
            )
            return V2EditableScriptDocument.model_validate(result.output)
        except Exception as exc:
            raise V2ScriptWriterError(
                "script_edit_normalization_failed",
                "The screenplay edit could not be normalized into the canonical document.",
            ) from exc

    def _build_llm_input(
        self,
        *,
        workflow_id: str,
        request: WorkflowV2PlanFromPromptRequest,
        input_asset_descriptors: list[dict[str, Any]],
        normalized_request: dict[str, Any] | None,
        skill_context: V2SkillContext,
    ) -> dict[str, Any]:
        payload = {
            "workflow_id": workflow_id,
            "task": "Write a complete advertising script plan as valid JSON.",
            "schema": "V2ScriptPlanV2",
            "output_schema": script_writer_output_schema(),
            "request": request.model_dump(mode="json"),
            "front_desk_normalized_request": normalized_request or {},
            "input_asset_descriptors": [
                _lightweight_asset_descriptor(descriptor) for descriptor in input_asset_descriptors
            ],
            "skill_context": skill_context.model_dump(mode="json"),
            "output_requirements": {
                "script_plan_version": 2,
                "must_include_scene_and_shot_structure": True,
                "must_not_template_raw_prompt": True,
                "must_not_include_media_bytes_or_data_urls": True,
                "must_use_skill_context": skill_context.skill_ids,
                "system_language": "English",
                "user_visible_content_language": "May follow user prompt language",
                "visual_style_contract": request.metadata.get("visual_style_contract", {}),
                "preserve_visual_style_contract": True,
                "required_top_level_fields": [
                    "script_plan_version",
                    "script_brief_id",
                    "script_version_id",
                    "language",
                    "script_title",
                    "script_text",
                    "scenes",
                    "shots",
                    "characters",
                    "locations",
                    "product_beats",
                    "tone",
                    "visual_style",
                    "duration_seconds",
                    "aspect_ratio",
                ],
                "canonical_nested_id_fields": [
                    "characters[].character_id",
                    "locations[].location_id",
                    "scenes[].scene_id",
                    "shots[].shot_id",
                    "shots[].scene_id",
                    "shots[].dialogue[].dialogue_id",
                    "shots[].dialogue[].character_id",
                ],
                "forbidden_alias_only_id_fields": [
                    "characters[].id",
                    "locations[].id",
                    "scenes[].id",
                    "shots[].id",
                ],
            },
        }
        return sanitize_context_for_llm_text(payload)


def _coerce_request(
    request: WorkflowV2PlanFromPromptRequest | dict[str, Any],
) -> WorkflowV2PlanFromPromptRequest:
    if isinstance(request, WorkflowV2PlanFromPromptRequest):
        return request
    return WorkflowV2PlanFromPromptRequest.model_validate(request)


def _editable_document_from_script(
    script: V2ScriptPlanV2,
) -> V2EditableScriptDocument:
    shots_by_scene: dict[str, list[dict[str, Any]]] = {}
    for shot in script.shots:
        shots_by_scene.setdefault(shot.scene_id, []).append(
            {
                "shot_id": shot.shot_id,
                "product_ids": list(shot.product_ids),
                "character_ids": list(shot.character_ids),
                "scene_ids": list(shot.scene_ids),
                "description": shot.description,
                "dialogue": [
                    {
                        "dialogue_id": line.dialogue_id,
                        "character_id": line.character_id,
                        "performance_cue": line.performance_cue,
                        "text": line.text,
                    }
                    for line in shot.dialogue
                ],
                "narration": shot.narration,
                "visual_prompt": shot.visual_prompt,
                "duration_seconds": shot.duration_seconds,
            }
        )
    return V2EditableScriptDocument.model_validate(
        {
            "script_title": script.script_title,
            "language": script.language,
            "characters": [
                {
                    "character_id": item.character_id,
                    "display_name": item.display_name,
                    "description": item.description,
                    "role": item.role,
                    "visual_notes": item.visual_notes,
                    "gender": item.gender,
                }
                for item in script.characters
            ],
            "locations": [
                {
                    "location_id": item.location_id,
                    "display_name": item.display_name,
                    "description": item.description,
                    "visual_notes": item.visual_notes,
                    "location_type": item.location_type,
                    "time_of_day": item.time_of_day,
                    "setting_type": item.setting_type,
                }
                for item in script.locations
            ],
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "title": scene.title,
                    "description": scene.description,
                    "location_id": scene.location_id,
                    "location_type": scene.location_type,
                    "time_of_day": scene.time_of_day,
                    "setting_type": scene.setting_type,
                    "shots": shots_by_scene[scene.scene_id],
                }
                for scene in script.scenes
            ],
            "product_beats": list(script.product_beats),
            "tone": script.tone,
            "visual_style": script.visual_style,
            "aspect_ratio": script.aspect_ratio,
        }
    )


def _script_writer_runtime_error_code(exc: StructuredGenerationRuntimeError) -> str:
    if exc.code == "structured_generation_unavailable":
        return "script_writer_unavailable"
    if exc.code == "structured_generation_fallback_failed":
        return "script_writer_fallback_failed"
    if exc.code == "structured_generation_schema_failed":
        return "script_writer_output_schema_invalid"
    if exc.code in {
        "structured_generation_quality_failed",
        "structured_generation_repair_failed",
    }:
        return "script_writer_output_quality_failed"
    return "script_writer_failed"


def _script_writer_repair_context(error: V2StructuredLLMError) -> dict[str, Any]:
    details = error.quality_error_details
    if isinstance(details, dict):
        return dict(details)
    return {}


def _lightweight_asset_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "asset_id",
        "version_id",
        "media_type",
        "semantic_type",
        "display_name",
        "tags",
    }
    cleaned = {key: descriptor.get(key) for key in allowed if descriptor.get(key) is not None}
    public_url = descriptor.get("public_url")
    if isinstance(public_url, str) and _safe_public_url(public_url):
        cleaned["public_url"] = public_url
    if "tags" in cleaned:
        cleaned["tags"] = [str(tag) for tag in cleaned.get("tags") or []]
    return cleaned


def _safe_public_url(value: str) -> bool:
    value = value.strip()
    return bool(value) and not value.startswith("data:") and ";base64," not in value


def _mock_script_plan(
    *,
    workflow_id: str,
    request: WorkflowV2PlanFromPromptRequest,
    input_asset_descriptors: list[dict[str, Any]],
) -> V2ScriptPlanV2:
    product_name = request.product_name or "Product"
    language = "zh" if _contains_cjk(f"{request.prompt} {product_name}") else "en"
    script_brief_id = f"script-brief-{_stable_suffix(workflow_id, request.prompt)}"
    script_version_id = f"script-ver-{_stable_suffix(request.prompt, product_name)}"
    profile = _script_profile(request)
    constraints = planning_constraints_from_metadata(request.metadata)
    scene_count = max(1, (constraints.requested_scene_count if constraints else None) or 1)
    character_count = max(1, (constraints.requested_character_count if constraints else None) or 1)
    shot_count = max(
        1,
        (constraints.requested_shot_count if constraints else None)
        or request.requested_shot_count
        or 3,
    )
    scene_styles = list(constraints.requested_scene_styles if constraints else [])
    shot_duration = max(1, request.duration_seconds // shot_count)
    explicit_visual_style = _explicit_visual_style(request)
    if language == "zh":
        title = f"{product_name} 广告脚本"
        tone = "清新、有节奏、可信赖"
        visual_style = explicit_visual_style or profile["visual_style_zh"]
        character_description = profile["character_zh"]
        location_description = profile["location_zh"]
    else:
        title = f"{product_name} commercial script"
        tone = profile["tone_en"]
        visual_style = explicit_visual_style or profile["visual_style_en"]
        character_description = profile["character_en"]
        location_description = profile["location_en"]
    scenes: list[V2ScriptScene] = []
    locations: list[V2ScriptLocation] = []
    shots: list[V2ScriptShotV2] = []
    scene_assignments = _scene_assignments(shot_count, scene_count)
    for index in range(1, scene_count + 1):
        style = scene_styles[index - 1] if index <= len(scene_styles) else None
        scene_id = f"scene-{index}"
        location_id = f"location-{index}"
        scene_shot_ids = [
            f"shot-{shot_index}"
            for shot_index, assigned_scene in enumerate(scene_assignments, start=1)
            if assigned_scene == index
        ]
        scene_description = _scene_description(
            profile,
            product_name=product_name,
            index=index,
            style=style,
            language=language,
            fallback=location_description,
        )
        scenes.append(
            V2ScriptScene(
                scene_id=scene_id,
                title=_scene_title(index, style, language),
                description=scene_description,
                location_id=location_id,
                shot_ids=scene_shot_ids,
                duration_seconds=max(1, request.duration_seconds // scene_count),
            )
        )
        locations.append(
            V2ScriptLocation(
                location_id=location_id,
                display_name=_scene_title(index, style, language),
                description=scene_description,
                visual_notes=_scene_visual_notes(visual_style, style),
            )
        )
    for index, assigned_scene in enumerate(scene_assignments, start=1):
        style = scene_styles[assigned_scene - 1] if assigned_scene <= len(scene_styles) else None
        shots.append(
            V2ScriptShotV2(
                shot_id=f"shot-{index}",
                scene_id=f"scene-{assigned_scene}",
                shot_index=index,
                scene_ids=[f"scene-{assigned_scene}"],
                reference_item_ids=[f"scene-{assigned_scene}"],
                description=_shot_description(profile, index=index, style=style),
                dialogue=[],
                visual_prompt=_shot_visual(profile, product_name, index=index, style=style),
                duration_seconds=max(
                    1,
                    request.duration_seconds - shot_duration * (shot_count - 1)
                    if index == shot_count
                    else shot_duration,
                ),
            )
        )
    scenes = [
        scene.model_copy(
            update={
                "duration_seconds": sum(
                    shot.duration_seconds for shot in shots if shot.scene_id == scene.scene_id
                )
            },
            deep=True,
        )
        for scene in scenes
    ]
    asset_warning = (
        [
            {
                "code": "script_writer_input_assets_summarized",
                "message": "Input assets were passed as lightweight descriptors only.",
            }
        ]
        if input_asset_descriptors
        else []
    )
    return _render_screenplay(
        V2ScriptPlanV2(
            script_brief_id=script_brief_id,
            script_version_id=script_version_id,
            language=language,
            script_title=title,
            script_text="",
            scenes=scenes,
            shots=shots,
            characters=_characters(
                count=character_count,
                language=language,
                description=character_description,
            ),
            locations=locations,
            product_beats=[
                profile["beat_1"],
                profile["beat_2"],
                profile["beat_3"],
            ],
            tone=tone,
            visual_style=visual_style,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            materializer_mode="mock",
            model_id="deterministic-v2-script-writer",
            warnings=asset_warning,
        )
    )


def _fallback_script_plan(
    *,
    workflow_id: str,
    request: WorkflowV2PlanFromPromptRequest,
    input_asset_descriptors: list[dict[str, Any]],
    original_error: V2StructuredLLMError,
) -> V2ScriptPlanV2:
    plan = _mock_script_plan(
        workflow_id=workflow_id,
        request=request,
        input_asset_descriptors=input_asset_descriptors,
    )
    warning = {
        "code": "script_writer_fallback_used",
        "message": "Real Script Writer output failed validation; deterministic script fallback was used.",
        "original_error_code": original_error.code,
        "original_error_message": str(original_error)[:500],
    }
    return plan.model_copy(update={"warnings": [*plan.warnings, warning]}, deep=True)


def _scene_assignments(shot_count: int, scene_count: int) -> list[int]:
    return [
        min(scene_count, ((index - 1) * scene_count // shot_count) + 1)
        for index in range(1, shot_count + 1)
    ]


def _scene_title(index: int, style: str | None, language: str) -> str:
    if style:
        return f"{style.title()} Scene" if language == "en" else f"{style.title()} 场景"
    return f"Scene {index}" if language == "en" else f"场景 {index}"


def _scene_description(
    profile: dict[str, str],
    *,
    product_name: str,
    index: int,
    style: str | None,
    language: str,
    fallback: str,
) -> str:
    if style:
        style_text = style.replace("_", " ")
        style_detail = _style_scene_detail(style)
        if language == "zh":
            return (
                f"{style_text.title()} style environment for {product_name}, "
                f"{style_detail} Preserves the requested scene variety."
            )
        return (
            f"{style_text.title()} style environment for {product_name}, preserving the requested "
            f"scene variety with clean commercial readability. {style_detail}"
        )
    if index == 1:
        return profile["scene_zh"] if language == "zh" else profile["scene_en"]
    return fallback


def _scene_visual_notes(visual_style: str, style: str | None) -> str:
    if not style:
        return visual_style
    return f"{visual_style}; requested {style} scene style."


def _explicit_visual_style(request: WorkflowV2PlanFromPromptRequest) -> str | None:
    contract = request.metadata.get("visual_style_contract")
    if not isinstance(contract, dict):
        return None
    if contract.get("source") not in {"explicit_user", "inferred"}:
        return None
    style_prompt = contract.get("style_prompt")
    if not isinstance(style_prompt, str):
        return None
    normalized = style_prompt.strip()
    return normalized or None


def _style_scene_detail(style: str) -> str:
    details = {
        "urban": "Architecture, pavement texture, storefront light, and layered city depth.",
        "nature": "Natural terrain, organic foliage, open sky, and calm outdoor depth.",
        "street": "Street surface, building edges, signage shapes, and practical light pools.",
        "city": "Architecture, skyline hints, reflective surfaces, and urban material contrast.",
        "forest": "Tree canopy, ground texture, filtered light, and organic spatial layers.",
        "beach": "Sand texture, horizon line, coastal light, and open-air spatial rhythm.",
    }
    return details.get(style, f"Distinct {style} environment materials and spatial rhythm.")


def _shot_description(profile: dict[str, str], *, index: int, style: str | None) -> str:
    key = f"shot_{min(index, 3)}_description"
    description = profile.get(key) or f"Storyboard beat {index}."
    if style:
        return f"{description} Scene style: {style}."
    return description


def _shot_visual(
    profile: dict[str, str],
    product_name: str,
    *,
    index: int,
    style: str | None,
) -> str:
    key = f"shot_{min(index, 3)}_visual"
    visual = profile.get(key) or f"Show {product_name} in a clear commercial storyboard beat."
    if style:
        return f"{visual} Environment style: {style}."
    return visual


def _characters(
    *,
    count: int,
    language: str,
    description: str,
) -> list[V2ScriptCharacter]:
    if count == 2 and language == "en":
        names = [
            (
                "character-1",
                "Lead Man",
                "lead male customer",
                f"{description} Male lead with calm confidence and precise product curiosity.",
            ),
            (
                "character-2",
                "Lead Woman",
                "lead female customer",
                f"{description} Female lead with warm expressiveness and decisive lifestyle energy.",
            ),
        ]
    else:
        names = [
            (
                f"character-{index}",
                f"Character {index}" if language == "en" else f"角色 {index}",
                "lead customer" if index == 1 else "supporting customer",
                _character_description_for_index(description, index=index),
            )
            for index in range(1, count + 1)
        ]
    return [
        V2ScriptCharacter(
            character_id=character_id,
            display_name=display_name,
            description=character_description,
            role=role,
            visual_notes=_character_visual_notes_for_index(index=index),
        )
        for index, (character_id, display_name, role, character_description) in enumerate(
            names[:count], start=1
        )
    ]


def _character_description_for_index(
    description: str,
    *,
    index: int,
) -> str:
    if index == 1:
        return f"{description} Leads the product discovery and establishes the primary emotional response."
    return f"{description} Provides a distinct supporting perspective and confirms the product benefit in use."


def _character_visual_notes_for_index(*, index: int) -> str:
    if index == 1:
        return "Natural lead styling, focused expression, and clear commercial identity continuity."
    return "Supporting wardrobe contrast, warm responsive expression, and distinct silhouette continuity."


def _script_profile(request: WorkflowV2PlanFromPromptRequest) -> dict[str, str]:
    product_name = request.product_name or "Product"
    prompt = request.prompt.lower()
    product = product_name.lower()
    if "iphone" in prompt or "iphone" in product or "14 pro" in prompt or "14 pro" in product:
        return {
            "tone_en": "premium, cinematic, travel-ready",
            "visual_style_en": "night lifestyle cinematography with crisp product hero lighting",
            "scene_en": (
                f"A traveler moves through a low-light city night with {product_name} visible, "
                "linking premium design, camera confidence, and everyday benefit."
            ),
            "shot_1_en": f"Hero close-up reveals {product_name} design details and screen identity.",
            "shot_2_en": "The lead user captures a low-light travel moment with confident camera clarity.",
            "shot_3_en": "End on a polished product hero and benefit line about capturing life anywhere.",
            "character_en": (
                "A style-conscious traveler whose reactions show confidence, discovery, and delight."
            ),
            "location_en": (
                "A night city street and travel walkway with reflective light, readable product surfaces, "
                "and clear camera-use blocking zones."
            ),
            "beat_1": f"Show {product_name} premium design and recognizable product identity.",
            "beat_2": "Demonstrate camera confidence in low-light night travel and lifestyle use.",
            "beat_3": "Close with product hero benefit: capture important moments anywhere.",
            "shot_1_description": "Premium design and product identity opening beat.",
            "shot_1_visual": f"Macro hero of {product_name} design, screen, and camera module under city light.",
            "shot_2_description": "Low-light camera usage and user benefit beat.",
            "shot_2_visual": "Traveler frames a night street moment, showing camera clarity and lifestyle energy.",
            "shot_3_description": "Final product hero and user benefit beat.",
            "shot_3_visual": f"Polished {product_name} hero shot with confident benefit-focused end frame.",
            "visual_style_zh": "夜景生活方式摄影、产品英雄光、镜头清晰",
            "scene_zh": f"用户在低光城市夜景中使用 {product_name}，串联设计质感、相机能力和生活收益。",
            "shot_1_zh": f"{product_name} 设计细节和屏幕识别度的产品英雄开场。",
            "shot_2_zh": "用户拍摄低光旅行瞬间，突出相机清晰度和可信赖体验。",
            "shot_3_zh": "以产品英雄画面和“随时记录重要瞬间”的收益收束。",
            "character_zh": "有审美的旅行用户，反应自信、自然、有探索感。",
            "location_zh": "有反射光和街景层次的夜间城市步道，适合展示手机拍摄动作。",
        }
    return {
        "tone_en": "fresh, energetic, credible",
        "visual_style_en": "bright natural light, clear product visibility, authentic interaction",
        "scene_en": (
            f"Open on {product_name} in a product-led lifestyle moment that makes the "
            "main usage context and benefit easy to understand."
        ),
        "shot_1_en": f"Establish {product_name} identity and the situation where it matters.",
        "shot_2_en": f"Show the lead user interacting with {product_name} and one concrete benefit.",
        "shot_3_en": f"Close with a memorable {product_name} hero and concise call to action.",
        "character_en": "A relatable lead customer with natural movement and credible enthusiasm.",
        "location_en": "A clean lifestyle setting that supports product visibility and user action.",
        "beat_1": f"Introduce {product_name} with clear identity and usage context.",
        "beat_2": f"Show a concrete {product_name} benefit through user action.",
        "beat_3": f"Finish with a memorable {product_name} product hero.",
        "shot_1_description": "Product identity and context opening beat.",
        "shot_1_visual": f"Show {product_name} clearly in the opening frame with its usage context.",
        "shot_2_description": "Human usage and concrete benefit beat.",
        "shot_2_visual": f"Show the lead character interacting naturally with {product_name}.",
        "shot_3_description": "Closing hero and call-to-action beat.",
        "shot_3_visual": f"End on a polished hero view of {product_name}.",
        "visual_style_zh": "明亮自然光、产品清晰、人物互动真实",
        "scene_zh": f"以产品主导的生活方式场景展示 {product_name} 的使用环境和核心收益。",
        "shot_1_zh": f"{product_name} 清晰进入画面，建立产品识别和使用情境。",
        "shot_2_zh": f"主角自然使用 {product_name}，突出一个具体收益。",
        "shot_3_zh": f"以 {product_name} 产品英雄画面和简洁行动号召收束。",
        "character_zh": "热情、真实的目标用户代表，动作自然，表情可信。",
        "location_zh": "明亮、干净、适合产品展示和生活方式叙事的主场景。",
    }


def _with_script_writer_metadata(
    plan: V2ScriptPlanV2,
    skill_context: V2SkillContext,
    *,
    quality_notes: list[str] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> V2ScriptPlanV2:
    plan = _render_screenplay(plan)
    existing_quality_notes = list(plan.quality_notes)
    merged_quality_notes = [
        *existing_quality_notes,
        "script_plan_contains_scene_and_shot_structure",
        "script_plan_not_raw_prompt_wrapper",
        *(quality_notes or []),
    ]
    merged_warnings = [*plan.warnings, *(warnings or [])]
    return plan.model_copy(
        update={
            "selected_skill_ids": list(skill_context.skill_ids),
            "selected_skill_paths": list(skill_context.source_paths),
            "skill_context_warnings": list(skill_context.warnings),
            "quality_notes": _dedupe_strings(merged_quality_notes),
            "materializer_version": V2_SCRIPT_WRITER_VERSION,
            "warnings": _dedupe_warnings(merged_warnings),
        },
        deep=True,
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_warnings(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _validate_script_plan_quality(
    plan: V2ScriptPlanV2,
    request: WorkflowV2PlanFromPromptRequest,
) -> None:
    raw_prompt = request.prompt.strip()
    product_name = request.product_name or "Product"
    failures: list[dict[str, Any]] = []
    prompt_norm = _normalize_quality_text(raw_prompt)
    script_norm = _normalize_quality_text(plan.script_text)
    wrapper_norm = _normalize_quality_text(
        f"{request.duration_seconds}s ad script for {product_name}: {raw_prompt}"
    )
    if script_norm in {prompt_norm, wrapper_norm} or (
        prompt_norm and prompt_norm in script_norm and len(script_norm) <= len(prompt_norm) + 80
    ):
        failures.append(
            {
                "code": "script_writer_raw_prompt_echo",
                "field": "script_text",
                "message": "script_text is a raw user prompt echo or title-prefixed prompt wrapper.",
            }
        )
    scene_text = " ".join(scene.description for scene in plan.scenes).strip()
    shot_text = " ".join(f"{shot.description} {shot.visual_prompt}" for shot in plan.shots).strip()
    if not scene_text or not shot_text or len(scene_text) < 24 or len(shot_text) < 40:
        failures.append(
            {
                "code": "script_writer_scene_or_shot_content_missing",
                "field": "scenes/shots",
                "message": "Script plan needs concrete scene and shot narrative content.",
            }
        )
    if _normalize_quality_text(scene_text) in {
        prompt_norm,
        _normalize_quality_text(product_name),
    } or _normalize_quality_text(shot_text) in {
        prompt_norm,
        _normalize_quality_text(product_name),
    }:
        failures.append(
            {
                "code": "script_writer_scene_or_shot_too_shallow",
                "field": "scenes/shots",
                "message": "Scene or shot content is too shallow for storyboard planning.",
            }
        )
    beat_text = " ".join(plan.product_beats)
    product_tokens = _quality_tokens(product_name)
    if len(plan.product_beats) < 2 or (
        product_tokens
        and not any(token in _normalize_quality_text(beat_text) for token in product_tokens)
    ):
        failures.append(
            {
                "code": "script_writer_product_beats_generic",
                "field": "product_beats",
                "message": "Product beats must include product-specific selling points.",
            }
        )
    duration_sum = sum(shot.duration_seconds for shot in plan.shots)
    tolerance = max(2, int(request.duration_seconds * 0.35))
    if abs(duration_sum - request.duration_seconds) > tolerance:
        failures.append(
            {
                "code": "script_writer_shot_duration_mismatch",
                "field": "shots.duration_seconds",
                "message": "Shot durations must approximately match requested duration.",
                "requested_duration_seconds": request.duration_seconds,
                "actual_duration_seconds": duration_sum,
            }
        )
    combined = _normalize_quality_text(
        " ".join(
            [
                plan.script_title,
                plan.script_text,
                scene_text,
                shot_text,
                beat_text,
                plan.visual_style,
                plan.tone,
            ]
        )
    )
    if _is_iphone_request(request):
        required_groups = {
            "design": {"design", "titanium", "screen", "identity"},
            "camera": {"camera", "photo", "video", "capture"},
            "low_light_or_lifestyle": {
                "low-light",
                "low light",
                "night",
                "travel",
                "lifestyle",
            },
            "hero_or_benefit": {"hero", "benefit", "confidence", "anywhere"},
        }
        missing = [
            group
            for group, terms in required_groups.items()
            if not any(term in combined for term in terms)
        ]
        if missing:
            failures.append(
                {
                    "code": "script_writer_iphone_beats_missing",
                    "field": "script_plan",
                    "message": "iPhone scripts must include design, camera, low-light/lifestyle, and hero benefit beats.",
                    "missing_beats": missing,
                }
            )
    if failures:
        raise V2ScriptWriterQualityError(failures)


def _render_screenplay(plan: V2ScriptPlanV2) -> V2ScriptPlanV2:
    return V2ScreenplayRenderer().rendered_plan(plan)


def _normalize_quality_text(value: str) -> str:
    return " ".join(value.lower().split())


def _quality_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_quality_text(value).replace("-", " ").split()
        if len(token) >= 3
    }


def _is_iphone_request(request: WorkflowV2PlanFromPromptRequest) -> bool:
    text = _normalize_quality_text(f"{request.product_name or ''} {request.prompt}")
    return "iphone" in text or "14 pro" in text


def _stable_suffix(*values: str) -> str:
    return sha1("|".join(values).encode("utf-8")).hexdigest()[:10]


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)
