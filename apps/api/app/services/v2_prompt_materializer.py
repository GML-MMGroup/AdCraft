from typing import Any

from app.schemas.workflow_v2 import (
    V2AgentRoute,
    V2GenerationTarget,
    V2MaterializedPrompt,
    V2SpecialistPromptRequest,
    V2SpecialistPromptResult,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_prompt_contracts import (
    V2CanonicalProviderPayload,
    prompt_contract_name_for_slot,
    prompt_contract_version,
)
from app.schemas.workflow_v2_specialist_ownership import (
    V2ProviderPromptCompilationResult,
    V2SpecialistOwnedPlan,
    V2SpecialistSlotPlan,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_prompt_contract_adapter import is_prompt_contract_slot
from app.services.v2_provider_prompt_compiler import (
    PROMPT_ISOLATION_ERROR_CODE,
    V2ProviderPromptCompiler,
    V2ProviderPromptCompilerError,
)
from app.services.v2_item_identity_specs import provider_identity_metadata
from app.services.v2_main_to_multiview_consistency import (
    compile_multiview_provider_prompt,
    is_main_to_multiview_slot,
)
from app.services.v2_slot_context_assembler import V2SlotContextAssembler
from app.services.v2_specialist_prompt_service import (
    V2SpecialistPromptError,
    V2SpecialistPromptService,
)
from app.services.v2_specialist_prompt_sanitizer import V2SpecialistPromptSanitizer
from app.services.v2_skill_context import V2SkillContextService
from app.services.v2_storyboard_cell_prompts import (
    cell_prompt_record_for_slot,
    storyboard_cell_prompt_records,
)
from app.services.v2_storyboard_defaults import shot_cell_role
from app.services.v2_visual_style import V2VisualStyleService


class V2PromptMaterializationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.metadata = metadata or {}


def _bounded_audit(value: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = sanitize_context_for_llm_text(value or {})
    return sanitized if isinstance(sanitized, dict) else {}


def _canonical_final_timeline_payload(
    timeline: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tracks = timeline.get("tracks")
    clips = timeline.get("clips")
    if not isinstance(tracks, list) or not isinstance(clips, list):
        raise V2PromptMaterializationError(
            "v2_final_timeline_invalid",
            "Canonical final timeline must contain tracks and clips.",
        )
    track_order = {
        str(track.get("track_id")): int(track.get("order") or 0)
        for track in tracks
        if isinstance(track, dict) and track.get("track_id")
    }
    timeline_clips = []
    for index, source_clip in enumerate(
        sorted(
            (clip for clip in clips if isinstance(clip, dict)),
            key=lambda clip: (
                track_order.get(str(clip.get("track_id") or ""), 0),
                float(clip.get("start_time") or 0),
                str(clip.get("clip_id") or ""),
            ),
        ),
        start=1,
    ):
        clip = dict(source_clip)
        clip["track_index"] = track_order.get(str(clip.get("track_id") or ""), 0)
        clip["order"] = index
        clip["trim_start"] = clip.get("trim_in")
        clip["trim_end"] = clip.get("trim_out")
        timeline_clips.append(clip)
    source_asset_ids = [
        str(clip["source_asset_id"]) for clip in timeline_clips if clip.get("source_asset_id")
    ]
    return (
        {
            "timeline_id": timeline.get("timeline_id"),
            "version": timeline.get("version"),
            "duration_seconds": timeline.get("duration_seconds"),
            "aspect_ratio": timeline.get("aspect_ratio"),
            "resolution": dict(timeline.get("resolution") or {}),
            "fps": timeline.get("fps"),
            "source_asset_ids": list(dict.fromkeys(source_asset_ids)),
            "source_version_ids": [
                str(clip["source_version_id"])
                for clip in timeline_clips
                if clip.get("source_version_id")
            ],
        },
        timeline_clips,
    )


class V2PromptMaterializer:
    def __init__(
        self,
        specialist_service: V2SpecialistPromptService | None = None,
    ) -> None:
        self._specialist_service = specialist_service or V2SpecialistPromptService()
        self._skill_context = V2SkillContextService()
        self._slot_context_assembler = V2SlotContextAssembler()
        self._provider_prompt_compiler = V2ProviderPromptCompiler()
        self._prompt_sanitizer = V2SpecialistPromptSanitizer()
        self._visual_style_service = V2VisualStyleService()

    def materialize_slot(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        target: V2GenerationTarget,
        route: V2AgentRoute,
        *,
        context: dict[str, Any],
    ) -> V2MaterializedPrompt:
        handoff = _specialist_handoff(context)
        effective_prompt = _effective_handoff_prompt(handoff)
        summary_prompt = effective_prompt or _summary_prompt(item, slot)
        provider_prompt = effective_prompt or _provider_prompt(item, slot, route)
        detail_prompts = _detail_prompts_for_slot(item, slot)
        reference_asset_ids = _reference_asset_ids(workflow, item, slot, route, context)
        if handoff:
            reference_asset_ids = list(
                dict.fromkeys(
                    [
                        *reference_asset_ids,
                        *[
                            str(reference.get("asset_id"))
                            for reference in handoff.get("selected_references", [])
                            if isinstance(reference, dict) and reference.get("asset_id")
                        ],
                    ]
                )
            )
        skill_context = self._skill_context.skill_context_for_specialist(
            specialist=route.specialist,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
        )
        director_context_summary = (
            dict(handoff.get("hard_constraints", {}))
            if handoff
            else {
                "duration_seconds": workflow.duration_seconds,
                "aspect_ratio": workflow.aspect_ratio,
                "audio_mode": workflow.audio_mode,
            }
        )
        if slot.media_type in {"image", "video"} and slot.slot_type != "final_video":
            style_context = dict(context)
            if handoff:
                style_context["selected_references"] = list(handoff.get("selected_references", []))
            style_contract = self._visual_style_service.resolve_for_slot(
                workflow,
                item,
                slot,
                style_context,
            )
            director_context_summary["visual_style_contract"] = style_contract.model_dump(
                mode="json"
            )
        specialist_request = V2SpecialistPromptRequest(
            workflow_id=workflow.workflow_id,
            target=_target_payload(target, slot),
            agent_route=route.model_dump(mode="json"),
            summary_prompt=summary_prompt,
            current_slot_prompt=provider_prompt,
            detail_prompts=detail_prompts,
            reference_asset_summaries=(
                list(handoff.get("selected_references", []))
                if handoff
                else _asset_summaries(reference_asset_ids)
            ),
            dependency_asset_summaries=_asset_summaries(
                [str(asset_id) for asset_id in context.get("dependency_asset_ids", [])]
            ),
            director_context_summary=director_context_summary,
            script_summary=(
                dict(handoff.get("screenplay_slice", {})) if handoff else _script_summary(workflow)
            ),
            constraints={
                "negative_prompt": slot.negative_prompt,
                "negative_constraints": slot.negative_constraints,
            },
            skill_context=skill_context.model_dump(mode="json"),
            provider_capability_summary=dict(slot.provider_params),
        )
        if route.specialist == "composition_tool":
            specialist_result = V2SpecialistPromptResult(
                summary_prompt=summary_prompt,
                specialist_prompt=(
                    "Use the composition timeline and selected media assets to render the final ad."
                ),
                provider_prompt=None,
                reference_asset_ids=reference_asset_ids,
                materializer_mode="fallback",
                materializer_version="v2-local-composition",
            )
        else:
            try:
                specialist_result = self._specialist_service.materialize(specialist_request)
            except V2SpecialistPromptError as exc:
                raise V2PromptMaterializationError(exc.code, str(exc)) from exc

        if item.item_type == "shot" and slot.slot_type.startswith("shot_cell_"):
            summary_prompt = _summary_prompt(item, slot) or summary_prompt
        else:
            summary_prompt = specialist_result.summary_prompt or summary_prompt
        source_provider_prompt = specialist_result.provider_prompt
        detail_prompts = specialist_result.detail_prompts or detail_prompts
        reference_asset_ids = specialist_result.reference_asset_ids or reference_asset_ids
        multiview_context = _multiview_context(context)
        if multiview_context is not None:
            compiled_multiview_prompt = compile_multiview_provider_prompt(
                workflow=workflow,
                item=item,
                slot=slot,
                context=multiview_context,
            )
            if compiled_multiview_prompt:
                source_provider_prompt = compiled_multiview_prompt
                reference_asset_ids = list(multiview_context["reference_asset_ids"])
                detail_prompts = {
                    **detail_prompts,
                    "identity_contract": multiview_context.get("identity_contract", {}),
                    "consistency_contract": multiview_context.get(
                        "consistency_contract",
                        {},
                    ),
                    "multiview_prompt_isolated": True,
                }
                specialist_result = specialist_result.model_copy(
                    update={
                        "provider_prompt": source_provider_prompt,
                        "specialist_prompt": (
                            f"{route.specialist} main-to-multiview consistency brief"
                        ),
                        "reference_asset_ids": reference_asset_ids,
                        "detail_prompts": detail_prompts,
                        "warnings": [
                            *specialist_result.warnings,
                            {
                                "code": "multiview_prompt_isolated",
                                "message": "Multi-view provider prompt was compiled from same-item main reference context.",
                            },
                            *list(multiview_context.get("warnings") or []),
                        ],
                    },
                    deep=True,
                )
        source_provider_prompt, detail_prompts = self._sanitize_provider_prompt(
            slot=slot,
            route=route,
            provider_prompt=source_provider_prompt,
            detail_prompts=detail_prompts,
        )
        try:
            compilation = self._compile_provider_prompt(
                workflow=workflow,
                item=item,
                slot=slot,
                target=target,
                route=route,
                summary_prompt=summary_prompt,
                specialist_result=specialist_result,
                provider_prompt=source_provider_prompt,
                detail_prompts=detail_prompts,
                reference_asset_ids=reference_asset_ids,
                context=context,
            )
            compiled_provider_prompt = compilation.provider_prompt
            reference_asset_ids = compilation.reference_asset_ids or reference_asset_ids
            provider_payload = self._provider_payload(
                workflow,
                item,
                slot,
                target,
                route,
                summary_prompt=summary_prompt,
                provider_prompt=compiled_provider_prompt,
                detail_prompts=detail_prompts,
                reference_asset_ids=reference_asset_ids,
                context=context,
                materializer_mode=specialist_result.materializer_mode,
                materializer_warnings=specialist_result.warnings,
                model_id=specialist_result.model_id,
                selected_skill_ids=specialist_result.selected_skill_ids,
                selected_skill_paths=specialist_result.selected_skill_paths,
                skill_context_warnings=specialist_result.skill_context_warnings,
                quality_notes=specialist_result.quality_notes,
                materializer_version=specialist_result.materializer_version,
                model_env_key=specialist_result.model_env_key,
                profile_id=specialist_result.profile_id,
                profile_version=specialist_result.profile_version,
                ownership_scope_id=specialist_result.ownership_scope_id,
                prompt_compilation=compilation,
            )
        except V2ProviderPromptCompilerError as exc:
            if exc.code == PROMPT_ISOLATION_ERROR_CODE:
                return self._recover_prompt_isolation(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    target=target,
                    route=route,
                    context=context,
                    reference_asset_ids=reference_asset_ids,
                    initial_audit=exc.audit,
                )
            metadata = {"prompt_isolation_audit": exc.audit} if isinstance(exc.audit, dict) else {}
            raise V2PromptMaterializationError(
                exc.code,
                str(exc),
                metadata=metadata,
            ) from exc
        return V2MaterializedPrompt(
            summary_prompt=summary_prompt,
            specialist_prompt=specialist_result.specialist_prompt
            or _specialist_prompt(route, summary_prompt, source_provider_prompt),
            detail_prompts=detail_prompts,
            provider_prompt=source_provider_prompt,
            negative_prompt=specialist_result.negative_prompt or slot.negative_prompt,
            negative_constraints=specialist_result.negative_constraints
            or slot.negative_constraints,
            reference_asset_ids=reference_asset_ids,
            warnings=specialist_result.warnings,
            materializer_mode=specialist_result.materializer_mode,
            model_id=specialist_result.model_id,
            selected_skill_ids=specialist_result.selected_skill_ids,
            selected_skill_paths=specialist_result.selected_skill_paths,
            skill_context_warnings=specialist_result.skill_context_warnings,
            quality_notes=specialist_result.quality_notes,
            materializer_version=specialist_result.materializer_version,
            model_env_key=specialist_result.model_env_key,
            profile_id=specialist_result.profile_id,
            profile_version=specialist_result.profile_version,
            ownership_scope_id=specialist_result.ownership_scope_id,
            provider_payload=provider_payload,
        )

    def _recover_prompt_isolation(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        target: V2GenerationTarget,
        route: V2AgentRoute,
        context: dict[str, Any],
        reference_asset_ids: list[str],
        initial_audit: dict[str, Any] | None,
    ) -> V2MaterializedPrompt:
        current_slot_prompt = (
            slot.user_prompt
            if slot.prompt_source == "user" or slot.manual_prompt_dirty
            else (slot.slot_prompt or _provider_prompt(item, slot, route))
        )
        fallback_skill_context = self._skill_context.skill_context_for_specialist(
            specialist=route.specialist,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
        )
        fallback_request = V2SpecialistPromptRequest(
            workflow_id=workflow.workflow_id,
            target=_target_payload(target, slot),
            agent_route=route.model_dump(mode="json"),
            summary_prompt=_summary_prompt(item, slot),
            current_slot_prompt=current_slot_prompt,
            detail_prompts={},
            reference_asset_summaries=_asset_summaries(reference_asset_ids),
            dependency_asset_summaries=_asset_summaries(
                [str(asset_id) for asset_id in context.get("dependency_asset_ids", [])]
            ),
            director_context_summary={
                "duration_seconds": workflow.duration_seconds,
                "aspect_ratio": workflow.aspect_ratio,
                "audio_mode": workflow.audio_mode,
            },
            script_summary=_script_summary(workflow),
            constraints={
                "negative_prompt": slot.negative_prompt,
                "negative_constraints": slot.negative_constraints,
            },
            skill_context=fallback_skill_context.model_dump(mode="json"),
            provider_capability_summary=dict(slot.provider_params),
        )
        warning = {
            "code": "prompt_isolation_violation_recovered",
            "message": "The provider prompt was rebuilt from the current slot context.",
        }
        try:
            specialist_result = self._specialist_service.materialize_fallback(
                fallback_request,
                warning=warning,
            )
        except V2SpecialistPromptError as exc:
            raise V2PromptMaterializationError(exc.code, str(exc)) from exc
        provider_prompt, detail_prompts = self._sanitize_provider_prompt(
            slot=slot,
            route=route,
            provider_prompt=specialist_result.provider_prompt,
            detail_prompts=specialist_result.detail_prompts,
        )
        try:
            compilation = self._compile_provider_prompt(
                workflow=workflow,
                item=item,
                slot=slot,
                target=target,
                route=route,
                summary_prompt=specialist_result.summary_prompt,
                specialist_result=specialist_result,
                provider_prompt=provider_prompt,
                detail_prompts=detail_prompts,
                reference_asset_ids=specialist_result.reference_asset_ids or reference_asset_ids,
                context=context,
            )
        except V2ProviderPromptCompilerError as exc:
            final_audit = _bounded_audit(exc.audit)
            raise V2PromptMaterializationError(
                PROMPT_ISOLATION_ERROR_CODE,
                str(exc),
                metadata={
                    "prompt_isolation_audit": final_audit,
                    "prompt_isolation_recovery": {
                        "attempt_count": 1,
                        "recovered": False,
                        "initial_audit": _bounded_audit(initial_audit),
                        "final_audit": final_audit,
                    },
                },
            ) from exc
        final_reference_asset_ids = compilation.reference_asset_ids or reference_asset_ids
        provider_payload = self._provider_payload(
            workflow,
            item,
            slot,
            target,
            route,
            summary_prompt=specialist_result.summary_prompt,
            provider_prompt=compilation.provider_prompt,
            detail_prompts=detail_prompts,
            reference_asset_ids=final_reference_asset_ids,
            context=context,
            materializer_mode="fallback",
            materializer_warnings=specialist_result.warnings,
            model_id=specialist_result.model_id,
            selected_skill_ids=specialist_result.selected_skill_ids,
            selected_skill_paths=specialist_result.selected_skill_paths,
            skill_context_warnings=specialist_result.skill_context_warnings,
            quality_notes=specialist_result.quality_notes,
            materializer_version=specialist_result.materializer_version,
            model_env_key=specialist_result.model_env_key,
            profile_id=specialist_result.profile_id,
            profile_version=specialist_result.profile_version,
            ownership_scope_id=specialist_result.ownership_scope_id,
            prompt_compilation=compilation,
        )
        provider_payload.update(
            {
                "fallback_reason": "prompt_isolation_violation",
                "prompt_isolation_recovery": {
                    "attempt_count": 1,
                    "recovered": True,
                    "initial_audit": _bounded_audit(initial_audit),
                    "final_audit": _bounded_audit(
                        compilation.provider_payload_metadata.get("prompt_isolation_audit")
                    ),
                },
            }
        )
        return V2MaterializedPrompt(
            summary_prompt=specialist_result.summary_prompt,
            specialist_prompt=specialist_result.specialist_prompt,
            detail_prompts=detail_prompts,
            provider_prompt=provider_prompt,
            negative_prompt=specialist_result.negative_prompt or slot.negative_prompt,
            negative_constraints=specialist_result.negative_constraints
            or slot.negative_constraints,
            reference_asset_ids=final_reference_asset_ids,
            warnings=specialist_result.warnings,
            materializer_mode="fallback",
            model_id=specialist_result.model_id,
            selected_skill_ids=specialist_result.selected_skill_ids,
            selected_skill_paths=specialist_result.selected_skill_paths,
            skill_context_warnings=specialist_result.skill_context_warnings,
            quality_notes=specialist_result.quality_notes,
            materializer_version=specialist_result.materializer_version,
            model_env_key=specialist_result.model_env_key,
            profile_id=specialist_result.profile_id,
            profile_version=specialist_result.profile_version,
            ownership_scope_id=specialist_result.ownership_scope_id,
            provider_payload=provider_payload,
        )

    def _compile_provider_prompt(
        self,
        *,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        target: V2GenerationTarget,
        route: V2AgentRoute,
        summary_prompt: str | None,
        specialist_result: V2SpecialistPromptResult,
        provider_prompt: str | None,
        detail_prompts: dict[str, Any],
        reference_asset_ids: list[str],
        context: dict[str, Any],
    ) -> V2ProviderPromptCompilationResult:
        slot_plan = V2SpecialistSlotPlan(
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            item_id=item.item_id,
            summary_prompt=summary_prompt or _summary_prompt(item, slot) or "Generate media.",
            specialist_prompt=specialist_result.specialist_prompt
            or _specialist_prompt(route, summary_prompt, provider_prompt),
            provider_prompt=provider_prompt,
            negative_prompt=specialist_result.negative_prompt or slot.negative_prompt,
            negative_constraints=specialist_result.negative_constraints
            or slot.negative_constraints,
            reference_asset_ids=reference_asset_ids,
            detail_prompts=detail_prompts,
            prompt_contract_name=str(
                detail_prompts.get("prompt_contract_name")
                or _prompt_contract_name_for_payload(slot.slot_type)
            ),
            prompt_contract_version=str(
                detail_prompts.get("prompt_contract_version") or prompt_contract_version()
            ),
            quality_notes=list(specialist_result.quality_notes),
        )
        owned_plan = V2SpecialistOwnedPlan(
            specialist=route.specialist,
            model_id=specialist_result.model_id,
            ownership_scope_id=specialist_result.ownership_scope_id
            or f"{route.specialist}:{slot.node_id}:{item.item_type}",
            target_node_id=slot.node_id,
            target_item_id=item.item_id,
            action=_action_for_slot(slot),
            slot_plans=[slot_plan],
            warnings=list(specialist_result.warnings),
            materializer_mode=specialist_result.materializer_mode,
            profile_version=specialist_result.profile_version or "v2",
        )
        slot_context = self._slot_context_assembler.assemble(
            workflow=workflow,
            item=item,
            slot=slot,
            route=route,
            owned_plan=owned_plan,
            slot_plan=slot_plan,
            runtime_context=context,
        )
        multiview_context = _multiview_context(context)
        canonical_handoff = bool(_specialist_handoff(context))
        allow_cell_context = slot.slot_type == "shot_video_segment"
        compilation = self._provider_prompt_compiler.compile(
            slot_context,
            sibling_provider_prompts=[]
            if canonical_handoff or multiview_context is not None or allow_cell_context
            else _sibling_provider_prompts(item, slot),
            sibling_detail_prompts=[]
            if canonical_handoff or multiview_context is not None or allow_cell_context
            else _sibling_detail_prompts(item, slot),
        )
        style_context = dict(context)
        handoff = _specialist_handoff(context)
        if handoff:
            style_context["selected_references"] = list(handoff.get("selected_references", []))
        contract = self._visual_style_service.resolve_for_slot(
            workflow,
            item,
            slot,
            style_context,
        )
        if "visual_style_contract" not in workflow.metadata:
            workflow.metadata["visual_style_contract"] = contract.model_dump(mode="json")
        if slot.media_type == "audio":
            return compilation
        application = self._visual_style_service.apply_to_provider_prompt(
            slot_type=slot.slot_type,
            provider_prompt=compilation.provider_prompt,
            negative_prompt=compilation.negative_prompt,
            negative_constraints=compilation.negative_constraints,
            contract=contract,
            reference_style_preserved=contract.source == "selected_reference",
        )
        return compilation.model_copy(
            update={
                "provider_prompt": application.provider_prompt,
                "negative_prompt": application.negative_prompt,
                "negative_constraints": application.negative_constraints,
                "provider_payload_metadata": {
                    **compilation.provider_payload_metadata,
                    "visual_style_contract": application.contract.model_dump(mode="json"),
                    "visual_style_audit": application.audit.model_dump(mode="json"),
                },
            },
            deep=True,
        )

    def _provider_payload(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        target: V2GenerationTarget,
        route: V2AgentRoute,
        *,
        summary_prompt: str | None,
        provider_prompt: str | None,
        detail_prompts: dict[str, Any],
        reference_asset_ids: list[str],
        context: dict[str, Any],
        materializer_mode: str,
        materializer_warnings: list[dict[str, Any]],
        model_id: str | None,
        selected_skill_ids: list[str],
        selected_skill_paths: list[str],
        skill_context_warnings: list[dict[str, Any]],
        quality_notes: list[str],
        materializer_version: str | None,
        model_env_key: str | None,
        profile_id: str | None,
        profile_version: str | None,
        ownership_scope_id: str | None,
        prompt_compilation: V2ProviderPromptCompilationResult,
    ) -> dict[str, Any]:
        route_payload = route.model_dump(mode="json")
        identity_metadata = provider_identity_metadata(dict(item.metadata or {}))
        base_payload: dict[str, Any] = {
            "agent_route": route_payload,
            "target": target.model_dump(mode="json"),
            "summary_prompt": summary_prompt,
            "provider_prompt": provider_prompt,
            "slot_prompt": slot.slot_prompt,
            "negative_prompt": prompt_compilation.negative_prompt,
            "negative_constraints": prompt_compilation.negative_constraints,
            "provider_params": dict(slot.provider_params),
            "reference_asset_ids": reference_asset_ids,
            "materializer_mode": materializer_mode,
            "materializer_warnings": materializer_warnings,
            "materializer_model_id": model_id,
            "selected_skill_ids": selected_skill_ids,
            "selected_skill_paths": selected_skill_paths,
            "skill_context_warnings": skill_context_warnings,
            "quality_notes": quality_notes,
            "materializer_version": materializer_version,
            "model_env_key": model_env_key,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "ownership_scope_id": ownership_scope_id,
            "slot_context_lineage": prompt_compilation.provider_payload_metadata.get(
                "slot_context_lineage", {}
            ),
            "slot_context_id": prompt_compilation.provider_payload_metadata.get("slot_context_id"),
            "slot_context_fingerprint": prompt_compilation.provider_payload_metadata.get(
                "slot_context_fingerprint"
            ),
            "provider_prompt_fingerprint": prompt_compilation.provider_payload_metadata.get(
                "provider_prompt_fingerprint"
            ),
            "prompt_registry_ref": prompt_compilation.provider_payload_metadata.get(
                "prompt_registry_ref", {}
            ),
            "prompt_lineage": prompt_compilation.provider_payload_metadata.get(
                "prompt_lineage", {}
            ),
            "prompt_content_profile": prompt_compilation.provider_payload_metadata.get(
                "prompt_content_profile", {}
            ),
            "allowed_reference_asset_ids": prompt_compilation.provider_payload_metadata.get(
                "allowed_reference_asset_ids", []
            ),
            "forbidden_reference_asset_ids": prompt_compilation.provider_payload_metadata.get(
                "forbidden_reference_asset_ids", []
            ),
            "prompt_isolation_audit": prompt_compilation.provider_payload_metadata.get(
                "prompt_isolation_audit", {}
            ),
            "prompt_contamination_check": prompt_compilation.provider_payload_metadata.get(
                "prompt_contamination_check", {}
            ),
            "provider_prompt_contract": prompt_compilation.provider_payload_metadata.get(
                "provider_prompt_contract", {}
            ),
            "continuity_sources": prompt_compilation.provider_payload_metadata.get(
                "continuity_sources", {}
            ),
            "prompt_provenance": _prompt_provenance(
                slot=slot,
                prompt_compilation=prompt_compilation,
                detail_prompts=detail_prompts,
                materializer_warnings=materializer_warnings,
                reference_asset_ids=reference_asset_ids,
            ),
            **identity_metadata,
        }
        visual_style_contract = prompt_compilation.provider_payload_metadata.get(
            "visual_style_contract"
        )
        visual_style_audit = prompt_compilation.provider_payload_metadata.get("visual_style_audit")
        if isinstance(visual_style_contract, dict) and isinstance(visual_style_audit, dict):
            base_payload["visual_style_contract"] = visual_style_contract
            base_payload["visual_style_audit"] = visual_style_audit
        for audit_key in ("prompt_sanitization_audit", "fallback_field_completeness"):
            audit_value = detail_prompts.get(audit_key)
            if isinstance(audit_value, dict) and audit_value:
                base_payload[audit_key] = sanitize_context_for_llm_text(audit_value)
        if isinstance(context.get("reference_bundle"), dict):
            base_payload["reference_bundle"] = context["reference_bundle"]
            base_payload["provider_reference_assets"] = list(
                context.get("provider_reference_assets", [])
            )
            base_payload["llm_context_assets"] = list(context.get("llm_context_assets", []))
            base_payload["reference_warnings"] = list(context.get("reference_warnings", []))
        if isinstance(context.get("specialist_handoff"), dict):
            base_payload["specialist_handoff"] = sanitize_context_for_llm_text(
                context["specialist_handoff"]
            )

        def canonicalize(payload: dict[str, Any]) -> dict[str, Any]:
            compiled_payload = _with_canonical_provider_payload(
                payload,
                workflow=workflow,
                item=item,
                slot=slot,
                target=target,
                detail_prompts=detail_prompts,
            )
            return self._provider_prompt_compiler.validate_provider_payload(compiled_payload)

        if slot.slot_type.startswith("shot_cell_"):
            current_cell = _cell_prompt_record_for_slot(item, slot)
            return canonicalize(
                {
                    **base_payload,
                    "sequence_index": current_cell.get("sequence_index"),
                    "sequence_role": current_cell.get("sequence_role"),
                    "cell_prompt": current_cell,
                    "selected_reference_item_ids": list(item.reference_item_ids),
                    "explicit_reference_ids": list(slot.explicit_reference_ids),
                    "implicit_reference_ids": list(slot.implicit_reference_ids),
                    "detail_prompt_key": slot.metadata.get("detail_prompt_key"),
                    "detail_prompts": _isolated_shot_cell_detail_prompts(
                        detail_prompts,
                        slot,
                    ),
                    "shot_continuity_context": {
                        "shot_id": item.shot_id or item.item_id,
                        "shot_index": item.shot_index,
                        "cell_role": current_cell.get("sequence_role")
                        or shot_cell_role(slot.slot_type),
                        "sequence_index": current_cell.get("sequence_index"),
                        "sequence_role": current_cell.get("sequence_role"),
                        "aspect_ratio": item.aspect_ratio or workflow.aspect_ratio,
                        "duration_seconds": item.duration_seconds,
                        "reference_item_ids": list(item.reference_item_ids),
                    },
                }
            )
        if slot.slot_type == "shot_video_segment":
            implicit_references = list(context.get("shot_cell_asset_ids", []))
            explicit_references = list(slot.explicit_reference_ids)
            video_details = _video_detail_payload(detail_prompts)
            cell_prompts, _warnings = storyboard_cell_prompt_records(
                shot_id=item.shot_id or item.item_id,
                summary_prompt=item.summary_prompt
                or item.shot_summary_prompt
                or item.item_prompt
                or "",
                detail_prompts=item.detail_prompts,
                reference_item_ids=item.reference_item_ids,
            )
            return canonicalize(
                {
                    **base_payload,
                    **video_details,
                    "cell_prompts": cell_prompts,
                    "shot_cell_prompt_details": cell_prompts,
                    "dialogue_prompt": slot.dialogue_prompt,
                    "audio_description_prompt": slot.audio_description_prompt,
                    "voice_style_prompt": slot.voice_style_prompt,
                    "negative_constraints": slot.negative_constraints,
                    "shot_cell_asset_ids": implicit_references,
                    "selected_reference_item_ids": list(item.reference_item_ids),
                    "implicit_reference_ids": implicit_references,
                    "explicit_reference_ids": explicit_references,
                    "reference_asset_ids": list(
                        dict.fromkeys([*implicit_references, *explicit_references])
                    ),
                }
            )
        if slot.slot_type == "final_video":
            segment_ids = list(context.get("shot_video_segment_asset_ids", []))
            bgm_asset_id = context.get("bgm_asset_id") if workflow.audio_mode != "none" else None
            canonical_timeline = context.get("canonical_timeline")
            if not isinstance(canonical_timeline, dict):
                raise V2PromptMaterializationError(
                    "v2_final_timeline_missing",
                    "Final video generation requires a canonical saved timeline.",
                )
            timeline_plan, timeline_clips = _canonical_final_timeline_payload(canonical_timeline)
            source_asset_ids = [
                str(clip["source_asset_id"])
                for clip in timeline_clips
                if clip.get("source_asset_id")
            ]
            reference_asset_ids = list(dict.fromkeys(source_asset_ids))
            if bgm_asset_id is not None and bgm_asset_id not in reference_asset_ids:
                reference_asset_ids.append(str(bgm_asset_id))
            return canonicalize(
                {
                    **base_payload,
                    "slot_prompt": slot.slot_prompt,
                    "composition_tool": "local_composition_ffmpeg",
                    "canonical_timeline": canonical_timeline,
                    "timeline_plan": timeline_plan,
                    "timeline_clips": timeline_clips,
                    "shot_video_segment_asset_ids": segment_ids,
                    "bgm_asset_id": bgm_asset_id,
                    "reference_asset_ids": reference_asset_ids,
                    "render_settings": {
                        "provider": "local_composition_ffmpeg",
                        "aspect_ratio": workflow.aspect_ratio,
                        "audio_mode": workflow.audio_mode,
                    },
                }
            )
        if slot.slot_type == "bgm_audio":
            item_reference_ids = list(context.get("item_reference_asset_ids", []))
            explicit_reference_ids = list(
                dict.fromkeys([*item_reference_ids, *slot.explicit_reference_ids])
            )
            return canonicalize(
                {
                    **base_payload,
                    "reference_asset_ids": explicit_reference_ids,
                    "explicit_reference_ids": explicit_reference_ids,
                    "implicit_reference_ids": [],
                    "reference_mode": _reference_policy(workflow, item),
                }
            )
        multiview_context = _multiview_context(context)
        if multiview_context is not None:
            dependency_reference_ids = list(multiview_context["reference_asset_ids"])
            dependency_slot_ids = list(multiview_context["dependency_slot_ids"])
            return canonicalize(
                {
                    **base_payload,
                    "reference_asset_ids": dependency_reference_ids,
                    "explicit_reference_ids": [],
                    "implicit_reference_ids": dependency_reference_ids,
                    "primary_reference_asset_id": multiview_context["primary_reference_asset_id"],
                    "primary_reference_version_id": multiview_context[
                        "primary_reference_version_id"
                    ],
                    "dependency_slot_ids": dependency_slot_ids,
                    "consistency_contract": dict(multiview_context["consistency_contract"]),
                    "identity_contract": dict(multiview_context["identity_contract"]),
                    "main_to_multiview_reference": dict(multiview_context["source_slot"]),
                }
            )
        if slot.node_id == "product-generation":
            item_reference_ids = list(context.get("item_reference_asset_ids", []))
            dependency_reference_ids = list(context.get("dependency_asset_ids", []))
            explicit_reference_ids = list(
                dict.fromkeys([*item_reference_ids, *slot.explicit_reference_ids])
            )
            product_references = list(
                dict.fromkeys([*dependency_reference_ids, *explicit_reference_ids])
            )
            return canonicalize(
                {
                    **base_payload,
                    "reference_asset_ids": product_references,
                    "explicit_reference_ids": explicit_reference_ids,
                    "implicit_reference_ids": dependency_reference_ids,
                    "reference_mode": _reference_policy(workflow, item),
                }
            )
        if slot.slot_type in {"character_three_view", "scene_multi_view_grid"}:
            dependency_reference_ids = list(context.get("dependency_asset_ids", []))
            return canonicalize(
                {
                    **base_payload,
                    "reference_asset_ids": dependency_reference_ids,
                    "explicit_reference_ids": list(slot.explicit_reference_ids),
                    "implicit_reference_ids": dependency_reference_ids,
                }
            )
        return canonicalize(
            {
                **base_payload,
                "explicit_reference_ids": list(slot.explicit_reference_ids),
                "implicit_reference_ids": list(slot.implicit_reference_ids),
            }
        )

    def _sanitize_provider_prompt(
        self,
        *,
        slot: WorkflowSlotV2,
        route: V2AgentRoute,
        provider_prompt: str | None,
        detail_prompts: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        result = self._prompt_sanitizer.sanitize_slot_prompt(
            slot_type=slot.slot_type,
            specialist_type=route.specialist,
            prompt=provider_prompt,
        )
        audit = result.audit()
        if not audit:
            return provider_prompt, detail_prompts
        return result.sanitized_prompt, {
            **detail_prompts,
            "prompt_sanitization_audit": audit,
        }


def _multiview_context(context: dict[str, Any]) -> dict[str, Any] | None:
    value = context.get("main_to_multiview")
    if not isinstance(value, dict):
        return None
    consistency_contract = value.get("consistency_contract")
    consistency_contract = consistency_contract if isinstance(consistency_contract, dict) else {}
    slot_type = str(consistency_contract.get("slot_type") or "")
    if slot_type and not is_main_to_multiview_slot(slot_type):
        return None
    reference_asset_ids = value.get("reference_asset_ids")
    dependency_slot_ids = value.get("dependency_slot_ids")
    if not isinstance(reference_asset_ids, list) or not reference_asset_ids:
        return None
    if not isinstance(dependency_slot_ids, list) or not dependency_slot_ids:
        return None
    return value


def _summary_prompt(item: WorkflowItemV2, slot: WorkflowSlotV2) -> str | None:
    if item.item_type in {"product", "character", "scene", "bgm"}:
        return item.item_prompt
    if item.item_type == "shot":
        return item.shot_summary_prompt
    if item.item_type == "final_composition":
        return "Assemble selected storyboard video segments into the final ad."
    return slot.slot_prompt or item.item_prompt


def _detail_prompts_for_slot(item: WorkflowItemV2, slot: WorkflowSlotV2) -> dict[str, Any]:
    if item.item_type != "shot":
        return {}
    details = dict(item.detail_prompts)
    cell_prompts = details.pop("cell_prompts", None)
    if slot.slot_type.startswith("shot_cell_"):
        del cell_prompts
        details["current_cell_prompt"] = _cell_prompt_record_for_slot(item, slot)
        return details
    if slot.slot_type == "shot_video_segment":
        return details
    return details


def _cell_prompt_record_for_slot(item: WorkflowItemV2, slot: WorkflowSlotV2) -> dict[str, Any]:
    summary = item.summary_prompt or item.shot_summary_prompt or item.item_prompt or ""
    if item.cell_prompts:
        for record in item.cell_prompts:
            if record.get("slot_type") == slot.slot_type:
                return dict(record)
    return cell_prompt_record_for_slot(
        shot_id=item.shot_id or item.item_id,
        summary_prompt=summary,
        detail_prompts=item.detail_prompts,
        slot_type=slot.slot_type,
        reference_item_ids=item.reference_item_ids,
    )


def _target_payload(
    target: V2GenerationTarget,
    slot: WorkflowSlotV2,
) -> dict[str, Any]:
    payload = target.model_dump(mode="json")
    payload["node_id"] = payload.get("node_id") or slot.node_id
    payload["item_id"] = payload.get("item_id") or slot.item_id
    payload["slot_id"] = payload.get("slot_id") or slot.slot_id
    payload["slot_type"] = payload.get("slot_type") or slot.slot_type
    payload["media_type"] = payload.get("media_type") or slot.media_type
    return payload


def _action_for_slot(slot: WorkflowSlotV2) -> str:
    if slot.slot_type == "shot_video_segment":
        return "materialize_shot_video"
    if slot.slot_type.startswith("shot_cell_"):
        return "materialize_shot_cells"
    if slot.slot_type == "final_video":
        return "build_timeline"
    if slot.slot_type == "free_output":
        return "free_generate"
    return "materialize_item_slots"


def _sibling_provider_prompts(item: WorkflowItemV2, current_slot: WorkflowSlotV2) -> list[str]:
    prompts: list[str] = []
    for slot in item.slots:
        if slot.slot_id == current_slot.slot_id:
            continue
        if current_slot.slot_type.startswith("shot_cell_") and not slot.slot_type.startswith(
            "shot_cell_"
        ):
            continue
        if isinstance(slot.slot_prompt, str) and slot.slot_prompt.strip():
            prompts.append(slot.slot_prompt.strip())
        snapshot = slot.metadata.get("provider_prompt_snapshot")
        if isinstance(snapshot, dict):
            provider_prompt = snapshot.get("provider_prompt")
            if isinstance(provider_prompt, str) and provider_prompt.strip():
                prompts.append(provider_prompt.strip())
    return list(dict.fromkeys(prompts))


def _sibling_detail_prompts(item: WorkflowItemV2, current_slot: WorkflowSlotV2) -> list[str]:
    if item.item_type != "shot" or not current_slot.slot_type.startswith("shot_cell_"):
        return []
    cell_prompts = item.detail_prompts.get("cell_prompts")
    if not isinstance(cell_prompts, dict):
        return []
    prompts: list[str] = []
    for slot_type, value in cell_prompts.items():
        if slot_type == current_slot.slot_type:
            continue
        if isinstance(value, dict):
            for key in (
                "visual_prompt",
                "provider_prompt",
                "prompt",
                "cell_prompt",
                "image_prompt",
            ):
                item = value.get(key)
                if item is not None and str(item).strip():
                    prompts.append(str(item).strip())
        elif isinstance(value, str) and value.strip():
            prompts.append(value.strip())
    return list(dict.fromkeys(prompts))


def _isolated_shot_cell_detail_prompts(
    detail_prompts: dict[str, Any],
    slot: WorkflowSlotV2,
) -> dict[str, Any]:
    allowed = {
        "storyboard_content",
        "shot_style",
        "camera_language",
        "current_cell_prompt",
        "prompt_contract",
        "prompt_contract_name",
        "prompt_contract_version",
        "selected_skill_ids",
        "selected_skill_paths",
        "skill_context_warnings",
        "quality_notes",
        "materializer_version",
    }
    payload = {key: value for key, value in detail_prompts.items() if key in allowed}
    cell_prompts = detail_prompts.get("cell_prompts")
    if isinstance(cell_prompts, dict):
        current_cell = cell_prompts.get(slot.slot_type)
        if isinstance(current_cell, dict):
            payload["current_cell_prompt"] = dict(current_cell)
    return payload


def _with_canonical_provider_payload(
    payload: dict[str, Any],
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    target: V2GenerationTarget,
    detail_prompts: dict[str, Any],
) -> dict[str, Any]:
    reference_asset_ids = [
        str(asset_id)
        for asset_id in payload.get("reference_asset_ids", [])
        if isinstance(asset_id, str) and asset_id.strip()
    ]
    provider_prompt = (
        payload.get("provider_prompt")
        or payload.get("summary_prompt")
        or slot.slot_prompt
        or item.item_prompt
        or item.shot_summary_prompt
        or f"Generate {slot.media_type} for {slot.slot_type}."
    )
    quality_contract = _quality_contract_for_payload(slot, detail_prompts)
    provider_prompt_contract = payload.get("provider_prompt_contract")
    if isinstance(provider_prompt_contract, dict) and provider_prompt_contract:
        quality_contract = {
            **quality_contract,
            "provider_prompt_contract_id": provider_prompt_contract.get("contract_id"),
        }
    canonical = V2CanonicalProviderPayload(
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=item.item_id,
        slot_id=slot.slot_id,
        slot_type=slot.slot_type,
        media_type=slot.media_type,  # type: ignore[arg-type]
        provider_prompt=str(provider_prompt),
        negative_prompt=payload.get("negative_prompt"),
        negative_constraints=payload.get("negative_constraints"),
        reference_asset_ids=reference_asset_ids,
        provider_params=dict(payload.get("provider_params") or {}),
        quality_contract=quality_contract,
        prompt_contract_name=str(
            detail_prompts.get("prompt_contract_name")
            or _prompt_contract_name_for_payload(slot.slot_type)
        ),
        prompt_contract_version=str(
            detail_prompts.get("prompt_contract_version") or prompt_contract_version()
        ),
        materializer_mode=payload.get("materializer_mode") or "mock",  # type: ignore[arg-type]
        model_id=payload.get("materializer_model_id"),
        selected_skill_ids=list(payload.get("selected_skill_ids") or []),
        visual_style_contract=payload.get("visual_style_contract"),
        visual_style_audit=payload.get("visual_style_audit"),
    )
    canonical_payload = sanitize_context_for_llm_text(canonical.model_dump(mode="json"))
    if slot.media_type == "audio":
        canonical_payload.pop("visual_style_contract", None)
        canonical_payload.pop("visual_style_audit", None)
    return {
        **payload,
        **canonical_payload,
        "target": target.model_dump(mode="json"),
        "canonical_provider_payload": canonical_payload,
    }


def _prompt_provenance(
    *,
    slot: WorkflowSlotV2,
    prompt_compilation: V2ProviderPromptCompilationResult,
    detail_prompts: dict[str, Any],
    materializer_warnings: list[dict[str, Any]],
    reference_asset_ids: list[str],
) -> dict[str, Any]:
    metadata = prompt_compilation.provider_payload_metadata
    warnings = [
        str(warning.get("code"))
        for warning in materializer_warnings
        if isinstance(warning, dict) and str(warning.get("code") or "").strip()
    ]
    prompt_registry_ref = metadata.get("prompt_registry_ref")
    prompt_contract = metadata.get("provider_prompt_contract")
    provenance = {
        "compiler": _compiler_name_for_slot(slot.slot_type),
        "source_fields": _prompt_source_fields(slot, detail_prompts),
        "legacy_fields_ignored": [],
        "legacy_fields_adapted": [
            warning for warning in warnings if warning == "v2_legacy_prompt_field_adapted"
        ],
        "selected_reference_asset_ids": list(reference_asset_ids),
        "warnings": list(dict.fromkeys(warnings)),
        "validation_status": "passed",
        "slot_context_id": metadata.get("slot_context_id"),
        "prompt_registry_ref": prompt_registry_ref if isinstance(prompt_registry_ref, dict) else {},
        "provider_prompt_contract_id": (
            prompt_contract.get("contract_id") if isinstance(prompt_contract, dict) else None
        ),
    }
    return sanitize_context_for_llm_text(provenance)


def _compiler_name_for_slot(slot_type: str) -> str:
    if slot_type.startswith("shot_cell_"):
        return "shot_cell_image_prompt_compiler"
    return f"{slot_type}_prompt_compiler"


def _prompt_source_fields(
    slot: WorkflowSlotV2,
    detail_prompts: dict[str, Any],
) -> list[str]:
    if slot.slot_type.startswith("shot_cell_"):
        return [f"shot.cell_prompts.{slot.slot_type}.provider_prompt"]
    if slot.slot_type == "shot_video_segment":
        return [
            "shot.shot_summary_prompt",
            "shot.detail_prompts.cell_prompts",
            "shot.selected_cell_assets",
        ]
    if slot.slot_type == "final_video":
        return ["composition.timeline", "composition.selected_media_assets"]
    if slot.slot_type == "bgm_audio":
        return ["item.item_prompt", "slot.slot_prompt"]
    if detail_prompts.get("multiview_prompt_isolated") is True:
        return [
            "item.identity_contract",
            "slot.selected_main_reference_asset",
            "slot.provider_prompt",
        ]
    return ["specialist_result.provider_prompt"]


def _quality_contract_for_payload(
    slot: WorkflowSlotV2,
    detail_prompts: dict[str, Any],
) -> dict[str, Any]:
    contract = detail_prompts.get("prompt_contract")
    if isinstance(contract, dict) and contract:
        return dict(contract)
    return {
        "contract_name": _prompt_contract_name_for_payload(slot.slot_type),
        "contract_version": prompt_contract_version(),
        "slot_type": slot.slot_type,
        "media_type": slot.media_type,
        "checks": ["provider_prompt_present", "reference_asset_ids_sanitized"],
    }


def _prompt_contract_name_for_payload(slot_type: str) -> str:
    if is_prompt_contract_slot(slot_type):
        return prompt_contract_name_for_slot(slot_type)
    return "V2GenericProviderPayload"


def _provider_prompt(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    route: V2AgentRoute,
) -> str | None:
    if route.specialist == "composition_tool":
        return None
    if route.specialist in {
        "quick_image_generator",
        "quick_video_generator",
        "quick_audio_generator",
    }:
        media_type = slot.media_type or "media"
        return f"Generate a standalone {media_type} asset: {slot.slot_prompt or item.item_prompt}"
    return slot.slot_prompt or item.item_prompt or item.shot_summary_prompt


def _specialist_prompt(
    route: V2AgentRoute,
    summary_prompt: str | None,
    provider_prompt: str | None,
) -> str:
    if route.specialist == "composition_tool":
        return "Use the composition timeline and selected media assets to render the final ad."
    prompt = provider_prompt or summary_prompt or ""
    return f"{route.specialist}: {prompt}".strip()


def _reference_asset_ids(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    route: V2AgentRoute,
    context: dict[str, Any],
) -> list[str]:
    if slot.slot_type == "shot_video_segment":
        return list(
            dict.fromkeys([*context.get("shot_cell_asset_ids", []), *slot.explicit_reference_ids])
        )
    if slot.slot_type == "final_video":
        segment_ids = list(context.get("shot_video_segment_asset_ids", []))
        bgm_asset_id = context.get("bgm_asset_id") if workflow.audio_mode != "none" else None
        return segment_ids + ([bgm_asset_id] if bgm_asset_id else [])
    multiview_context = _multiview_context(context)
    if multiview_context is not None:
        return list(multiview_context["reference_asset_ids"])
    if slot.node_id == "product-generation":
        return list(
            dict.fromkeys(
                [
                    *context.get("dependency_asset_ids", []),
                    *context.get("item_reference_asset_ids", []),
                    *slot.explicit_reference_ids,
                ]
            )
        )
    if slot.slot_type == "bgm_audio":
        return list(
            dict.fromkeys(
                [
                    *context.get("item_reference_asset_ids", []),
                    *slot.explicit_reference_ids,
                ]
            )
        )
    if slot.slot_type in {"character_three_view", "scene_multi_view_grid"}:
        return list(context.get("dependency_asset_ids", []))
    if item.item_type == "shot" and route.specialist == "storyboard_artist":
        provider_assets = context.get("provider_reference_assets")
        if isinstance(provider_assets, list) and provider_assets:
            return list(
                dict.fromkeys(
                    str(asset.get("asset_id"))
                    for asset in provider_assets
                    if isinstance(asset, dict) and str(asset.get("asset_id") or "").strip()
                )
            )
        return list(context.get("visual_reference_asset_ids", []))
    return list(dict.fromkeys([*slot.implicit_reference_ids, *slot.explicit_reference_ids]))


def _reference_policy(workflow: WorkflowV2, item: WorkflowItemV2) -> str:
    value = item.metadata.get("reference_mode") or workflow.metadata.get("reference_mode")
    return str(value or "best_effort")


def _video_detail_payload(detail_prompts: dict[str, Any]) -> dict[str, Any]:
    return {
        "storyboard_content": detail_prompts.get("storyboard_content"),
        "dialogue": detail_prompts.get("dialogue"),
        "audio_description": detail_prompts.get("audio_description"),
        "voice_style": detail_prompts.get("voice_style"),
        "video_negative_constraints": detail_prompts.get("video_negative_constraints"),
        "time_segments": detail_prompts.get("time_segments", []),
        "desired_duration_seconds": detail_prompts.get("desired_duration_seconds"),
        "provider_duration_seconds": detail_prompts.get("provider_duration_seconds"),
    }


def _asset_summaries(asset_ids: list[str]) -> list[dict[str, str]]:
    return [{"asset_id": str(asset_id)} for asset_id in asset_ids if str(asset_id)]


def _script_summary(workflow: WorkflowV2) -> dict[str, Any]:
    script = next((node for node in workflow.nodes if node.node_id == "script"), None)
    if script is None or not script.items:
        return {}
    item = script.items[0]
    return {
        "prompt": item.item_prompt,
        "script_text": item.metadata.get("script_text"),
    }


def _specialist_handoff(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("specialist_handoff")
    return dict(value) if isinstance(value, dict) else {}


def _effective_handoff_prompt(handoff: dict[str, Any]) -> str | None:
    if not handoff:
        return None
    for key in ("latest_user_instruction", "user_prompt", "system_suggested_prompt"):
        value = handoff.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
