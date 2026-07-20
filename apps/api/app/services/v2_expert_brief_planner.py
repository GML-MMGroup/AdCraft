from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_expert_brief_contracts import (
    V2ExpertBriefInputAssetDescriptor,
    V2ExpertBriefPlannerInput,
    V2ExpertBriefPlannerOutput,
)
from app.schemas.workflow_v2_planning import (
    V2BgmBrief,
    V2CharacterBrief,
    V2ExpertBriefPlan,
    V2ProductBrief,
    V2SceneBrief,
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptPlan,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_expert_brief_quality import (
    V2ExpertBriefQualityService,
)
from app.services.v2_skill_context import V2SkillContextService
from app.services.v2_specialist_asset_prompt_quality import (
    V2SpecialistAssetPromptQualityError,
    V2SpecialistAssetPromptQualityValidator,
    V2SpecialistQualityViolation,
    specialist_quality_audit,
)
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)
from app.services.v2_structured_llm import V2StructuredLLMClient, V2StructuredLLMError
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_script_persistence import V2ScriptPersistenceAdapter
from app.services.v2_versioning import V2_EXPERT_BRIEF_BUILDER_VERSION
from app.schemas.workflow_v2_screenplay import (
    V2ScriptPlanV2,
    V2SpecialistHandoffContext,
)


class V2ExpertBriefPlannerError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2ExpertBriefPlanner:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        quality: V2ExpertBriefQualityService | None = None,
        specialist_quality: V2SpecialistAssetPromptQualityValidator | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._skill_context = V2SkillContextService()
        self._quality = quality or V2ExpertBriefQualityService()
        self._specialist_quality = specialist_quality or V2SpecialistAssetPromptQualityValidator()
        self._structured_llm = V2StructuredLLMClient(self._settings)
        self._structured_runtime = StructuredGenerationRuntime(
            settings=self._settings,
            structured_llm=self._structured_llm,
        )

    def plan_briefs(
        self,
        script_plan: V2ScriptPlan | V2ScriptPlanV2,
        request: WorkflowV2PlanFromPromptRequest,
        workflow_id: str,
        input_asset_descriptors: list[dict[str, Any] | V2ExpertBriefInputAssetDescriptor],
        normalized_request: dict[str, Any] | None = None,
        force_mock: bool = False,
        specialist_handoffs: list[V2SpecialistHandoffContext] | None = None,
    ) -> V2ExpertBriefPlan:
        script_plan = _canonical_script_plan(script_plan)
        if force_mock or self._settings.agno_mock_mode:
            plan = self._deterministic_plan(script_plan, request)
            self._validate_plan(plan, script_plan=script_plan, request=request)
            return _with_specialist_quality_audit(
                plan,
                status="passed",
                repair_used=False,
                fallback_used=False,
                violations=[],
            )
        return self._real_plan(
            script_plan,
            request,
            workflow_id=workflow_id,
            input_asset_descriptors=input_asset_descriptors,
            normalized_request=normalized_request,
            specialist_handoffs=specialist_handoffs or [],
        )

    def _real_plan(
        self,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        workflow_id: str,
        input_asset_descriptors: list[dict[str, Any] | V2ExpertBriefInputAssetDescriptor],
        normalized_request: dict[str, Any] | None,
        specialist_handoffs: list[V2SpecialistHandoffContext],
    ) -> V2ExpertBriefPlan:
        planner_input = V2ExpertBriefPlannerInput(
            workflow_id=workflow_id,
            script_plan=script_plan,
            request=request,
            input_asset_descriptors=[
                _coerce_input_asset_descriptor(descriptor) for descriptor in input_asset_descriptors
            ],
            normalized_request=normalized_request or {},
            specialist_handoffs=specialist_handoffs,
        )
        spec = StructuredGenerationSpec[V2ExpertBriefPlannerOutput](
            stage_name="expert_brief_planner",
            contract_name="V2ExpertBriefPlannerOutput",
            model_id=self._settings.llm_creative_model,
            system_prompt=_system_prompt(),
            input_payload=_planner_payload(planner_input),
            output_model=V2ExpertBriefPlannerOutput,
            quality_validator=lambda output: self._validate_plan(
                output.to_plan(),
                script_plan=script_plan,
                request=request,
            ),
            repair_context_builder=_expert_brief_repair_context,
            fallback_builder=lambda error: _output_from_plan(
                self._fallback_plan(
                    script_plan,
                    request,
                    original_error=error,
                )
            ),
            trace_metadata={"workflow_id": workflow_id},
            temperature=0.35,
        )
        try:
            result = self._structured_runtime.run(spec)
        except StructuredGenerationRuntimeError as exc:
            raise V2ExpertBriefPlannerError(
                _planner_runtime_error_code(exc),
                str(exc),
            ) from exc
        plan = result.output.to_plan()
        self._validate_plan(plan, script_plan=script_plan, request=request)
        violations = _specialist_violations_from_quality_errors(result.sanitized_quality_errors)
        plan = _with_specialist_quality_audit(
            plan,
            status=_specialist_audit_status(result.mode),
            repair_used=result.mode == "repair",
            fallback_used=result.mode == "fallback",
            violations=violations,
        )
        if result.mode == "repair" and violations:
            plan = _append_warning(
                plan,
                {
                    "code": "specialist_asset_prompt_repair_used",
                    "message": "Specialist asset prompts were repaired after quality validation.",
                    "stage": "specialist_asset_prompt_quality",
                },
            )
        return plan

    def _deterministic_plan(
        self,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> V2ExpertBriefPlan:
        scene_ids = [scene.scene_id for scene in script_plan.scenes]
        shot_ids = [shot.shot_id for shot in script_plan.shots]
        product_name = request.product_name or "Product"
        product_ids = [
            str(item)
            for item in script_plan.metadata.get("creative_inventory_product_ids", [])
            if str(item).strip()
        ]
        warnings: list[dict[str, Any]] = []
        product_brief = self._product_brief(
            item_id=product_ids[0] if product_ids else "product-1",
            product_name=product_name,
            script_plan=script_plan,
            source_scene_ids=scene_ids,
            source_shot_ids=shot_ids,
        )
        character_briefs = [
            self._character_brief(
                character=character,
                script_plan=script_plan,
            )
            for character in _script_characters(script_plan)
        ]
        scene_briefs = [
            self._scene_brief(
                location=location,
                script_plan=script_plan,
            )
            for location in _script_locations(script_plan)
        ]
        bgm_brief = self._bgm_brief(
            script_plan,
            request,
            source_scene_ids=scene_ids,
            source_shot_ids=shot_ids,
        )
        if request.audio_mode == "none":
            warnings.append(
                {
                    "code": "bgm_disabled_by_audio_mode",
                    "message": "audio_mode=none disables BGM generation; retained disabled brief for schema compatibility.",
                }
            )
        return V2ExpertBriefPlan(
            script_brief_id=script_plan.script_brief_id,
            script_version_id=script_plan.script_version_id,
            product_briefs=[product_brief],
            character_briefs=character_briefs,
            scene_briefs=scene_briefs,
            bgm_brief=bgm_brief,
            warnings=warnings,
        )

    def _mock_plan(
        self,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> V2ExpertBriefPlan:
        return self._deterministic_plan(script_plan, request)

    def _fallback_plan(
        self,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        original_error: V2StructuredLLMError,
    ) -> V2ExpertBriefPlan:
        warning = _fallback_warning(original_error)
        plan = self._deterministic_plan(script_plan, request)
        plan = plan.model_copy(
            update={
                "warnings": [*plan.warnings, warning, _specialist_fallback_warning(original_error)]
            }
        )
        try:
            self._quality.validate_plan(plan, script_plan=script_plan, request=request)
        except Exception as exc:
            raise V2ExpertBriefPlannerError(
                "expert_brief_fallback_failed",
                "Deterministic expert brief fallback failed validation.",
            ) from exc
        try:
            self._specialist_quality.validate_plan(
                plan,
                script_plan=script_plan,
                request=request,
            )
        except V2SpecialistAssetPromptQualityError as exc:
            raise V2ExpertBriefPlannerError(
                "specialist_asset_prompt_fallback_failed",
                "Deterministic specialist asset prompt fallback failed validation.",
            ) from exc
        return plan

    def _validate_plan(
        self,
        plan: V2ExpertBriefPlan,
        *,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> None:
        self._specialist_quality.validate_plan(
            plan,
            script_plan=script_plan,
            request=request,
        )
        self._quality.validate_plan(plan, script_plan=script_plan, request=request)

    def _product_brief(
        self,
        *,
        item_id: str,
        product_name: str,
        script_plan: V2ScriptPlan,
        source_scene_ids: list[str],
        source_shot_ids: list[str],
    ) -> V2ProductBrief:
        beats = "; ".join(script_plan.product_beats[:3]) or script_plan.script_title
        item_prompt = (
            f"Product Designer handoff for {product_name}: define product identity, "
            "recognizable silhouette, brand or packaging cues, hero selling points, "
            f"usage context, and visual style constraints. Selling evidence: {beats}. "
            f"Visual style: {script_plan.visual_style}."
        )
        product_main = (
            f"Create one single hero product reference image for {product_name}: full-frame "
            "product identity, recognizable silhouette, packaging and brand cue clarity, "
            "readable label hierarchy, premium materials, clean neutral background, and "
            "strict product-only presentation. Keep the output focused on reusable product "
            "reference design."
        )
        product_multi = (
            f"Create one 2x2 product multi-view grid for {product_name}: front view, side view, "
            "back view, and detail view. Preserve product identity, recognizable silhouette, "
            "brand or packaging cues, hero selling points, material finish, and visual style constraints. "
            "Keep every panel product-only and reference-ready."
        )
        return V2ProductBrief(
            item_id=item_id,
            display_name=product_name,
            description=beats,
            item_prompt=item_prompt,
            creative_brief=item_prompt,
            slot_prompts={
                "product_main_image": product_main,
                "product_multi_view_grid": product_multi,
            },
            asset_prompts={
                "product_main_image": product_main,
                "product_multi_view_grid": product_multi,
            },
            source_scene_ids=source_scene_ids,
            source_shot_ids=source_shot_ids,
            **self._brief_skill_metadata("product_designer", "product_main_image", "image"),
        )

    def _character_brief(
        self,
        *,
        character: V2ScriptCharacter,
        script_plan: V2ScriptPlan,
    ) -> V2CharacterBrief:
        source_scene_ids, source_shot_ids = _source_ids_for_text(
            script_plan,
            [character.character_id, character.display_name, character.role],
        )
        item_id = character.character_id
        item_prompt = (
            f"Character Designer handoff for {character.display_name}: identity, age impression, "
            "wardrobe, silhouette, facial features, performance role, and emotion arc. "
            f"Script role: {character.role}. Description: {character.description}. "
            f"Visual notes: {character.visual_notes}. Source scenes: {', '.join(source_scene_ids)}; "
            f"source shots: {', '.join(source_shot_ids)}."
        )
        character_main = (
            f"Create one single full-frame character main reference image for {character.display_name}: "
            "clear identity, age impression, body type, wardrobe, silhouette, facial features, "
            "hairstyle, expression, posture, neutral presentation, and plain background. "
            "Use a single image layout."
        )
        character_three = (
            f"Create a front / side / back three-view character turnaround for {character.display_name} "
            "using the selected main image as identity reference. Preserve wardrobe, silhouette, "
            "facial features, proportions, and age impression across all views."
        )
        return V2CharacterBrief(
            item_id=item_id,
            display_name=character.display_name,
            description=character.description,
            item_prompt=item_prompt,
            creative_brief=item_prompt,
            slot_prompts={
                "character_main_image": character_main,
                "character_three_view": character_three,
            },
            asset_prompts={
                "character_main_image": character_main,
                "character_three_view": character_three,
            },
            source_scene_ids=source_scene_ids,
            source_shot_ids=source_shot_ids,
            **self._brief_skill_metadata("character_designer", "character_main_image", "image"),
        )

    def _scene_brief(
        self,
        *,
        location: V2ScriptLocation,
        script_plan: V2ScriptPlan,
    ) -> V2SceneBrief:
        source_scene_ids, source_shot_ids = _source_ids_for_location(script_plan, location)
        item_id = location.location_id
        item_prompt = (
            f"Scene Designer handoff for {location.display_name}: location identity, spatial layout, "
            "lighting, materials, time of day, camera-neutral environment readability, atmosphere, "
            "and blocking-neutral composition guidance. "
            f"Description: {location.description}. Visual notes: {location.visual_notes}. "
            f"Source scenes: {', '.join(source_scene_ids)}; source shots: {', '.join(source_shot_ids)}."
        )
        scene_main = (
            f"Create one single environment reference image for {location.display_name}: location identity, "
            "spatial layout, lighting, materials, time of day, surfaces, depth, and clean commercial readability. "
            "Include camera-neutral composition zones for later composition as an empty environment reference."
        )
        scene_multi = (
            f"Create one 2x2 scene multi-view grid for {location.display_name}: establishing view, "
            "alternate angle, detail view, and background view. Preserve the same spatial layout, "
            "lighting, materials, time of day, camera-neutral composition, and environment identity across all four views. "
            "Keep the grid environment-only and reference-ready."
        )
        return V2SceneBrief(
            item_id=item_id,
            display_name=location.display_name,
            description=location.description,
            item_prompt=item_prompt,
            creative_brief=item_prompt,
            slot_prompts={
                "scene_main_image": scene_main,
                "scene_multi_view_grid": scene_multi,
            },
            asset_prompts={
                "scene_main_image": scene_main,
                "scene_multi_view_grid": scene_multi,
            },
            source_scene_ids=source_scene_ids,
            source_shot_ids=source_shot_ids,
            **self._brief_skill_metadata("scene_designer", "scene_main_image", "image"),
        )

    def _bgm_brief(
        self,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        source_scene_ids: list[str],
        source_shot_ids: list[str],
    ) -> V2BgmBrief:
        item_prompt = (
            f"Sound Director handoff: instrumental background music mood and duration {script_plan.duration_seconds}s "
            f"commercial. Pace and energy curve follow the tone '{script_plan.tone}', supporting the "
            "product story without vocals, narration, lyrics, sound effects, or foley."
        )
        slot_prompt = (
            f"Generate instrumental BGM only with duration {script_plan.duration_seconds}s: mood {script_plan.tone}; "
            "pace starts warm, builds through the product benefit, and resolves with a clean commercial lift. "
            "No vocals, no narration, no lyrics, no sound effects, no foley."
        )
        return V2BgmBrief(
            item_id="bgm-1",
            display_name="BGM",
            description=f"Instrumental music direction for {script_plan.script_title}.",
            item_prompt=item_prompt,
            slot_prompts={"bgm_audio": slot_prompt},
            source_scene_ids=source_scene_ids,
            source_shot_ids=source_shot_ids,
            duration_seconds=script_plan.duration_seconds,
            music_mood=script_plan.tone,
            pace="warm commercial build",
            audio_mode=request.audio_mode,
            **self._brief_skill_metadata("sound_director", "bgm_audio", "audio"),
        )

    def _brief_skill_metadata(
        self,
        specialist: str,
        slot_type: str,
        media_type: str,
    ) -> dict[str, object]:
        context = self._skill_context.skill_context_for_specialist(
            specialist=specialist,
            slot_type=slot_type,
            media_type=media_type,
        )
        return {
            "source_skill_ids": context.skill_ids,
            "source_skill_paths": context.source_paths,
            "brief_builder_version": V2_EXPERT_BRIEF_BUILDER_VERSION,
        }


def _planner_payload(planner_input: V2ExpertBriefPlannerInput) -> dict[str, Any]:
    canonical_context: dict[str, Any]
    if planner_input.specialist_handoffs:
        canonical_context = {
            "specialist_handoffs": [
                handoff.model_dump(mode="json") for handoff in planner_input.specialist_handoffs
            ]
        }
    else:
        canonical_context = {"script_plan": planner_input.script_plan.model_dump(mode="json")}
    return sanitize_context_for_llm_text(
        {
            "task": "Create OiiOii-style expert creative briefs from the validated V2ScriptPlan.",
            "workflow_id": planner_input.workflow_id,
            **canonical_context,
            "planning_constraints": {
                "product_name": planner_input.request.product_name,
                "visual_style_contract": planner_input.request.metadata.get(
                    "visual_style_contract", {}
                ),
                "preserve_visual_style_contract": True,
                "duration_seconds": planner_input.request.duration_seconds,
                "aspect_ratio": planner_input.request.aspect_ratio,
                "audio_mode": planner_input.request.audio_mode,
                "requested_shot_count": planner_input.request.requested_shot_count,
            },
            "input_asset_descriptors": [
                descriptor.model_dump(mode="json")
                for descriptor in planner_input.input_asset_descriptors
            ],
            "output_contract": "V2ExpertBriefPlannerOutput",
            "requirements": {
                "one_product_brief": True,
                "one_character_brief_per_script_character": True,
                "one_scene_brief_per_primary_location": True,
                "one_bgm_brief_when_audio_enabled_or_disabled_placeholder": True,
                "must_include_source_scene_and_shot_ids": True,
                "must_not_generate_media_or_provider_tasks": True,
                "must_not_use_raw_initial_prompt": True,
                "must_not_include_base64_data_urls_raw_bytes_or_secrets": True,
                "product": {
                    "creative_brief_may_include_story_context": True,
                    "asset_prompts_are_slot_scoped": True,
                    "required_item_prompt_language": [
                        "product identity",
                        "recognizable silhouette",
                        "selling points",
                        "usage context",
                        "visual style",
                    ],
                    "required_slot_prompt_keys": [
                        "product_main_image",
                        "product_multi_view_grid",
                    ],
                },
                "character": {
                    "creative_brief_may_include_story_context": True,
                    "asset_prompts_are_slot_scoped": True,
                    "asset_prompts_must_be_character_only": True,
                    "required_item_prompt_language": [
                        "identity",
                        "wardrobe",
                        "silhouette",
                        "performance role",
                        "emotion arc",
                    ],
                    "required_slot_prompt_keys": [
                        "character_main_image",
                        "character_three_view",
                    ],
                },
                "scene": {
                    "creative_brief_may_include_story_context": True,
                    "asset_prompts_are_slot_scoped": True,
                    "asset_prompts_must_be_environment_only": True,
                    "required_item_prompt_language": [
                        "spatial layout",
                        "lighting",
                        "materials",
                        "time of day",
                        "blocking",
                    ],
                    "required_slot_prompt_keys": [
                        "scene_main_image",
                        "scene_multi_view_grid",
                    ],
                },
                "bgm": {
                    "required_item_prompt_language": [
                        "instrumental",
                        "pace",
                        "energy",
                        "duration",
                        "no vocals",
                        "no lyrics",
                    ],
                    "required_slot_prompt_keys": ["bgm_audio"],
                },
                "missing_any_required_key_or_semantic_term_invalidates_output": True,
            },
        }
    )


def _canonical_script_plan(
    script_plan: V2ScriptPlan | V2ScriptPlanV2,
) -> V2ScriptPlanV2:
    if isinstance(script_plan, V2ScriptPlanV2):
        return script_plan
    try:
        return V2ScriptPersistenceAdapter().normalize_metadata_plan(
            script_plan.model_dump(mode="json")
        )[0]
    except Exception as exc:
        raise V2ExpertBriefPlannerError(
            "script_plan_unavailable",
            "Expert brief planning requires a canonical version-2 screenplay.",
        ) from exc


def _system_prompt() -> str:
    return (
        V2HighRiskPromptRenderer()
        .render(
            prompt_id="v2.expert_brief.plan.v1",
            context={
                "inventory_constraints": {
                    "product_count": 1,
                    "character_count": "requested",
                    "scene_count": "requested",
                    "shot_count": "requested",
                    "duration_seconds": "requested",
                    "aspect_ratio": "requested",
                }
            },
            identity={"path_kind": "normal"},
        )
        .prompt_text
    )


def _planner_runtime_error_code(exc: StructuredGenerationRuntimeError) -> str:
    if exc.code == "structured_generation_fallback_failed":
        cause_code = getattr(exc.__cause__, "code", None)
        if cause_code in {
            "specialist_asset_prompt_fallback_failed",
            "expert_brief_fallback_failed",
        }:
            return str(cause_code)
        return "expert_brief_fallback_failed"
    if exc.code == "structured_generation_unavailable":
        return "expert_brief_planner_unavailable"
    if exc.code in {
        "structured_generation_schema_failed",
        "structured_generation_quality_failed",
        "structured_generation_repair_failed",
    }:
        return "expert_brief_repair_failed"
    return "expert_brief_llm_call_failed"


def _output_from_plan(plan: V2ExpertBriefPlan) -> V2ExpertBriefPlannerOutput:
    return V2ExpertBriefPlannerOutput.model_validate(plan.model_dump(mode="json"))


def _expert_brief_repair_context(error: V2StructuredLLMError) -> dict[str, Any]:
    details = error.quality_error_details
    if isinstance(details, dict):
        return dict(details)
    return {}


def _planner_error_code(exc: V2StructuredLLMError) -> str:
    if exc.code == "structured_llm_unavailable":
        return "expert_brief_planner_unavailable"
    if exc.code == "structured_llm_call_failed":
        return "expert_brief_llm_call_failed"
    if exc.code == "structured_generation_repair_failed":
        return "expert_brief_repair_failed"
    if exc.code == "structured_output_invalid_json":
        return "expert_brief_repair_failed"
    if exc.code == "structured_output_schema_invalid":
        return "expert_brief_repair_failed"
    if exc.code == "structured_output_quality_failed":
        return "expert_brief_repair_failed"
    return "expert_brief_llm_call_failed"


def _fallback_warning(exc: V2StructuredLLMError) -> dict[str, Any]:
    original_error_code = _planner_error_code(exc)
    return {
        "code": "expert_brief_planner_fallback_used",
        "message": "Real expert brief planning failed validation; deterministic expert briefs were used.",
        "failed_stage": _failed_stage(exc),
        "original_error_code": original_error_code,
        "original_error_message": _safe_error_message(exc),
    }


def _specialist_fallback_warning(exc: V2StructuredLLMError) -> dict[str, Any]:
    return {
        "code": "specialist_asset_prompt_fallback_used",
        "message": "Specialist asset prompt quality used deterministic fallback prompts.",
        "failed_stage": _failed_stage(exc),
        "original_error_code": _planner_error_code(exc),
        "original_error_message": _safe_error_message(exc),
    }


def _append_warning(plan: V2ExpertBriefPlan, warning: dict[str, Any]) -> V2ExpertBriefPlan:
    return plan.model_copy(update={"warnings": [*plan.warnings, warning]}, deep=True)


def _specialist_audit_status(mode: str) -> str:
    if mode == "repair":
        return "repaired"
    if mode == "fallback":
        return "fallback_used"
    return "passed"


def _specialist_violations_from_quality_errors(
    quality_errors: list[dict[str, Any]],
) -> list[V2SpecialistQualityViolation]:
    violations: list[V2SpecialistQualityViolation] = []
    for error in quality_errors:
        details = error.get("details")
        if not isinstance(details, dict):
            continue
        raw_violations = details.get("specialist_quality_violations")
        if not isinstance(raw_violations, list):
            continue
        for raw in raw_violations:
            if not isinstance(raw, dict):
                continue
            try:
                violations.append(V2SpecialistQualityViolation.model_validate(raw))
            except Exception:
                continue
    return violations


def _with_specialist_quality_audit(
    plan: V2ExpertBriefPlan,
    *,
    status: str,
    repair_used: bool,
    fallback_used: bool,
    violations: list[V2SpecialistQualityViolation],
) -> V2ExpertBriefPlan:
    audit = specialist_quality_audit(
        status=status,  # type: ignore[arg-type]
        repair_used=repair_used,
        fallback_used=fallback_used,
        violations=violations,
    )

    def update_brief(brief: Any) -> Any:
        return brief.model_copy(update={"specialist_quality_audit": audit}, deep=True)

    return plan.model_copy(
        update={
            "product_briefs": [update_brief(brief) for brief in plan.product_briefs],
            "character_briefs": [update_brief(brief) for brief in plan.character_briefs],
            "scene_briefs": [update_brief(brief) for brief in plan.scene_briefs],
            "specialist_quality_audit": audit,
        },
        deep=True,
    )


def _failed_stage(exc: V2StructuredLLMError) -> str:
    if exc.code in {"structured_llm_call_failed", "structured_llm_unavailable"}:
        return "real_llm"
    if exc.code in {"structured_output_invalid_json", "structured_output_schema_invalid"}:
        return "schema_validation"
    if exc.code == "structured_output_quality_failed" or exc.quality_error_code:
        return "quality_validation"
    return "repair"


def _safe_error_message(exc: V2StructuredLLMError) -> str:
    message = str(exc).strip()
    if not message:
        return exc.code
    return message[:500]


def _coerce_input_asset_descriptor(
    value: dict[str, Any] | V2ExpertBriefInputAssetDescriptor,
) -> V2ExpertBriefInputAssetDescriptor:
    if isinstance(value, V2ExpertBriefInputAssetDescriptor):
        return value
    return V2ExpertBriefInputAssetDescriptor.model_validate(value)


def _script_characters(script_plan: V2ScriptPlan) -> list[V2ScriptCharacter]:
    return script_plan.characters


def _script_locations(script_plan: V2ScriptPlan) -> list[V2ScriptLocation]:
    if script_plan.locations:
        return script_plan.locations
    return [
        V2ScriptLocation(
            location_id=scene.location_id or scene.scene_id,
            display_name=scene.title,
            description=scene.description,
            visual_notes="Derived from script scene description.",
        )
        for scene in script_plan.scenes
    ]


def _source_ids_for_text(
    script_plan: V2ScriptPlan,
    values: list[str],
) -> tuple[list[str], list[str]]:
    terms = [value.lower() for value in values if value.strip()]
    scene_ids: list[str] = []
    shot_ids: list[str] = []
    for shot in script_plan.shots:
        haystack = " ".join(
            [
                shot.description,
                shot.visual_prompt,
                shot.narration or "",
            ]
        ).lower()
        if any(term and term in haystack for term in terms):
            shot_ids.append(shot.shot_id)
            if shot.scene_id not in scene_ids:
                scene_ids.append(shot.scene_id)
    if not shot_ids:
        return [scene.scene_id for scene in script_plan.scenes], [
            shot.shot_id for shot in script_plan.shots
        ]
    return scene_ids, shot_ids


def _source_ids_for_location(
    script_plan: V2ScriptPlan,
    location: V2ScriptLocation,
) -> tuple[list[str], list[str]]:
    scene_ids = [
        scene.scene_id
        for scene in script_plan.scenes
        if scene.location_id == location.location_id
        or location.display_name.lower() in scene.title.lower()
        or location.display_name.lower() in scene.description.lower()
    ]
    if not scene_ids:
        scene_ids = [scene.scene_id for scene in script_plan.scenes]
    shot_ids = [shot.shot_id for shot in script_plan.shots if shot.scene_id in scene_ids]
    if not shot_ids:
        shot_ids = [shot.shot_id for shot in script_plan.shots]
    return scene_ids, shot_ids
