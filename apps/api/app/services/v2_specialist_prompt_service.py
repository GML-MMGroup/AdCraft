from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    V2GenerationTarget,
    V2PromptMaterializerMode,
    V2SpecialistPromptRequest,
    V2SpecialistPromptResult,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_prompt_contract_adapter import (
    is_prompt_contract_slot,
    prompt_contract_from_specialist_result,
    specialist_result_from_prompt_contract,
)
from app.services.v2_prompt_contract_quality import validate_prompt_contract
from app.services.v2_skill_context import V2SkillContextService
from app.services.v2_specialist_configs import V2SpecialistConfig, specialist_config_for
from app.services.v2_specialist_llm_client import (
    V2SpecialistLLMClient,
    V2SpecialistLLMClientError,
)
from app.services.v2_specialist_prompt_sanitizer import V2SpecialistPromptSanitizer
from app.services.v2_specialist_ownership import (
    ownership_scope_for,
    validate_specialist_owned_plan,
    validate_specialist_slot_target,
)
from app.services.v2_prompt_registry import V2PromptRegistry
from app.services.v2_versioning import V2_SPECIALIST_MATERIALIZER_VERSION
from app.schemas.workflow_v2_specialist_ownership import (
    V2SpecialistOwnedPlan,
    V2SpecialistSlotPlan,
)


class V2SpecialistPromptError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2SpecialistPromptService:
    def __init__(
        self,
        settings: Settings | None = None,
        llm_client: V2SpecialistLLMClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client
        self._skill_context = V2SkillContextService()

    def materialize(
        self,
        request: V2SpecialistPromptRequest,
    ) -> V2SpecialistPromptResult:
        safe_request = V2SpecialistPromptRequest.model_validate(
            sanitize_context_for_llm_text(request.model_dump(mode="json"))
        )
        config = self._config_for_request(safe_request)
        safe_request = _with_skill_context(safe_request, self._skill_context)
        if config.specialist == "composition_tool":
            result = _deterministic_specialist_result(
                safe_request,
                mode="mock",
                warnings=[],
                model_id=None,
            )
            return _with_result_provenance(result, safe_request, config)

        mode, warnings = self._resolve_mode(config)
        if mode == "real":
            try:
                result = self._real_client().materialize(safe_request, config)
                _validate_specialist_result(result)
                return _with_result_provenance(result, safe_request, config)
            except V2SpecialistLLMClientError as exc:
                if self._settings.v2_prompt_materializer_strict:
                    raise V2SpecialistPromptError(
                        "prompt_materialization_failed",
                        f"{exc.code}: {exc}",
                    ) from exc
                result = _deterministic_specialist_result(
                    safe_request,
                    mode="fallback",
                    warnings=[_warning(exc.code, str(exc))],
                    model_id=None,
                )
                return _with_result_provenance(result, safe_request, config)
            except V2SpecialistPromptError:
                raise

        result = _deterministic_specialist_result(
            safe_request,
            mode=mode,
            warnings=warnings,
            model_id=None,
        )
        return _with_result_provenance(result, safe_request, config)

    def materialize_fallback(
        self,
        request: V2SpecialistPromptRequest,
        *,
        warning: dict[str, Any],
    ) -> V2SpecialistPromptResult:
        """Build a validated deterministic result from an allowlisted slot request."""
        safe_request = V2SpecialistPromptRequest.model_validate(
            sanitize_context_for_llm_text(request.model_dump(mode="json"))
        )
        config = self._config_for_request(safe_request)
        safe_request = _with_skill_context(safe_request, self._skill_context)
        result = _deterministic_specialist_result(
            safe_request,
            mode="fallback",
            warnings=[sanitize_context_for_llm_text(warning)],
            model_id=None,
        )
        return _with_result_provenance(result, safe_request, config)

    def _resolve_mode(
        self,
        config: V2SpecialistConfig,
    ) -> tuple[V2PromptMaterializerMode, list[dict[str, Any]]]:
        if self._settings.agno_mock_mode:
            return "mock", []
        if (
            config.is_llm_specialist
            and not config.model_id
            and (
                self._settings.llm_api_key
                or self._settings.llm_base_url
                or self._settings.v2_prompt_materializer_strict
            )
        ):
            raise V2SpecialistPromptError(
                "specialist_model_not_configured",
                f"{config.model_env_key or config.specialist} is not configured.",
            )
        if self._real_specialist_available(config):
            return "real", []
        if self._settings.v2_prompt_materializer_strict:
            raise V2SpecialistPromptError(
                "prompt_materialization_failed",
                "Real specialist prompt materializer is unavailable.",
            )
        return ("fallback", [_warning("real_specialist_unavailable")])

    def _config_for_request(
        self,
        request: V2SpecialistPromptRequest,
    ) -> V2SpecialistConfig:
        specialist = str(request.agent_route.get("specialist") or "")
        config = specialist_config_for(specialist, self._settings)
        slot_type = str(request.target.get("slot_type") or "")
        media_type = request.target.get("media_type")
        media_type = media_type if isinstance(media_type, str) else None
        if config is None or not config.supports_target(slot_type, media_type):
            raise V2SpecialistPromptError(
                "unsupported_target_for_specialist",
                f"Specialist {specialist or '<missing>'} does not support {slot_type}.",
            )
        validation = validate_specialist_slot_target(
            specialist=specialist,
            target=_target_from_request(request),
            action=_action_for_request(request),
        )
        if not validation.valid:
            raise V2SpecialistPromptError(
                validation.error_code or "specialist_ownership_violation",
                validation.error_message,
            )
        return config

    def _real_specialist_available(self, config: V2SpecialistConfig) -> bool:
        return bool(
            config.is_llm_specialist
            and self._settings.llm_api_key
            and self._settings.llm_base_url
            and config.model_id
        )

    def _real_client(self) -> V2SpecialistLLMClient:
        if self._llm_client is None:
            self._llm_client = V2SpecialistLLMClient(self._settings)
        return self._llm_client


def _warning(
    code: str,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message or "Deterministic fallback materializer was used.",
    }


def _visual_style_prompt(request: V2SpecialistPromptRequest) -> str | None:
    context = request.director_context_summary
    if not isinstance(context, dict):
        return None
    contract = context.get("visual_style_contract")
    if not isinstance(contract, dict):
        return None
    style_prompt = contract.get("style_prompt")
    if not isinstance(style_prompt, str):
        return None
    normalized = style_prompt.strip()
    return normalized or None


def _with_skill_context(
    request: V2SpecialistPromptRequest,
    skill_context_service: V2SkillContextService,
) -> V2SpecialistPromptRequest:
    if request.skill_context.get("skill_ids"):
        return request
    specialist = str(request.agent_route.get("specialist") or "")
    slot_type = str(request.target.get("slot_type") or "")
    media_type = str(request.target.get("media_type") or "")
    context = skill_context_service.skill_context_for_specialist(
        specialist=specialist,
        slot_type=slot_type,
        media_type=media_type,
    )
    return request.model_copy(update={"skill_context": context.model_dump(mode="json")})


def _target_from_request(request: V2SpecialistPromptRequest) -> V2GenerationTarget:
    payload = dict(request.target)
    payload.setdefault("workflow_id", request.workflow_id)
    return V2GenerationTarget(
        workflow_id=str(payload.get("workflow_id") or request.workflow_id),
        target_type=payload.get("target_type") or "slot",
        node_id=payload.get("node_id"),
        node_type=payload.get("node_type"),
        item_id=payload.get("item_id"),
        item_type=payload.get("item_type"),
        slot_id=payload.get("slot_id"),
        slot_type=payload.get("slot_type"),
        asset_id=payload.get("asset_id"),
        media_type=payload.get("media_type"),
        is_free_generation=bool(payload.get("is_free_generation")),
    )


def _action_for_request(request: V2SpecialistPromptRequest) -> str:
    explicit = request.target.get("action") or request.agent_route.get("action")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    slot_type = str(request.target.get("slot_type") or "")
    if slot_type == "shot_video_segment":
        return "materialize_shot_video"
    if slot_type.startswith("shot_cell_"):
        return "materialize_shot_cells"
    if slot_type == "final_video":
        return "build_timeline"
    if slot_type == "free_output":
        return "free_generate"
    return "materialize_item_slots"


def _with_result_provenance(
    result: V2SpecialistPromptResult,
    request: V2SpecialistPromptRequest,
    config: V2SpecialistConfig,
) -> V2SpecialistPromptResult:
    metadata = _skill_metadata(request)
    prompt_provenance = _materializer_prompt_provenance(request, config)
    detail_prompts = {
        **dict(result.detail_prompts),
        **prompt_provenance,
    }
    result = result.model_copy(update={"detail_prompts": detail_prompts}, deep=True)
    owned_plan = _owned_plan_for_result(result, request, config)
    validation = validate_specialist_owned_plan(owned_plan)
    if not validation.valid:
        raise V2SpecialistPromptError(
            validation.error_code or "specialist_ownership_violation",
            validation.error_message,
        )
    ownership_scope = ownership_scope_for(config.specialist)
    return result.model_copy(
        update={
            **metadata,
            "materializer_version": V2_SPECIALIST_MATERIALIZER_VERSION,
            "model_env_key": config.model_env_key,
            "profile_id": config.profile_id,
            "profile_version": config.profile_version,
            "ownership_scope_id": ownership_scope.ownership_scope_id
            if ownership_scope
            else owned_plan.ownership_scope_id,
            "quality_notes": list(
                dict.fromkeys(
                    [
                        *result.quality_notes,
                        "specialist_prompt_passed_quality_gate",
                    ]
                )
            ),
        },
        deep=True,
    )


def _materializer_prompt_provenance(
    request: V2SpecialistPromptRequest,
    config: V2SpecialistConfig,
) -> dict[str, Any]:
    slot_type = str(request.target.get("slot_type") or "")
    media_type = request.target.get("media_type")
    media_type = media_type if isinstance(media_type, str) else None
    render_result = V2HighRiskPromptRenderer().render(
        prompt_id="v2.specialist.materializer.v1",
        context={
            "specialist": config.specialist,
            "slot_type": slot_type,
        },
        identity={
            "workflow_id": request.workflow_id,
            "node_id": request.target.get("node_id"),
            "item_id": request.target.get("item_id"),
            "slot_id": request.target.get("slot_id"),
            "slot_type": slot_type,
            "media_type": media_type,
            "specialist": config.specialist,
            "path_kind": "normal",
        },
    )
    lineage = V2PromptRegistry().lineage_for_render(render_result).model_dump(mode="json")
    payload = {
        "materializer_prompt_registry_ref": render_result.prompt_registry_ref.model_dump(
            mode="json"
        ),
        "materializer_prompt_lineage": lineage,
    }
    if isinstance(render_result.metadata.get("prompt_content_profile"), dict):
        payload["materializer_prompt_content_profile"] = render_result.metadata[
            "prompt_content_profile"
        ]
    return sanitize_context_for_llm_text(payload)


def _owned_plan_for_result(
    result: V2SpecialistPromptResult,
    request: V2SpecialistPromptRequest,
    config: V2SpecialistConfig,
) -> V2SpecialistOwnedPlan:
    target = _target_from_request(request)
    slot_type = str(target.slot_type or "")
    item_id = str(target.item_id or request.target.get("item_id") or "item")
    slot_id = str(target.slot_id or request.target.get("slot_id") or f"{item_id}:{slot_type}")
    scope = ownership_scope_for(config.specialist)
    return V2SpecialistOwnedPlan(
        specialist=config.specialist,  # type: ignore[arg-type]
        model_id=result.model_id or config.model_id,
        ownership_scope_id=scope.ownership_scope_id if scope else config.specialist,
        target_node_id=str(target.node_id or request.target.get("node_id") or ""),
        target_item_id=item_id,
        action=_action_for_request(request),
        slot_plans=[
            V2SpecialistSlotPlan(
                slot_id=slot_id,
                slot_type=slot_type,
                item_id=item_id,
                summary_prompt=result.summary_prompt or request.summary_prompt or "",
                specialist_prompt=result.specialist_prompt
                or f"{config.specialist} structured prompt",
                provider_prompt=result.provider_prompt,
                negative_prompt=result.negative_prompt,
                negative_constraints=result.negative_constraints,
                reference_asset_ids=list(result.reference_asset_ids),
                detail_prompts=dict(result.detail_prompts),
                prompt_contract_name=str(
                    result.detail_prompts.get("prompt_contract_name")
                    or request.target.get("prompt_contract_name")
                    or slot_type
                    or "V2GenericProviderPayload"
                ),
                prompt_contract_version=str(
                    result.detail_prompts.get("prompt_contract_version") or "v2"
                ),
                quality_notes=list(result.quality_notes),
            )
        ]
        if slot_type
        else [],
        warnings=list(result.warnings),
        materializer_mode=result.materializer_mode,
        profile_version=config.profile_version,
    )


def _skill_metadata(request: V2SpecialistPromptRequest) -> dict[str, Any]:
    context = request.skill_context if isinstance(request.skill_context, dict) else {}
    return {
        "selected_skill_ids": [str(item) for item in context.get("skill_ids", [])],
        "selected_skill_paths": [str(item) for item in context.get("source_paths", [])],
        "skill_context_warnings": [
            warning for warning in context.get("warnings", []) if isinstance(warning, dict)
        ],
        "quality_notes": ["specialist_prompt_passed_quality_gate"],
        "materializer_version": V2_SPECIALIST_MATERIALIZER_VERSION,
    }


def _validate_specialist_result(result: V2SpecialistPromptResult) -> None:
    forbidden = (
        "Product image prompt:",
        "Character design prompt:",
        "Scene design prompt:",
        "Storyboard frame prompt:",
        "Professional storyboard detail for:",
        "Dialogue direction for:",
        "Audio atmosphere for:",
    )
    serialized = " ".join(
        str(value)
        for value in (
            result.summary_prompt,
            result.specialist_prompt,
            result.provider_prompt,
            result.detail_prompts,
        )
        if value
    )
    if any(pattern in serialized for pattern in forbidden):
        raise V2SpecialistPromptError(
            "specialist_prompt_quality_failed",
            "Specialist prompt output used a forbidden lazy wrapper phrase.",
        )


def _storyboard_video_details(
    detail_prompts: dict[str, Any],
    base: str,
) -> dict[str, Any]:
    storyboard_content = str(detail_prompts.get("storyboard_content") or "").strip()
    if not storyboard_content:
        storyboard_content = (
            f"0.0-2.5s: Establish the shot with {base}\n"
            f"2.5-5.0s: Complete the action with stable product, character, and scene continuity."
        )
    details = {
        "storyboard_content": storyboard_content,
        "dialogue": str(
            detail_prompts.get("dialogue")
            or "No spoken dialogue; preserve any script narration if present."
        ),
        "audio_description": str(
            detail_prompts.get("audio_description")
            or "Use only production sound cues that support motion realism."
        ),
        "voice_style": str(
            detail_prompts.get("voice_style")
            or "Natural commercial voice style when narration is present."
        ),
        "video_negative_constraints": str(
            detail_prompts.get("video_negative_constraints")
            or "No watermark. No subtitles. No distorted labels. No identity drift."
        ),
        "time_segments": detail_prompts.get("time_segments")
        or [
            {"start_seconds": 0.0, "end_seconds": 2.5, "content": "Establish the shot."},
            {"start_seconds": 2.5, "end_seconds": 5.0, "content": "Complete the motion."},
        ],
        "desired_duration_seconds": int(detail_prompts.get("desired_duration_seconds") or 5),
        "provider_duration_seconds": int(detail_prompts.get("provider_duration_seconds") or 5),
    }
    return details


def _deterministic_specialist_result(
    request: V2SpecialistPromptRequest,
    *,
    mode: V2PromptMaterializerMode,
    warnings: list[dict[str, Any]],
    model_id: str | None,
) -> V2SpecialistPromptResult:
    target = request.target
    route = request.agent_route
    specialist = str(route.get("specialist") or "specialist")
    slot_type = str(target.get("slot_type") or "")
    media_type = str(target.get("media_type") or "media")
    summary_prompt = request.summary_prompt or _script_text(request) or request.current_slot_prompt
    current_prompt = request.current_slot_prompt or summary_prompt
    reference_asset_ids = _reference_asset_ids(request)
    detail_prompts = _detail_prompts_for_slot(request, slot_type)
    skill_metadata = _skill_metadata(request)
    detail_prompts.update(skill_metadata)
    completeness = V2SpecialistPromptSanitizer().complete_fallback_prompt(
        slot_type=slot_type,
        specialist_type=specialist,
        prompt=current_prompt,
        summary_prompt=summary_prompt,
        visual_style_prompt=_visual_style_prompt(request),
    )
    current_prompt = completeness.prompt
    if audit := completeness.audit.compact():
        detail_prompts["fallback_field_completeness"] = audit

    if specialist == "composition_tool" or slot_type == "final_video":
        specialist_prompt = (
            "Composition tool brief: assemble selected storyboard video segments, "
            "audio beds, subtitles, and timeline clips into the final ad."
        )
        return V2SpecialistPromptResult(
            summary_prompt=summary_prompt,
            specialist_prompt=specialist_prompt,
            detail_prompts=detail_prompts,
            provider_prompt=None,
            negative_prompt=_constraint(request, "negative_prompt"),
            negative_constraints=_constraint(request, "negative_constraints"),
            reference_asset_ids=reference_asset_ids,
            warnings=warnings,
            materializer_mode=mode,
            model_id=model_id,
            **skill_metadata,
        )

    provider_prompt = _provider_prompt(
        specialist=specialist,
        slot_type=slot_type,
        media_type=media_type,
        summary_prompt=summary_prompt,
        current_prompt=current_prompt,
        detail_prompts=detail_prompts,
    )
    specialist_prompt = f"{specialist} professional brief: {provider_prompt}".strip()
    result = V2SpecialistPromptResult(
        summary_prompt=summary_prompt,
        specialist_prompt=specialist_prompt,
        detail_prompts=detail_prompts,
        provider_prompt=provider_prompt,
        negative_prompt=_constraint(request, "negative_prompt"),
        negative_constraints=_constraint(request, "negative_constraints"),
        reference_asset_ids=reference_asset_ids,
        warnings=warnings,
        materializer_mode=mode,
        model_id=model_id,
        **skill_metadata,
    )
    return _validate_and_convert_contract_result(
        request,
        result,
        slot_type=slot_type,
        mode=mode,
        model_id=model_id,
        skill_metadata=skill_metadata,
        detail_prompts=detail_prompts,
    )


def _provider_prompt(
    *,
    specialist: str,
    slot_type: str,
    media_type: str,
    summary_prompt: str | None,
    current_prompt: str | None,
    detail_prompts: dict[str, Any],
) -> str:
    base = current_prompt or summary_prompt or f"Generate {media_type}."
    if specialist == "product_designer" and slot_type == "product_multi_view_grid":
        return (
            f"Create one 2x2 product multi-view grid: {base}. Include front, side, detail, "
            "and in-context views with the same product geometry, packaging, label hierarchy, "
            "brand marks, lighting, and visual style. Use selected product references when present."
        )
    if specialist == "product_designer":
        return (
            f"Create one single hero product image: {base}. Preserve product identity, "
            "packaging, label details, brand marks, and commercial readability. No contact sheet, "
            "no collage, no multi-panel layout."
        )
    if specialist == "character_designer" and slot_type == "character_three_view":
        return (
            f"Create one front / side / back three-view character turnaround sheet: {base}. "
            "Use the selected character main image when available. Preserve the same identity, "
            "wardrobe, silhouette, proportions, facial features, and color details across all views."
        )
    if specialist == "character_designer":
        return (
            f"Create one single character main reference image: {base}. Preserve identity, "
            "wardrobe, silhouette, and production-ready reference clarity. No turnaround sheet, "
            "no contact sheet, no multi-panel layout."
        )
    if specialist == "scene_designer" and slot_type == "scene_multi_view_grid":
        return (
            f"Create one 2x2 scene multi-view grid of the same location: {base}. Show four views "
            "with the same spatial layout, lighting, materials, and visual style. Use the selected "
            "scene main image when available."
        )
    if specialist == "scene_designer":
        return (
            f"Create one single full-frame environment reference: {base}. Establish environment "
            "layout, lighting, materials, and camera-friendly spatial cues. No multi-view grid, "
            "no collage, no characters unless explicitly required by the script."
        )
    if specialist == "storyboard_artist":
        detail = detail_prompts.get(slot_type) or detail_prompts.get("storyboard_content") or ""
        suffix = f" Frame detail: {detail}" if detail else ""
        return (
            f"Create one single full-frame keyframe for {slot_type}: {base}.{suffix} "
            "No storyboard sheet, no collage, no split screen, no text labels. Maintain product, "
            "character, scene, lighting, and style continuity."
        )
    if specialist == "video_director":
        details = _storyboard_video_details(detail_prompts, base)
        return (
            f"{details['storyboard_content']}\n"
            f"Dialogue: {details['dialogue']}\n"
            f"Audio description: {details['audio_description']}\n"
            f"Voice style: {details['voice_style']}\n"
            f"Negative constraints: {details['video_negative_constraints']}\n"
            "Animate only from the selected four storyboard cell images."
        )
    if specialist == "sound_director":
        duration = detail_prompts.get("duration_seconds")
        duration_text = (
            f"{duration} seconds" if duration else "match the full advertisement duration"
        )
        return (
            f"Compose instrumental background music only for this advertisement: {base}.\n"
            f"Mood: {detail_prompts.get('music_mood') or detail_prompts.get('mood') or 'brand-aligned commercial mood'}.\n"
            f"Pace: {detail_prompts.get('pace') or 'steady advertising pace that supports the edit'}.\n"
            f"Energy: {detail_prompts.get('energy') or 'supportive, polished, and not distracting'}.\n"
            f"Duration: {duration_text}.\n"
            f"Instrumentation: {detail_prompts.get('instrumentation') or 'instrumental synth, light percussion, and warm tonal bed'}.\n"
            f"Commercial pacing: {detail_prompts.get('commercial_pacing') or 'clear intro, product-friendly middle, clean ending'}.\n"
            "No vocals. No lyrics. No narration. No spoken dialogue. "
            "No sound effects. No foley. No scene-specific noises."
        )
    if specialist.startswith("quick_"):
        return f"Generate a standalone {media_type} asset: {base}"
    return base


def _detail_prompts_for_slot(
    request: V2SpecialistPromptRequest,
    slot_type: str,
) -> dict[str, Any]:
    if not request.detail_prompts and slot_type == "shot_video_segment":
        return _storyboard_video_details(
            {}, request.current_slot_prompt or request.summary_prompt or ""
        )
    if not request.detail_prompts:
        if slot_type == "bgm_audio":
            return {
                "duration_seconds": request.director_context_summary.get("duration_seconds"),
                "audio_mode": request.director_context_summary.get("audio_mode"),
            }
        return {}
    if slot_type.startswith("shot_cell_"):
        return dict(request.detail_prompts)
    return dict(request.detail_prompts)


def _reference_asset_ids(request: V2SpecialistPromptRequest) -> list[str]:
    asset_ids: list[str] = []
    for summary in [
        *request.reference_asset_summaries,
        *request.dependency_asset_summaries,
    ]:
        if not isinstance(summary, dict):
            continue
        asset_id = summary.get("asset_id")
        if isinstance(asset_id, str) and asset_id.strip():
            asset_ids.append(asset_id.strip())
    return list(dict.fromkeys(asset_ids))


def _constraint(request: V2SpecialistPromptRequest, key: str) -> str | None:
    value = request.constraints.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _script_text(request: V2SpecialistPromptRequest) -> str | None:
    for key in ("script_text", "summary", "prompt"):
        value = request.script_summary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validate_and_convert_contract_result(
    request: V2SpecialistPromptRequest,
    result: V2SpecialistPromptResult,
    *,
    slot_type: str,
    mode: V2PromptMaterializerMode,
    model_id: str | None,
    skill_metadata: dict[str, Any],
    detail_prompts: dict[str, Any],
) -> V2SpecialistPromptResult:
    if not is_prompt_contract_slot(slot_type):
        return result
    try:
        contract = prompt_contract_from_specialist_result(
            request,
            result,
            slot_type=slot_type,
        )
        validate_prompt_contract(
            contract,
            slot_type=slot_type,
            required_reference_asset_ids=_required_reference_ids(slot_type, result),
        )
        return specialist_result_from_prompt_contract(
            contract,
            slot_type=slot_type,
            materializer_mode=mode,
            model_id=model_id,
            selected_skill_ids=list(skill_metadata.get("selected_skill_ids") or []),
            selected_skill_paths=list(skill_metadata.get("selected_skill_paths") or []),
            skill_context_warnings=list(skill_metadata.get("skill_context_warnings") or []),
            materializer_version=str(skill_metadata.get("materializer_version") or ""),
            extra_detail_prompts=detail_prompts,
            extra_warnings=result.warnings,
            extra_quality_notes=list(skill_metadata.get("quality_notes") or []),
        )
    except Exception as exc:  # noqa: BLE001 - contract failures are normalized for callers.
        raise V2SpecialistPromptError(
            "specialist_prompt_quality_failed",
            str(exc),
        ) from exc


def _required_reference_ids(
    slot_type: str,
    result: V2SpecialistPromptResult,
) -> list[str]:
    if slot_type == "shot_video_segment":
        return list(result.reference_asset_ids)
    return []
