from collections.abc import Callable
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    V2GenerationPlan,
    V2GenerationTarget,
    V2ProviderResult,
    V2ProviderTask,
    V2SlotExecutionJob,
    V2SlotExecutionResult,
    WorkflowAssetRelationV2,
    WorkflowAssetVersionV2,
    WorkflowV2ChatTargetRequest,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2Event,
)
from app.schemas.workflow_v2_provider_results import V2ProviderExecutionContext
from app.schemas.workflow_v2_screenplay import V2GenerationLineage
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_agent_router import V2AgentRouteError, V2AgentRouter
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineService
from app.services.v2_media_quality_gate import V2MediaQualityGate, detect_media_format
from app.services.v2_generation_lineage import build_generation_lineage
from app.services.v2_item_identity_specs import asset_identity_metadata, slot_identity_metadata
from app.services.v2_main_to_multiview_consistency import (
    dependency_slot_ids_for_multiview,
    is_main_to_multiview_slot,
    main_reference_missing_metadata,
    selected_main_reference_context,
)
from app.services.v2_prompt_materializer import (
    V2PromptMaterializationError,
    V2PromptMaterializer,
)
from app.services.v2_provider_executor import V2ProviderExecutor, V2_PROMPT_SOURCE_CONTRACT
from app.services.v2_provider_recovery import (
    V2ProviderRecoveryRunner,
    provider_retry_metadata_from_result,
)
from app.services.v2_provider_references import reference_metadata_from_payload
from app.services.v2_provider_result_store import (
    V2ProviderResultStore,
    V2ProviderResultStoreError,
)
from app.services.v2_provider_tasks import V2ProviderTaskStore
from app.services.v2_reference_audit import V2ReferenceAuditBuilder
from app.services.v2_reference_bundle_builder import V2ReferenceBundleBuilder
from app.services.v2_runtime_prompt_governance import (
    V2PromptGovernanceError,
    apply_compiled_prompt_to_payload,
    compile_v2_provider_prompt,
)
from app.services.v2_shot_reference_resolver import (
    V2ResolvedShotReferences,
    V2ShotReferenceResolver,
    V2ShotReferenceResolverError,
)
from app.services.v2_storyboard_namespace import (
    V2StoryboardNamespaceError,
    validate_storyboard_slot_namespace,
)
from app.services.v2_specialist_prompt_service import V2SpecialistPromptService
from app.services.v2_specialist_handoff import (
    V2SpecialistHandoffBuilder,
    V2SpecialistHandoffError,
)
from app.services.v2_storyboard_defaults import shot_cell_slot_types

TransitionSlot = Callable[..., None]
SlotRelationWriter = Callable[..., WorkflowAssetRelationV2]
EventAppender = Callable[..., WorkflowV2Event]


def _uses_canonical_specialist_handoff(slot: WorkflowSlotV2) -> bool:
    return slot.node_id in {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
        "bgm",
    }


def _validated_generation_lineage(provider_payload: dict[str, Any]) -> dict[str, Any]:
    payload = provider_payload.get("generation_lineage")
    if not isinstance(payload, dict):
        raise V2GenerationPipelineError(
            "v2_generation_lineage_missing",
            "Generated V2 assets require canonical generation lineage.",
        )
    try:
        return V2GenerationLineage.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        raise V2GenerationPipelineError(
            "v2_generation_lineage_invalid",
            "Generated V2 asset lineage did not match the canonical contract.",
        ) from exc


def _merge_provider_payload_snapshots(
    *payloads: dict[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    canonical_lineage: dict[str, Any] | None = None
    for payload in payloads:
        if payload:
            if canonical_lineage is None and isinstance(payload.get("generation_lineage"), dict):
                canonical_lineage = payload["generation_lineage"]
            merged.update(payload)
    if canonical_lineage is not None:
        merged["generation_lineage"] = canonical_lineage
    return sanitize_context_for_llm_text(merged)


def _generation_input_fingerprint(
    *,
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
) -> str:
    payload = sanitize_context_for_llm_text(
        {
            "workflow": {
                "workflow_id": workflow.workflow_id,
                "duration_seconds": workflow.duration_seconds,
                "aspect_ratio": workflow.aspect_ratio,
                "audio_mode": workflow.audio_mode,
                "selected_script_version_id": workflow.metadata.get("selected_script_version_id"),
            },
            "item": {
                "item_id": item.item_id,
                "node_id": item.node_id,
                "item_type": item.item_type,
                "item_prompt": item.item_prompt,
                "system_suggested_prompt": item.system_suggested_prompt,
                "user_prompt": item.user_prompt,
                "prompt_source": item.prompt_source,
                "manual_prompt_dirty": item.manual_prompt_dirty,
                "shot_summary_prompt": item.shot_summary_prompt,
                "detail_prompts": item.detail_prompts,
                "reference_item_ids": item.reference_item_ids,
                "reference_source": item.reference_source,
                "aspect_ratio": item.aspect_ratio,
                "duration_seconds": item.duration_seconds,
            },
            "slot": {
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "required": slot.required,
                "slot_prompt": slot.slot_prompt,
                "system_suggested_prompt": slot.system_suggested_prompt,
                "user_prompt": slot.user_prompt,
                "negative_prompt": slot.negative_prompt,
                "dialogue_prompt": slot.dialogue_prompt,
                "audio_description_prompt": slot.audio_description_prompt,
                "voice_style_prompt": slot.voice_style_prompt,
                "negative_constraints": slot.negative_constraints,
                "prompt_source": slot.prompt_source,
                "manual_prompt_dirty": slot.manual_prompt_dirty,
                "media_prompt_asset_ids": slot.media_prompt_asset_ids,
                "implicit_reference_ids": slot.implicit_reference_ids,
                "explicit_reference_ids": slot.explicit_reference_ids,
                "dependency_slot_ids": slot.dependency_slot_ids,
                "provider": slot.provider,
                "provider_params": slot.provider_params,
            },
        }
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_asset_id(provider_result_id: str | None) -> str | None:
    if not provider_result_id:
        return None
    return f"asset_{provider_result_id}"


def _canonical_version_id(provider_result_id: str | None) -> str | None:
    if not provider_result_id:
        return None
    return f"ver_{provider_result_id}_0"


class V2GenerationPipelineError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2GenerationPipeline:
    def __init__(
        self,
        *,
        data_dir: Path,
        asset_store: V2AssetStoreService,
        settings: Settings | None = None,
        router: V2AgentRouter | None = None,
        materializer: V2PromptMaterializer | None = None,
        provider_executor: V2ProviderExecutor | None = None,
        task_store: V2ProviderTaskStore | None = None,
        quality_gate: V2MediaQualityGate | None = None,
        reference_bundle_builder: V2ReferenceBundleBuilder | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = data_dir
        self._asset_store = asset_store
        self._router = router or V2AgentRouter()
        self._materializer = materializer or V2PromptMaterializer(
            V2SpecialistPromptService(self._settings)
        )
        self._provider_executor = provider_executor or V2ProviderExecutor(
            settings=self._settings,
            data_dir=data_dir,
        )
        self._task_store = task_store or V2ProviderTaskStore(data_dir)
        self._provider_result_store = V2ProviderResultStore(data_dir)
        self._quality_gate = quality_gate or V2MediaQualityGate()
        self._provider_recovery = V2ProviderRecoveryRunner(
            settings=self._settings,
            data_dir=data_dir,
        )
        self._reference_bundle_builder = reference_bundle_builder or V2ReferenceBundleBuilder(
            data_dir
        )
        self._reference_audit_builder = V2ReferenceAuditBuilder(data_dir)
        self._shot_reference_resolver = V2ShotReferenceResolver(data_dir)
        self._handoff_builder = V2SpecialistHandoffBuilder(data_dir)
        self._final_timeline_service = V2FinalCompositionTimelineService(
            replace(self._settings, media_data_dir=data_dir)
        )

    def input_fingerprint(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> str:
        """Return the durable, non-LLM input identity used to validate manifests."""
        return _generation_input_fingerprint(workflow=workflow, item=item, slot=slot)

    def generate_slot(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        executed_slot_ids: list[str],
        provider_calls: list[dict[str, Any]],
        *,
        select_generated: bool,
        source_action: str,
        slot_transitions: list[dict[str, Any]],
        transition_slot: TransitionSlot,
        set_working_version_for_slot: SlotRelationWriter,
        set_selected_version_for_slot: SlotRelationWriter,
        append_event: EventAppender,
        execution_id: str | None = None,
    ) -> None:
        transition_slot(
            workflow,
            slot,
            "running",
            slot_transitions,
            event_type="slot_generation_started",
        )
        try:
            plan = self.build_plan(workflow, item, slot, source_action=source_action)
            plan = self._with_execution_context(
                plan,
                workflow,
                item,
                slot,
                execution_id=execution_id,
            )
            provider_payload = sanitize_context_for_llm_text(plan.provider_payload)
            self._append_reference_bundle_built_event(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
            )
            append_event(
                workflow.workflow_id,
                "provider_execution_started",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": slot.provider,
                    "slot_type": slot.slot_type,
                    "materializer_mode": plan.materialized_prompt.materializer_mode,
                },
            )
            if slot.slot_type == "final_video":
                append_event(
                    workflow.workflow_id,
                    "final_composition_render_started",
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    payload={
                        "provider": "local_composition_ffmpeg",
                        "timeline_id": provider_payload.get("timeline_plan", {}).get("timeline_id")
                        if isinstance(provider_payload.get("timeline_plan"), dict)
                        else None,
                    },
                )
            provider_result, plan = self._provider_recovery.execute(
                workflow=workflow,
                item=item,
                slot=slot,
                plan=plan,
                executor=self._provider_executor,
                append_event=append_event,
            )
            provider_payload = _merge_provider_payload_snapshots(
                plan.provider_payload or provider_payload,
                provider_result.provider_payload_snapshot,
            )
            slot.metadata.update(provider_retry_metadata_from_result(provider_result))
            self._append_reference_events(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
            )
            self._append_provider_input_flagged_event(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
            )
        except (
            V2AgentRouteError,
            V2PromptMaterializationError,
            V2PromptGovernanceError,
            V2StoryboardNamespaceError,
        ) as exc:
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=exc.code,
                message=str(exc),
                metadata=getattr(exc, "metadata", {}),
            )
            raise V2GenerationPipelineError(exc.code, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - provider/tool failures are persisted.
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code="provider_generation_failed",
                message=str(exc),
            )
            raise V2GenerationPipelineError("provider_generation_failed", str(exc)) from exc

        if provider_result.status == "waiting":
            task = self._task_store.create_waiting_task(
                workflow,
                item,
                slot,
                plan,
                provider_result,
                select_generated=select_generated,
                source_action=source_action,
                execution_id=execution_id,
            )
            slot.metadata["provider_task_id"] = task.task_id
            slot.metadata["remote_task_id"] = provider_result.remote_task_id
            slot.metadata["waiting_reason"] = provider_result.metadata.get(
                "waiting_reason",
                "provider_task_submitted",
            )
            self._persist_prompt_metadata(slot, plan, provider_payload)
            provider_calls.append(
                self._provider_call(
                    slot=slot,
                    plan=plan,
                    provider_payload=provider_payload,
                    provider_result=provider_result,
                    task=task,
                )
            )
            append_event(
                workflow.workflow_id,
                "provider_task_submitted",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                },
            )
            append_event(
                workflow.workflow_id,
                "provider_task_waiting",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                },
            )
            self._append_reference_audit_recorded_event(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
                provider_task_id=task.task_id,
            )
            transition_slot(
                workflow,
                slot,
                "waiting",
                slot_transitions,
                event_type="slot_generation_waiting",
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                },
            )
            return

        if provider_result.status == "skipped":
            self._persist_prompt_metadata(slot, plan, provider_payload)
            provider_calls.append(
                self._provider_call(
                    slot=slot,
                    plan=plan,
                    provider_payload=provider_payload,
                    provider_result=provider_result,
                )
            )
            self._skip_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=provider_result.error_code or "provider_generation_skipped",
                message=provider_result.error_message or "Provider generation was skipped.",
                metadata=provider_result.metadata,
            )
            return

        if provider_result.status == "failed":
            failure_payload: dict[str, Any] = {
                "provider": provider_result.provider,
                "error_code": provider_result.error_code,
                "error_message": provider_result.error_message,
            }
            prompt_audit = provider_result.metadata.get("prompt_audit")
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            for key in (
                "stage",
                "http_status",
                "provider_error_code",
                "provider_request_id",
                "provider_response_summary",
                "request_summary",
                "node_id",
                "item_id",
                "slot_id",
                "slot_type",
                "generation_integrity",
                "integrity_audit",
                "provider_prompt_contract",
                "reference_delivery_audit",
                "reference_wire_audit",
            ):
                if key in provider_result.metadata:
                    failure_payload[key] = sanitize_context_for_llm_text(
                        provider_result.metadata[key]
                    )
            append_event(
                workflow.workflow_id,
                "provider_execution_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            if slot.slot_type == "final_video":
                append_event(
                    workflow.workflow_id,
                    "final_composition_render_failed",
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    payload={
                        "provider": provider_result.provider,
                        "error_code": provider_result.error_code,
                        "error_message": provider_result.error_message,
                    },
                )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=provider_result.error_code or "provider_generation_failed",
                message=provider_result.error_message or "Provider generation failed.",
                metadata={
                    **provider_result.metadata,
                    "provider": provider_result.provider,
                },
            )
            raise V2GenerationPipelineError(
                provider_result.error_code or "provider_generation_failed",
                provider_result.error_message or "Provider generation failed.",
            )

        append_event(
            workflow.workflow_id,
            "quality_gate_started",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload={"provider": provider_result.provider, "media_type": slot.media_type},
        )
        try:
            asset = self._write_generated_asset_from_result(
                workflow,
                slot,
                plan,
                provider_payload,
                provider_result,
            )
        except V2GenerationPipelineError as exc:
            failure_payload = {
                "provider": provider_result.provider,
                "error_code": exc.code,
                "error_message": str(exc),
            }
            prompt_audit = provider_result.metadata.get("prompt_audit")
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            for key in (
                "provider_prompt_contract",
                "reference_delivery_audit",
                "reference_wire_audit",
            ):
                if key in provider_result.metadata:
                    failure_payload[key] = sanitize_context_for_llm_text(
                        provider_result.metadata[key]
                    )
            append_event(
                workflow.workflow_id,
                "quality_gate_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=exc.code,
                message=str(exc),
                metadata=provider_result.metadata,
            )
            raise
        append_event(
            workflow.workflow_id,
            "quality_gate_passed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload=asset.metadata.get("quality_gate_result", {}),
        )
        self._append_reference_audit_recorded_event(
            workflow,
            item,
            slot,
            provider_payload,
            append_event,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
        )

        slot.current_working_asset_id = asset.asset_id
        slot.current_working_version_id = asset.version_id
        if select_generated:
            slot.selected_asset_id = asset.asset_id
            slot.selected_version_id = asset.version_id
            next_status = "completed"
        else:
            next_status = "completed" if slot.selected_asset_id else "ready"

        self._persist_prompt_metadata(slot, plan, provider_payload)
        slot.implicit_reference_ids = list(provider_payload.get("implicit_reference_ids", []))
        slot.explicit_reference_ids = list(provider_payload.get("explicit_reference_ids", []))

        executed_slot_ids.append(slot.slot_id)
        provider_calls.append(
            self._provider_call(
                slot=slot,
                plan=plan,
                provider_payload=provider_payload,
                provider_result=provider_result,
                asset=asset,
            )
        )
        route_snapshot = slot.metadata["agent_route_snapshot"]
        append_event(
            workflow.workflow_id,
            "asset_version_created",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "agent_route": route_snapshot,
                "specialist": route_snapshot.get("specialist"),
            },
        )
        set_working_version_for_slot(
            workflow,
            slot,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            source_action=source_action,
        )
        if select_generated:
            set_selected_version_for_slot(
                workflow,
                slot,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                source_action=source_action,
            )
        append_event(
            workflow.workflow_id,
            "provider_execution_completed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "provider": provider_result.provider,
                "provider_model": provider_result.provider_model,
            },
        )
        if slot.slot_type == "final_video":
            append_event(
                workflow.workflow_id,
                "final_composition_render_completed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                payload={
                    "provider": provider_result.provider,
                    "timeline_id": provider_result.metadata.get("timeline_id"),
                    "timeline_version": provider_result.metadata.get("timeline_version"),
                },
            )
        transition_slot(
            workflow,
            slot,
            next_status,
            slot_transitions,
            event_type="slot_generation_completed",
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={"specialist": route_snapshot.get("specialist")},
        )

    def execute_slot_provider(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        *,
        source_action: str,
        execution_id: str | None = None,
        append_worker_event: EventAppender | None = None,
    ) -> V2SlotExecutionResult:
        attempt_id = f"attempt_{uuid4().hex}"
        job = V2SlotExecutionJob(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
            source_action=source_action,
            select_generated=True,
        )
        try:
            plan = self.build_plan(workflow, item, slot, source_action=source_action)
            plan = self._with_execution_context(
                plan,
                workflow,
                item,
                slot,
                execution_id=execution_id,
            )
            provider_payload = sanitize_context_for_llm_text(plan.provider_payload)
            provider_result, plan = self._provider_recovery.execute(
                workflow=workflow,
                item=item,
                slot=slot,
                plan=plan,
                executor=self._provider_executor,
            )
            provider_payload = _merge_provider_payload_snapshots(
                plan.provider_payload or provider_payload,
                provider_result.provider_payload_snapshot,
            )
            input_fingerprint = self.input_fingerprint(workflow, item, slot)
            job = job.model_copy(update={"input_fingerprint": input_fingerprint})
            manifest_path: str | None = None
            provider_result_identifier: str | None = None
            if provider_result.status == "completed":
                context = V2ProviderExecutionContext(
                    workflow_id=workflow.workflow_id,
                    execution_id=execution_id or f"sync_{uuid4().hex}",
                    attempt_id=attempt_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    slot_type=slot.slot_type,
                    media_type=slot.media_type,
                    input_fingerprint=input_fingerprint,
                    source_action=source_action,
                    select_generated=True,
                )
                staging_path = self._provider_result_store.stage_provider_output(
                    context=context,
                    asset_bytes=provider_result.asset_bytes,
                    local_file_path=provider_result.local_file_path,
                )
                manifest = self._provider_result_store.persist_immediate_result(
                    context=context,
                    provider_name=provider_result.provider or slot.provider or "unknown-provider",
                    provider_model=provider_result.provider_model,
                    staging_path=staging_path,
                    generation_plan_snapshot=plan.model_dump(mode="json"),
                    provider_payload_snapshot=provider_payload,
                    provider_result_metadata=provider_result.metadata,
                    reference_asset_ids=list(
                        provider_result.reference_asset_ids or plan.reference_asset_ids
                    ),
                )
                provider_result_identifier = manifest.provider_result_id
                manifest_path = (
                    self._provider_result_store.manifest_path(
                        workflow_id=manifest.workflow_id,
                        execution_id=manifest.execution_id,
                        slot_id=manifest.slot_id,
                        attempt_id=manifest.attempt_id,
                    )
                    .relative_to(self._data_dir)
                    .as_posix()
                )
                if append_worker_event is not None:
                    append_worker_event(
                        workflow.workflow_id,
                        "provider_result_persisted",
                        execution_id=context.execution_id,
                        node_id=context.node_id,
                        item_id=context.item_id,
                        slot_id=context.slot_id,
                        payload={
                            "attempt_id": context.attempt_id,
                            "provider_result_id": manifest.provider_result_id,
                            "status": "pending",
                        },
                    )
                provider_result = provider_result.model_copy(
                    update={
                        "asset_bytes": None,
                        "local_file_path": manifest.outputs[0].staging_path,
                        "metadata": {
                            **provider_result.metadata,
                            "source_attempt_id": context.attempt_id,
                            "source_execution_id": context.execution_id,
                            "source_input_fingerprint": context.input_fingerprint,
                            "source_provider_result_id": manifest.provider_result_id,
                            "source_output_index": manifest.outputs[0].output_index,
                        },
                    }
                )
            return V2SlotExecutionResult(
                job=job,
                status=provider_result.status,
                plan=plan,
                provider_result=provider_result,
                provider_payload_snapshot=provider_payload,
                provider_result_id=provider_result_identifier,
                manifest_path=manifest_path,
                error_code=provider_result.error_code,
                error_message=provider_result.error_message,
            )
        except V2ProviderResultStoreError as exc:
            provider_result = V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=slot.provider,
                error_code=exc.code,
                error_message=str(exc),
            )
            return V2SlotExecutionResult(
                job=job,
                status="failed",
                provider_result=provider_result,
                error_code=exc.code,
                error_message=str(exc),
            )
        except (
            V2AgentRouteError,
            V2PromptMaterializationError,
            V2StoryboardNamespaceError,
        ) as exc:
            provider_result = V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=slot.provider,
                error_code=exc.code,
                error_message=str(exc),
                metadata=getattr(exc, "metadata", {}),
            )
            return V2SlotExecutionResult(
                job=job,
                status="failed",
                provider_result=provider_result,
                error_code=exc.code,
                error_message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - provider/tool failures become result state.
            provider_result = V2ProviderResult(
                status="failed",
                media_type=slot.media_type,
                provider=slot.provider,
                error_code="provider_generation_failed",
                error_message=str(exc),
            )
            return V2SlotExecutionResult(
                job=job,
                status="failed",
                provider_result=provider_result,
                error_code="provider_generation_failed",
                error_message=str(exc),
            )

    def apply_slot_execution_result(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        execution_result: V2SlotExecutionResult,
        executed_slot_ids: list[str],
        provider_calls: list[dict[str, Any]],
        *,
        select_generated: bool,
        source_action: str,
        slot_transitions: list[dict[str, Any]],
        transition_slot: TransitionSlot,
        set_working_version_for_slot: SlotRelationWriter,
        set_selected_version_for_slot: SlotRelationWriter,
        append_event: EventAppender,
    ) -> None:
        plan = execution_result.plan
        provider_result = execution_result.provider_result
        provider_payload = _merge_provider_payload_snapshots(
            plan.provider_payload if plan is not None else None,
            provider_result.provider_payload_snapshot,
            execution_result.provider_payload_snapshot,
        )
        slot.metadata.update(provider_retry_metadata_from_result(provider_result))
        if plan is not None:
            self._append_reference_bundle_built_event(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
            )
        append_event(
            workflow.workflow_id,
            "provider_execution_started",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload={
                "provider": provider_result.provider or slot.provider,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "status": "running",
            },
        )
        if slot.slot_type == "final_video":
            append_event(
                workflow.workflow_id,
                "final_composition_render_started",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": "local_composition_ffmpeg",
                    "timeline_id": provider_payload.get("timeline_plan", {}).get("timeline_id")
                    if isinstance(provider_payload.get("timeline_plan"), dict)
                    else None,
                },
            )
        self._append_reference_events(workflow, item, slot, provider_payload, append_event)
        self._append_provider_input_flagged_event(
            workflow,
            item,
            slot,
            provider_payload,
            append_event,
        )

        if provider_result.status == "waiting":
            if plan is None:
                self._fail_slot(
                    workflow,
                    slot,
                    slot_transitions,
                    transition_slot,
                    code="provider_task_plan_missing",
                    message="Provider task cannot be persisted without a generation plan.",
                    metadata=provider_result.metadata,
                )
                raise V2GenerationPipelineError(
                    "provider_task_plan_missing",
                    "Provider task cannot be persisted without a generation plan.",
                )
            task = self._task_store.create_waiting_task(
                workflow,
                item,
                slot,
                plan,
                provider_result,
                select_generated=select_generated,
                source_action=source_action,
                execution_id=execution_result.job.execution_id,
                attempt_id=execution_result.job.attempt_id,
                input_fingerprint=execution_result.job.input_fingerprint,
            )
            slot.metadata["provider_task_id"] = task.task_id
            slot.metadata["remote_task_id"] = provider_result.remote_task_id
            slot.metadata["waiting_reason"] = provider_result.metadata.get(
                "waiting_reason",
                "provider_task_submitted",
            )
            self._persist_prompt_metadata(slot, plan, provider_payload)
            provider_calls.append(
                self._provider_call(
                    slot=slot,
                    plan=plan,
                    provider_payload=provider_payload,
                    provider_result=provider_result,
                    task=task,
                )
            )
            append_event(
                workflow.workflow_id,
                "provider_task_submitted",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                    "status": "waiting",
                    "slot_type": slot.slot_type,
                    "media_type": slot.media_type,
                },
            )
            append_event(
                workflow.workflow_id,
                "provider_task_waiting",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                    "status": "waiting",
                    "slot_type": slot.slot_type,
                    "media_type": slot.media_type,
                },
            )
            self._append_reference_audit_recorded_event(
                workflow,
                item,
                slot,
                provider_payload,
                append_event,
                provider_task_id=task.task_id,
            )
            transition_slot(
                workflow,
                slot,
                "waiting",
                slot_transitions,
                event_type="slot_generation_waiting",
                payload={
                    "provider": provider_result.provider,
                    "remote_task_id": provider_result.remote_task_id,
                    "provider_task_id": task.task_id,
                    "waiting_reason": slot.metadata["waiting_reason"],
                    "status": "waiting",
                    "slot_type": slot.slot_type,
                    "media_type": slot.media_type,
                },
            )
            return

        if provider_result.status == "skipped":
            if plan is not None:
                self._persist_prompt_metadata(slot, plan, provider_payload)
                provider_calls.append(
                    self._provider_call(
                        slot=slot,
                        plan=plan,
                        provider_payload=provider_payload,
                        provider_result=provider_result,
                    )
                )
            self._skip_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=provider_result.error_code or "provider_generation_skipped",
                message=provider_result.error_message or "Provider generation was skipped.",
                metadata=provider_result.metadata,
            )
            return

        if provider_result.status == "failed":
            failure_payload: dict[str, Any] = {
                "provider": provider_result.provider,
                "error_code": provider_result.error_code,
                "error_message": provider_result.error_message,
                "status": "failed",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
            }
            prompt_audit = provider_result.metadata.get("prompt_audit")
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            for key in (
                "stage",
                "http_status",
                "provider_error_code",
                "provider_request_id",
                "provider_response_summary",
                "request_summary",
                "node_id",
                "item_id",
                "slot_id",
                "slot_type",
                "generation_integrity",
                "integrity_audit",
                "provider_prompt_contract",
                "reference_delivery_audit",
                "reference_wire_audit",
            ):
                if key in provider_result.metadata:
                    failure_payload[key] = sanitize_context_for_llm_text(
                        provider_result.metadata[key]
                    )
            append_event(
                workflow.workflow_id,
                "provider_execution_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=provider_result.error_code or "provider_generation_failed",
                message=provider_result.error_message or "Provider generation failed.",
                metadata={
                    **provider_result.metadata,
                    "provider": provider_result.provider,
                },
            )
            raise V2GenerationPipelineError(
                provider_result.error_code or "provider_generation_failed",
                provider_result.error_message or "Provider generation failed.",
            )

        if plan is None:
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code="provider_plan_missing",
                message="Provider result cannot be applied without a generation plan.",
                metadata=provider_result.metadata,
            )
            raise V2GenerationPipelineError(
                "provider_plan_missing",
                "Provider result cannot be applied without a generation plan.",
            )

        append_event(
            workflow.workflow_id,
            "quality_gate_started",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload={"provider": provider_result.provider, "media_type": slot.media_type},
        )
        try:
            asset = self._write_generated_asset_from_result(
                workflow,
                slot,
                plan,
                provider_payload,
                provider_result,
                asset_id=_canonical_asset_id(execution_result.provider_result_id),
                version_id=_canonical_version_id(execution_result.provider_result_id),
            )
        except V2GenerationPipelineError as exc:
            failure_payload = {
                "provider": provider_result.provider,
                "error_code": exc.code,
                "error_message": str(exc),
            }
            prompt_audit = provider_result.metadata.get("prompt_audit")
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            for key in (
                "provider_prompt_contract",
                "reference_delivery_audit",
                "reference_wire_audit",
            ):
                if key in provider_result.metadata:
                    failure_payload[key] = sanitize_context_for_llm_text(
                        provider_result.metadata[key]
                    )
            append_event(
                workflow.workflow_id,
                "quality_gate_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=exc.code,
                message=str(exc),
                metadata=provider_result.metadata,
            )
            raise
        append_event(
            workflow.workflow_id,
            "quality_gate_passed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload=asset.metadata.get("quality_gate_result", {}),
        )
        self._append_reference_audit_recorded_event(
            workflow,
            item,
            slot,
            provider_payload,
            append_event,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
        )
        slot.current_working_asset_id = asset.asset_id
        slot.current_working_version_id = asset.version_id
        if select_generated:
            slot.selected_asset_id = asset.asset_id
            slot.selected_version_id = asset.version_id
            next_status = "completed"
        else:
            next_status = "completed" if slot.selected_asset_id else "ready"

        self._persist_prompt_metadata(slot, plan, provider_payload)
        slot.implicit_reference_ids = list(provider_payload.get("implicit_reference_ids", []))
        slot.explicit_reference_ids = list(provider_payload.get("explicit_reference_ids", []))
        executed_slot_ids.append(slot.slot_id)
        provider_calls.append(
            self._provider_call(
                slot=slot,
                plan=plan,
                provider_payload=provider_payload,
                provider_result=provider_result,
                asset=asset,
            )
        )
        route_snapshot = slot.metadata["agent_route_snapshot"]
        append_event(
            workflow.workflow_id,
            "asset_version_created",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "agent_route": route_snapshot,
                "specialist": route_snapshot.get("specialist"),
                "status": "completed",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
            },
        )
        set_working_version_for_slot(
            workflow,
            slot,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            source_action=source_action,
        )
        if select_generated:
            set_selected_version_for_slot(
                workflow,
                slot,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                source_action=source_action,
            )
        append_event(
            workflow.workflow_id,
            "provider_execution_completed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "provider": provider_result.provider,
                "provider_model": provider_result.provider_model,
                "status": "completed",
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
            },
        )
        if slot.slot_type == "final_video":
            append_event(
                workflow.workflow_id,
                "final_composition_render_completed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                payload={
                    "provider": provider_result.provider,
                    "timeline_id": provider_result.metadata.get("timeline_id"),
                    "timeline_version": provider_result.metadata.get("timeline_version"),
                },
            )
        transition_slot(
            workflow,
            slot,
            next_status,
            slot_transitions,
            event_type="slot_generation_completed",
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "specialist": route_snapshot.get("specialist"),
                "status": next_status,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
            },
        )

    def apply_provider_task_result(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        task: V2ProviderTask,
        provider_result: V2ProviderResult,
        *,
        slot_transitions: list[dict[str, Any]],
        transition_slot: TransitionSlot,
        set_working_version_for_slot: SlotRelationWriter,
        set_selected_version_for_slot: SlotRelationWriter,
        append_event: EventAppender,
    ) -> WorkflowAssetVersionV2 | None:
        if provider_result.status == "waiting":
            slot.metadata["provider_task_id"] = task.task_id
            slot.metadata["remote_task_id"] = provider_result.remote_task_id or task.remote_task_id
            slot.metadata["waiting_reason"] = provider_result.metadata.get(
                "waiting_reason",
                "provider_task_still_running",
            )
            if slot.status != "waiting":
                transition_slot(
                    workflow,
                    slot,
                    "waiting",
                    slot_transitions,
                    event_type="slot_generation_waiting",
                    payload={
                        "provider_task_id": task.task_id,
                        "status": "waiting",
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                    },
                )
            return None
        if provider_result.status == "failed":
            failure_payload: dict[str, Any] = {
                "provider_task_id": task.task_id,
                "error_code": provider_result.error_code,
                "error_message": provider_result.error_message,
            }
            prompt_audit = provider_result.metadata.get(
                "prompt_audit"
            ) or provider_result.provider_payload_snapshot.get("prompt_audit")
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            append_event(
                workflow.workflow_id,
                "provider_execution_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=provider_result.error_code or "provider_generation_failed",
                message=provider_result.error_message or "Provider task failed.",
                metadata=failure_payload,
            )
            return None

        plan = self.build_plan(workflow, item, slot)
        provider_payload = _merge_provider_payload_snapshots(
            task.provider_payload_snapshot,
            provider_result.provider_payload_snapshot,
        )
        self._append_reference_events(workflow, item, slot, provider_payload, append_event)
        self._append_provider_input_flagged_event(
            workflow,
            item,
            slot,
            provider_payload,
            append_event,
        )
        append_event(
            workflow.workflow_id,
            "quality_gate_started",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload={"provider_task_id": task.task_id, "media_type": slot.media_type},
        )
        try:
            asset = self._write_generated_asset_from_result(
                workflow,
                slot,
                plan,
                provider_payload,
                provider_result,
                asset_id=task.asset_id,
                version_id=task.version_id,
            )
        except V2GenerationPipelineError as exc:
            failure_payload = {
                "provider_task_id": task.task_id,
                "error_code": exc.code,
                "error_message": str(exc),
            }
            prompt_audit = provider_result.metadata.get("prompt_audit") or provider_payload.get(
                "prompt_audit"
            )
            if isinstance(prompt_audit, dict):
                failure_payload["prompt_audit"] = sanitize_context_for_llm_text(prompt_audit)
            append_event(
                workflow.workflow_id,
                "quality_gate_failed",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=failure_payload,
            )
            self._fail_slot(
                workflow,
                slot,
                slot_transitions,
                transition_slot,
                code=exc.code,
                message=str(exc),
                metadata=failure_payload,
            )
            return None
        slot.current_working_asset_id = asset.asset_id
        slot.current_working_version_id = asset.version_id
        select_generated = bool(task.metadata.get("select_generated"))
        if select_generated:
            slot.selected_asset_id = asset.asset_id
            slot.selected_version_id = asset.version_id
            next_status = "completed"
        else:
            next_status = "completed" if slot.selected_asset_id else "ready"
        self._persist_prompt_metadata(slot, plan, provider_payload)
        slot.metadata.pop("provider_task_id", None)
        slot.metadata.pop("waiting_reason", None)
        set_working_version_for_slot(
            workflow,
            slot,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            source_action=str(task.metadata.get("source_action") or "provider_task_poll"),
        )
        if select_generated:
            set_selected_version_for_slot(
                workflow,
                slot,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                source_action=str(task.metadata.get("source_action") or "provider_task_poll"),
            )
        append_event(
            workflow.workflow_id,
            "asset_version_created",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={"provider_task_id": task.task_id},
        )
        append_event(
            workflow.workflow_id,
            "provider_execution_completed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={"provider_task_id": task.task_id, "provider": provider_result.provider},
        )
        append_event(
            workflow.workflow_id,
            "quality_gate_passed",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload=asset.metadata.get("quality_gate_result", {}),
        )
        self._append_reference_audit_recorded_event(
            workflow,
            item,
            slot,
            provider_payload,
            append_event,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            provider_task_id=task.task_id,
        )
        transition_slot(
            workflow,
            slot,
            next_status,
            slot_transitions,
            event_type="slot_generation_completed",
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            payload={
                "provider_task_id": task.task_id,
                "status": next_status,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
            },
        )
        return asset

    def build_plan(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        *,
        source_action: str | None = None,
    ) -> V2GenerationPlan:
        target = V2GenerationTarget(
            workflow_id=workflow.workflow_id,
            target_type="slot",
            node_id=slot.node_id,
            node_type=slot.node_id,
            item_id=item.item_id,
            item_type=item.item_type,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
            is_free_generation=item.item_type == "free" or slot.slot_type == "free_output",
        )
        route = self._router.route(target)
        if item.item_type == "shot" and slot.slot_type.startswith("shot_cell_"):
            # Resolving semantic references derives execution-only dependencies.  Keep
            # that derivation local until a scheduler transition persists the slot.
            slot = slot.model_copy(deep=True)
        shot_references = self._prepare_shot_references(workflow, item, slot)
        bundle = self._reference_bundle_builder.build_for_slot(
            workflow,
            item,
            slot,
            generation_mode=_bundle_generation_mode(slot, source_action=source_action),
        )
        validate_storyboard_slot_namespace(
            item,
            slot,
            bundle,
            allowed_reference_item_ids=(
                shot_references.reference_item_ids if shot_references is not None else None
            ),
        )
        context = self._context_for_slot(workflow, item, slot)
        self._attach_canonical_final_timeline_context(workflow, item, context, slot)
        _apply_reference_bundle_to_context(context, bundle)
        handoff_payload: dict[str, Any] | None = None
        if _uses_canonical_specialist_handoff(slot):
            try:
                handoff = self._handoff_builder.build(
                    workflow,
                    item=item,
                    slot=slot,
                    generation_mode=_bundle_generation_mode(slot, source_action=source_action),
                    reference_bundle=bundle,
                )
            except V2SpecialistHandoffError as exc:
                raise V2GenerationPipelineError(exc.code, str(exc)) from exc
            handoff_payload = handoff.model_dump(mode="json")
            context["specialist_handoff"] = handoff_payload
        materialized = self._materializer.materialize_slot(
            workflow,
            item,
            slot,
            target,
            route,
            context=context,
        )
        audit = self._reference_audit_builder.build_pre_provider_audit(
            workflow,
            item,
            slot,
            bundle,
            generation_action=_bundle_generation_mode(slot, source_action=source_action),
        )
        audit = self._reference_audit_builder.attach_slot_context_lineage_from_payload(
            audit,
            materialized.provider_payload,
        )
        sanitized_audit = self._reference_audit_builder.sanitize_reference_audit(audit)
        provider_payload = {
            **materialized.provider_payload,
            "reference_audit": sanitized_audit,
            "generation_lineage": build_generation_lineage(
                workflow,
                item,
                slot,
                specialist_handoff=handoff_payload,
                reference_bundle=bundle,
            ).model_dump(mode="json"),
        }
        try:
            compiled_prompt = compile_v2_provider_prompt(
                workflow,
                item,
                slot,
                provider_payload=provider_payload,
            )
        except V2PromptGovernanceError as exc:
            raise V2PromptMaterializationError(
                exc.code,
                str(exc),
                metadata=exc.metadata,
            ) from exc
        provider_payload = apply_compiled_prompt_to_payload(provider_payload, compiled_prompt)
        if shot_references is not None:
            provider_payload["shot_reference_snapshot"] = _initial_shot_reference_snapshot(
                shot_references
            )
            provider_payload["shot_reference_version_ids_by_asset_id"] = (
                _reference_version_ids_by_asset_id(bundle)
            )
            if slot.slot_type.startswith("shot_cell_"):
                self._validate_shot_reference_contract(
                    slot=slot,
                    references=shot_references,
                    context=context,
                    provider_payload=provider_payload,
                )
        materialized = materialized.model_copy(
            update={"provider_payload": provider_payload},
            deep=True,
        )
        return V2GenerationPlan(
            target=target,
            agent_route=route,
            materialized_prompt=materialized,
            provider_payload=provider_payload,
            reference_asset_ids=materialized.reference_asset_ids,
            reference_audit=sanitized_audit,
        )

    def _prepare_shot_references(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> V2ResolvedShotReferences | None:
        if item.item_type != "shot":
            return None
        try:
            if slot.slot_type.startswith("shot_cell_"):
                self._shot_reference_resolver.reconcile_shot_cell_dependencies(
                    workflow,
                    item,
                    slot,
                )
            if slot.slot_type.startswith("shot_cell_") or slot.slot_type == "shot_video_segment":
                return self._shot_reference_resolver.resolve(
                    workflow,
                    item,
                    require_selected_assets=True,
                )
        except V2ShotReferenceResolverError as exc:
            raise V2GenerationPipelineError(exc.code, str(exc)) from exc
        return None

    def _validate_shot_reference_contract(
        self,
        *,
        slot: WorkflowSlotV2,
        references: V2ResolvedShotReferences,
        context: dict[str, Any],
        provider_payload: dict[str, Any],
    ) -> None:
        required_asset_ids = [reference.asset_id for reference in references.required_assets]
        resolved_asset_ids = [
            *required_asset_ids,
            *[reference.asset_id for reference in references.optional_assets],
        ]
        audit = provider_payload.get("reference_audit")
        if not isinstance(audit, dict):
            self._raise_shot_reference_contract_error(slot, "reference audit is missing")
        if list(slot.dependency_slot_ids) != list(references.required_main_slot_ids):
            self._raise_shot_reference_contract_error(
                slot, "dependency slots diverged from resolver"
            )
        if _ordered_string_ids(context.get("dependency_asset_ids")) != required_asset_ids:
            self._raise_shot_reference_contract_error(
                slot, "dependency assets diverged from resolver"
            )
        if _ordered_string_ids(context.get("visual_reference_asset_ids")) != resolved_asset_ids:
            self._raise_shot_reference_contract_error(
                slot, "slot context references diverged from resolver"
            )
        if _ordered_string_ids(audit.get("required_reference_asset_ids")) != required_asset_ids:
            self._raise_shot_reference_contract_error(slot, "audit required references diverged")
        if _ordered_string_ids(audit.get("dependency_reference_asset_ids")) != required_asset_ids:
            self._raise_shot_reference_contract_error(slot, "audit dependency references diverged")
        _require_reference_prefix(
            _ordered_string_ids(audit.get("requested_reference_asset_ids")),
            resolved_asset_ids,
            slot=slot,
            source="audit requested references",
        )
        _require_reference_prefix(
            _ordered_string_ids(provider_payload.get("reference_asset_ids")),
            resolved_asset_ids,
            slot=slot,
            source="provider payload references",
        )
        snapshot = provider_payload.get("shot_reference_snapshot")
        if not isinstance(snapshot, dict):
            self._raise_shot_reference_contract_error(slot, "shot reference snapshot is missing")
        if _ordered_string_ids(snapshot.get("required_reference_asset_ids")) != required_asset_ids:
            self._raise_shot_reference_contract_error(slot, "snapshot required references diverged")
        if (
            _ordered_string_ids(snapshot.get("optional_reference_asset_ids"))
            != resolved_asset_ids[len(required_asset_ids) :]
        ):
            self._raise_shot_reference_contract_error(slot, "snapshot optional references diverged")

    @staticmethod
    def _raise_shot_reference_contract_error(slot: WorkflowSlotV2, reason: str) -> None:
        raise V2GenerationPipelineError(
            "shot_reference_contract_mismatch",
            f"Shot reference contract mismatch for {slot.node_id}/{slot.item_id}/{slot.slot_id}: {reason}.",
        )

    def _with_execution_context(
        self,
        plan: V2GenerationPlan,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        *,
        execution_id: str | None,
    ) -> V2GenerationPlan:
        if not execution_id:
            return plan
        provider_payload = {
            **plan.provider_payload,
            "execution_context": {
                "workflow_id": workflow.workflow_id,
                "execution_id": execution_id,
                "node_id": slot.node_id,
                "item_id": item.item_id,
                "slot_id": slot.slot_id,
            },
        }
        materialized_prompt = plan.materialized_prompt.model_copy(
            update={"provider_payload": provider_payload},
            deep=True,
        )
        return plan.model_copy(
            update={
                "materialized_prompt": materialized_prompt,
                "provider_payload": provider_payload,
            },
            deep=True,
        )

    def materialize_chat_revision(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2 | None,
        slot: WorkflowSlotV2 | None,
        target: V2GenerationTarget,
        route,
        request: WorkflowV2ChatTargetRequest,
    ):
        if item is None and slot is None:
            raise V2PromptMaterializationError("agent_route_not_found")
        revision_item = item.model_copy(deep=True) if item is not None else None
        revision_slot = slot.model_copy(deep=True) if slot is not None else None
        if revision_item is not None and revision_slot is None:
            revision_slot = next(
                (candidate for candidate in revision_item.slots if candidate.required), None
            )
        if revision_item is None or revision_slot is None:
            raise V2PromptMaterializationError("slot_not_found")
        if slot is not None and request.prompt_scope in {"auto", "slot"}:
            revision_slot.slot_prompt = request.slot_prompt or request.instruction
            revision_slot.user_prompt = revision_slot.slot_prompt
            revision_slot.prompt_source = "user"
            revision_slot.manual_prompt_dirty = True
            if request.negative_prompt is not None:
                revision_slot.negative_prompt = request.negative_prompt
            if request.dialogue_prompt is not None:
                revision_slot.dialogue_prompt = request.dialogue_prompt
            if request.audio_description_prompt is not None:
                revision_slot.audio_description_prompt = request.audio_description_prompt
            if request.voice_style_prompt is not None:
                revision_slot.voice_style_prompt = request.voice_style_prompt
            if request.negative_constraints is not None:
                revision_slot.negative_constraints = request.negative_constraints
        else:
            prompt = request.item_prompt or request.instruction
            if revision_item.item_type == "shot":
                revision_item.shot_summary_prompt = prompt
            else:
                revision_item.item_prompt = prompt
            revision_item.user_prompt = prompt
            revision_item.prompt_source = "user"
            revision_item.manual_prompt_dirty = True
        bundle = self._reference_bundle_builder.build_for_slot(
            workflow,
            revision_item,
            revision_slot,
            generation_mode="chat_revise_and_generate",
        )
        context = self._context_for_slot(workflow, revision_item, revision_slot)
        self._attach_canonical_final_timeline_context(
            workflow,
            revision_item,
            context,
            revision_slot,
        )
        _apply_reference_bundle_to_context(context, bundle)
        if _uses_canonical_specialist_handoff(revision_slot):
            handoff = self._handoff_builder.build(
                workflow,
                item=revision_item,
                slot=revision_slot,
                latest_instruction=request.instruction,
                generation_mode="chat_revise_and_generate",
            )
            context["specialist_handoff"] = handoff.model_dump(mode="json")
        return self._materializer.materialize_slot(
            workflow,
            revision_item,
            revision_slot,
            target,
            route,
            context=context,
        )

    def poll_provider_task(self, task: V2ProviderTask) -> V2ProviderResult:
        return self._provider_executor.poll_task(task)

    def _write_generated_asset_from_result(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
        provider_payload: dict[str, Any],
        provider_result: V2ProviderResult,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowAssetVersionV2:
        version_id = version_id or f"ver_{uuid4().hex[:12]}"
        asset_id = (
            asset_id or f"{workflow.workflow_id}_{slot.slot_id.replace(':', '_')}_{version_id}"
        )
        ext = _extension_for_media_type(slot.media_type)
        local_path = (
            Path("assets")
            / "generated"
            / workflow.workflow_id
            / slot.node_id
            / slot.item_id
            / f"{slot.slot_type}-{version_id}.{ext}"
        )
        absolute_path = self._data_dir / local_path
        validate_v2_data_path(self._data_dir, absolute_path, operation="v2-generated-asset-write")
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        if provider_result.asset_bytes is not None:
            absolute_path.write_bytes(provider_result.asset_bytes)
        elif provider_result.local_file_path:
            source_path = Path(provider_result.local_file_path)
            if not source_path.is_absolute():
                source_path = self._data_dir / source_path
            if not source_path.exists():
                raise V2GenerationPipelineError(
                    "asset_file_missing",
                    f"Provider output file not found: {source_path}",
                )
            shutil.copyfile(source_path, absolute_path)
        else:
            raise V2GenerationPipelineError(
                "provider_output_missing",
                "Provider result did not include asset bytes or local file path.",
            )
        detected = detect_media_format(absolute_path)
        if detected is not None and absolute_path.suffix.lower() != detected.file_extension:
            corrected_local_path = local_path.with_suffix(detected.file_extension)
            corrected_absolute_path = self._data_dir / corrected_local_path
            validate_v2_data_path(
                self._data_dir,
                corrected_absolute_path,
                operation="v2-generated-asset-write",
            )
            corrected_absolute_path.parent.mkdir(parents=True, exist_ok=True)
            absolute_path.replace(corrected_absolute_path)
            local_path = corrected_local_path
            absolute_path = corrected_absolute_path
        quality_result = sanitize_context_for_llm_text(
            self._quality_gate.evaluate(
                data_dir=self._data_dir,
                file_path=local_path,
                media_type=slot.media_type,
            )
        )
        if quality_result.get("status") != "passed":
            raise V2GenerationPipelineError(
                str(quality_result.get("error_code") or "quality_gate_failed"),
                str(quality_result.get("error_message") or "Generated asset failed quality gate."),
            )
        self._validate_deterministic_provider_contract(
            slot=slot,
            provider_payload=provider_payload,
            provider_result=provider_result,
            absolute_path=absolute_path,
        )
        prompt_snapshot = sanitize_context_for_llm_text(
            {
                **plan.materialized_prompt.model_dump(
                    mode="json",
                    exclude={"provider_payload"},
                ),
                "agent_route": plan.agent_route.model_dump(mode="json"),
                "target": plan.target.model_dump(mode="json"),
            }
        )
        record = WorkflowAssetVersionV2(
            asset_id=asset_id,
            version_id=version_id,
            media_type=slot.media_type,
            source_type="generated",
            file_path=local_path.as_posix(),
            public_url=f"/media/{local_path.as_posix()}",
            workflow_id=workflow.workflow_id,
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            semantic_type=_semantic_type_for_slot(slot.slot_type, slot.media_type),
            prompt_snapshot=prompt_snapshot,
            provider_payload_snapshot=provider_payload,
            reference_asset_ids=list(
                provider_result.reference_asset_ids or plan.reference_asset_ids
            ),
            created_by="v2-generation-pipeline",
            metadata={
                "media_type": slot.media_type,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "slot_id": slot.slot_id,
                "slot_type": slot.slot_type,
                "semantic_type": _semantic_type_for_slot(slot.slot_type, slot.media_type),
                "generation_lineage": _validated_generation_lineage(provider_payload),
                "sequence_index": provider_payload.get("sequence_index"),
                "sequence_role": provider_payload.get("sequence_role"),
                "summary_prompt": provider_payload.get("summary_prompt"),
                "provider_prompt": provider_payload.get("provider_prompt"),
                "reference_item_ids": list(
                    provider_payload.get("selected_reference_item_ids") or []
                ),
                "reference_asset_ids": list(provider_payload.get("reference_asset_ids") or []),
                "cell_prompt": sanitize_context_for_llm_text(
                    provider_payload.get("cell_prompt") or {}
                ),
                "cell_prompts": sanitize_context_for_llm_text(
                    provider_payload.get("cell_prompts") or []
                ),
                **_bgm_asset_metadata_from_payload(slot, provider_payload, provider_result),
                **_specialist_prompt_source_metadata(slot),
                "agent_route": plan.agent_route.model_dump(mode="json"),
                "provider": provider_result.provider,
                "provider_model": provider_result.provider_model,
                "prompt_registry_ref": sanitize_context_for_llm_text(
                    provider_payload.get("prompt_registry_ref")
                    or provider_result.metadata.get("prompt_registry_ref")
                    or {}
                ),
                "prompt_lineage": sanitize_context_for_llm_text(
                    provider_payload.get("prompt_lineage")
                    or provider_result.metadata.get("prompt_lineage")
                    or {}
                ),
                "prompt_provenance": sanitize_context_for_llm_text(
                    provider_payload.get("prompt_provenance")
                    or provider_result.metadata.get("prompt_provenance")
                    or {}
                ),
                "prompt_content_profile": sanitize_context_for_llm_text(
                    provider_payload.get("prompt_content_profile")
                    or provider_result.metadata.get("prompt_content_profile")
                    or {}
                ),
                "canonical_provider_payload": sanitize_context_for_llm_text(
                    provider_payload.get("canonical_provider_payload") or provider_payload
                ),
                **self._shot_reference_snapshot_metadata(slot, provider_payload),
                **_main_to_multiview_metadata_from_payload(provider_payload),
                **_contract_metadata_from_payload(provider_payload),
                **asset_identity_metadata(provider_payload),
                **reference_metadata_from_payload(provider_payload),
                **sanitize_context_for_llm_text(provider_result.metadata),
                **_detected_media_metadata(quality_result),
                "quality_gate_result": quality_result,
                "quality_gate_warnings": list(quality_result.get("warnings") or []),
            },
        )
        return self._asset_store.save_asset_version(record)

    def _shot_reference_snapshot_metadata(
        self,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if slot.slot_type not in {"shot_video_segment", *shot_cell_slot_types()}:
            return {}
        raw_snapshot = provider_payload.get("shot_reference_snapshot")
        if not isinstance(raw_snapshot, dict):
            return {}
        submitted_asset_ids = _ordered_string_ids(
            provider_payload.get("submitted_reference_asset_ids")
            or provider_payload.get("reference_asset_ids")
            or []
        )
        version_ids_by_asset_id = _reference_version_ids_from_payload(provider_payload)
        submitted_version_ids = [
            version_ids_by_asset_id.get(asset_id) or record.version_id
            for asset_id in submitted_asset_ids
            if (record := self._asset_store.find_asset_version(asset_id=asset_id)) is not None
        ]
        snapshot = {
            "snapshot_version": 1,
            "shot_item_id": str(raw_snapshot.get("shot_item_id") or ""),
            "primary_scene_item_id": str(raw_snapshot.get("primary_scene_item_id") or ""),
            "reference_item_ids": _ordered_string_ids(raw_snapshot.get("reference_item_ids") or []),
            "required_reference_asset_ids": _ordered_string_ids(
                raw_snapshot.get("required_reference_asset_ids") or []
            ),
            "optional_reference_asset_ids": _ordered_string_ids(
                raw_snapshot.get("optional_reference_asset_ids") or []
            ),
            "submitted_reference_asset_ids": submitted_asset_ids,
            "submitted_reference_version_ids": _ordered_string_ids(submitted_version_ids),
        }
        return {"shot_reference_snapshot": sanitize_context_for_llm_text(snapshot)}

    def _validate_deterministic_provider_contract(
        self,
        *,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        provider_result: V2ProviderResult,
        absolute_path: Path,
    ) -> None:
        if not absolute_path.exists() or not absolute_path.is_file():
            raise V2GenerationPipelineError(
                "asset_file_missing",
                f"Generated asset file not found: {absolute_path}",
            )
        try:
            with absolute_path.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            raise V2GenerationPipelineError(
                "asset_file_unreadable",
                f"Generated asset file is not readable: {absolute_path}",
            ) from exc
        if provider_result.media_type != slot.media_type:
            raise V2GenerationPipelineError(
                "provider_media_type_mismatch",
                f"Provider returned {provider_result.media_type} for {slot.media_type} slot.",
            )
        audit = provider_result.metadata.get("prompt_audit") or provider_payload.get("prompt_audit")
        if slot.slot_type != "final_video" and slot.media_type in {"image", "audio", "video"}:
            if not isinstance(audit, dict):
                raise V2GenerationPipelineError(
                    "v2_prompt_audit_missing",
                    "V2 provider result did not include prompt audit metadata.",
                )
            if audit.get("prompt_match") is not True:
                raise V2GenerationPipelineError(
                    "v2_provider_prompt_mismatch",
                    "V2 provider request prompt did not match canonical provider prompt.",
                )
            if audit.get("prompt_source_contract") != V2_PROMPT_SOURCE_CONTRACT:
                raise V2GenerationPipelineError(
                    "v2_provider_prompt_mismatch",
                    "V2 provider prompt audit did not use canonical provider prompt contract.",
                )
            if audit.get("legacy_prompt_fields_used"):
                raise V2GenerationPipelineError(
                    "v2_legacy_prompt_field_used",
                    "V2 provider prompt used retired legacy prompt fields.",
                )
        required_ids = _required_reference_asset_ids(provider_payload)
        if required_ids:
            submitted_ids = set(
                provider_payload.get("submitted_reference_asset_ids")
                or provider_result.reference_asset_ids
                or provider_payload.get("reference_asset_ids")
                or []
            )
            missing_ids = [asset_id for asset_id in required_ids if asset_id not in submitted_ids]
            if missing_ids:
                raise V2GenerationPipelineError(
                    "v2_required_reference_dropped",
                    "V2 required references were not submitted: " + ", ".join(missing_ids),
                )

    def _append_reference_events(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        append_event: EventAppender,
    ) -> None:
        reference_metadata = reference_metadata_from_payload(provider_payload)
        audit = provider_payload.get("reference_audit")
        if isinstance(audit, dict):
            reference_metadata = {
                **reference_metadata,
                "audit_id": audit.get("audit_id"),
                "drop_reasons": list(audit.get("drop_reasons") or []),
            }
        requested = reference_metadata["requested_reference_asset_ids"]
        dropped = reference_metadata["dropped_reference_asset_ids"]
        if not requested and not dropped and not isinstance(audit, dict):
            return
        append_event(
            workflow.workflow_id,
            "provider_references_adapted",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload=reference_metadata,
        )
        if dropped:
            append_event(
                workflow.workflow_id,
                "provider_reference_dropped",
                node_id=slot.node_id,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "dropped_reference_asset_ids": dropped,
                    "reference_usage_warnings": reference_metadata["reference_usage_warnings"],
                },
            )

    def _append_reference_bundle_built_event(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        append_event: EventAppender,
    ) -> None:
        del workflow, item
        audit = provider_payload.get("reference_audit")
        if not isinstance(audit, dict):
            return
        append_event(
            audit["workflow_id"],
            "reference_bundle_built",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={
                "audit_id": audit.get("audit_id"),
                "slot_id": audit.get("slot_id"),
                "slot_context_id": audit.get("slot_context_id"),
                "slot_context_fingerprint": audit.get("slot_context_fingerprint"),
                "required_reference_asset_ids": list(
                    audit.get("required_reference_asset_ids") or []
                ),
                "explicit_reference_asset_ids": list(
                    audit.get("explicit_reference_asset_ids") or []
                ),
                "implicit_reference_asset_ids": list(
                    audit.get("implicit_reference_asset_ids") or []
                ),
                "dependency_reference_asset_ids": list(
                    audit.get("dependency_reference_asset_ids") or []
                ),
                "requested_reference_asset_ids": list(
                    audit.get("requested_reference_asset_ids") or []
                ),
                "allowed_reference_asset_ids": list(audit.get("allowed_reference_asset_ids") or []),
                "forbidden_reference_asset_ids": list(
                    audit.get("forbidden_reference_asset_ids") or []
                ),
                "reference_usage": list(audit.get("reference_usage") or []),
            },
        )

    def _append_reference_audit_recorded_event(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        append_event: EventAppender,
        *,
        asset_id: str | None = None,
        version_id: str | None = None,
        provider_task_id: str | None = None,
    ) -> None:
        audit = provider_payload.get("reference_audit")
        if not isinstance(audit, dict):
            return
        wire_audit = provider_payload.get("reference_wire_audit")
        append_event(
            workflow.workflow_id,
            "reference_audit_recorded",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=asset_id,
            version_id=version_id,
            payload={
                "audit_id": audit.get("audit_id"),
                "slot_id": slot.slot_id,
                "asset_id": asset_id,
                "version_id": version_id,
                "provider_task_id": provider_task_id,
                **(
                    {"reference_wire_audit": sanitize_context_for_llm_text(wire_audit)}
                    if isinstance(wire_audit, dict)
                    else {}
                ),
            },
        )

    def _append_provider_input_flagged_event(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
        append_event: EventAppender,
    ) -> None:
        flags = provider_payload.get("quality_flags")
        if not isinstance(flags, list) or not flags:
            return
        append_event(
            workflow.workflow_id,
            "provider_input_flagged",
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload={
                "workflow_id": workflow.workflow_id,
                "node_id": slot.node_id,
                "item_id": item.item_id,
                "slot_id": slot.slot_id,
                "slot_type": slot.slot_type,
                "quality_flags": sanitize_context_for_llm_text(flags),
            },
        )

    def _persist_prompt_metadata(
        self,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
        provider_payload: dict[str, Any],
    ) -> None:
        route_snapshot = sanitize_context_for_llm_text(plan.agent_route.model_dump(mode="json"))
        prompt_snapshot = sanitize_context_for_llm_text(
            {
                **plan.materialized_prompt.model_dump(
                    mode="json",
                    exclude={"provider_payload"},
                ),
                "agent_route": plan.agent_route.model_dump(mode="json"),
                "target": plan.target.model_dump(mode="json"),
            }
        )
        slot.metadata["agent_route_snapshot"] = route_snapshot
        slot.metadata["provider_prompt_snapshot"] = prompt_snapshot
        slot.metadata["provider_payload_snapshot"] = provider_payload
        slot.metadata["canonical_provider_payload"] = (
            provider_payload.get("canonical_provider_payload") or provider_payload
        )
        if isinstance(provider_payload.get("reference_audit"), dict):
            slot.metadata["latest_reference_audit"] = provider_payload["reference_audit"]
        if isinstance(provider_payload.get("reference_delivery_audit"), dict):
            slot.metadata["latest_reference_delivery_audit"] = provider_payload[
                "reference_delivery_audit"
            ]
        if isinstance(provider_payload.get("reference_wire_audit"), dict):
            slot.metadata["latest_reference_wire_audit"] = sanitize_context_for_llm_text(
                provider_payload["reference_wire_audit"]
            )
        if isinstance(provider_payload.get("provider_prompt_contract"), dict):
            slot.metadata["provider_prompt_contract"] = provider_payload["provider_prompt_contract"]
        if isinstance(provider_payload.get("prompt_registry_ref"), dict):
            slot.metadata["prompt_registry_ref"] = provider_payload["prompt_registry_ref"]
        if isinstance(provider_payload.get("prompt_lineage"), dict):
            slot.metadata["prompt_lineage"] = provider_payload["prompt_lineage"]
        if isinstance(provider_payload.get("prompt_content_profile"), dict):
            slot.metadata["prompt_content_profile"] = provider_payload["prompt_content_profile"]
        identity_slot_metadata = slot_identity_metadata(
            {
                "identity_spec_hash": provider_payload.get("identity_spec_hash"),
                "identity_spec_version": provider_payload.get("identity_spec_version"),
            }
        )
        if identity_slot_metadata:
            slot.metadata.update(identity_slot_metadata)
            slot.metadata["identity_spec_fields_used"] = list(
                provider_payload.get("identity_spec_fields_used") or []
            )
        if isinstance(provider_payload.get("prompt_isolation_audit"), dict):
            slot.metadata["prompt_isolation_audit"] = provider_payload["prompt_isolation_audit"]
        fallback_reason = provider_payload.get("fallback_reason")
        if isinstance(fallback_reason, str) and fallback_reason:
            slot.metadata["fallback_reason"] = fallback_reason
        if isinstance(provider_payload.get("prompt_isolation_recovery"), dict):
            slot.metadata["prompt_isolation_recovery"] = sanitize_context_for_llm_text(
                provider_payload["prompt_isolation_recovery"]
            )
        if isinstance(provider_payload.get("prompt_sanitization_audit"), dict):
            slot.metadata["prompt_sanitization_audit"] = provider_payload[
                "prompt_sanitization_audit"
            ]
        if isinstance(provider_payload.get("fallback_field_completeness"), dict):
            slot.metadata["fallback_field_completeness"] = provider_payload[
                "fallback_field_completeness"
            ]
        if isinstance(provider_payload.get("generation_integrity"), dict):
            slot.metadata["generation_integrity"] = provider_payload["generation_integrity"]
            slot.metadata["integrity_audit"] = provider_payload["generation_integrity"]
        slot.metadata["materializer_mode"] = plan.materialized_prompt.materializer_mode
        slot.metadata["materializer_warnings"] = list(plan.materialized_prompt.warnings)
        slot.metadata["materializer_model_id"] = plan.materialized_prompt.model_id
        slot.metadata["selected_reference_item_ids"] = provider_payload.get(
            "selected_reference_item_ids", []
        )

    def _provider_call(
        self,
        *,
        slot: WorkflowSlotV2,
        plan: V2GenerationPlan,
        provider_payload: dict[str, Any],
        provider_result: V2ProviderResult,
        asset: WorkflowAssetVersionV2 | None = None,
        task: V2ProviderTask | None = None,
    ) -> dict[str, Any]:
        return {
            "node_id": slot.node_id,
            "item_id": slot.item_id,
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "status": provider_result.status,
            "provider": provider_result.provider,
            "provider_model": provider_result.provider_model,
            "agent_route": sanitize_context_for_llm_text(plan.agent_route.model_dump(mode="json")),
            "provider_prompt_snapshot": sanitize_context_for_llm_text(
                {
                    **plan.materialized_prompt.model_dump(
                        mode="json",
                        exclude={"provider_payload"},
                    ),
                    "agent_route": plan.agent_route.model_dump(mode="json"),
                    "target": plan.target.model_dump(mode="json"),
                }
            ),
            "provider_payload": provider_payload,
            "materializer_mode": plan.materialized_prompt.materializer_mode,
            "materializer_warnings": list(plan.materialized_prompt.warnings),
            "remote_task_id": provider_result.remote_task_id,
            "provider_task_id": task.task_id if task else None,
            "asset_id": asset.asset_id if asset else None,
            "version_id": asset.version_id if asset else None,
            "error_code": provider_result.error_code,
            "error_message": provider_result.error_message,
        }

    def _context_for_slot(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> dict[str, Any]:
        is_shot_cell = item.item_type == "shot" and slot.slot_type.startswith("shot_cell_")
        context = {
            "dependency_asset_ids": self._dependency_asset_ids(workflow, slot),
            "visual_reference_asset_ids": (
                [] if is_shot_cell else self._visual_reference_asset_ids(workflow)
            ),
            "item_reference_asset_ids": self._item_reference_asset_ids(workflow, item),
            "shot_cell_asset_ids": self._shot_cell_asset_ids(item),
            "shot_video_segment_asset_ids": self._selected_shot_video_asset_ids(workflow),
            "bgm_asset_id": (
                self._selected_bgm_asset_id(workflow) if workflow.audio_mode != "none" else None
            ),
        }
        if is_shot_cell:
            try:
                resolved = self._shot_reference_resolver.resolve(
                    workflow,
                    item,
                    require_selected_assets=True,
                )
            except V2ShotReferenceResolverError as exc:
                raise V2GenerationPipelineError(exc.code, str(exc)) from exc
            references = [*resolved.required_assets, *resolved.optional_assets]
            context.update(
                {
                    "dependency_asset_ids": [
                        reference.asset_id for reference in resolved.required_assets
                    ],
                    "visual_reference_asset_ids": [reference.asset_id for reference in references],
                    "reference_version_ids": [reference.version_id for reference in references],
                    "shot_reference_selection": {
                        "shot_item_id": resolved.shot_item_id,
                        "primary_scene_item_id": resolved.primary_scene_item_id,
                        "reference_item_ids": list(resolved.reference_item_ids),
                        "required_main_slot_ids": list(resolved.required_main_slot_ids),
                        "optional_companion_slot_ids": list(resolved.optional_companion_slot_ids),
                    },
                }
            )
        if is_main_to_multiview_slot(slot.slot_type):
            slot.dependency_slot_ids = dependency_slot_ids_for_multiview(item, slot)
            reference_context = selected_main_reference_context(
                workflow=workflow,
                item=item,
                slot=slot,
                asset_store=self._asset_store,
            )
            if reference_context is None:
                metadata = main_reference_missing_metadata(item, slot)
                slot.metadata.update(metadata)
                raise V2PromptMaterializationError(
                    "missing_selected_main_image",
                    "Multi-view generation requires the selected matching main image.",
                    metadata=metadata,
                )
            item.metadata["identity_contract"] = reference_context["identity_contract"]
            context["main_to_multiview"] = reference_context
            context["dependency_asset_ids"] = list(reference_context["reference_asset_ids"])
            context["reference_version_ids"] = list(reference_context["reference_version_ids"])
            context["dependency_asset_summaries"] = [
                {
                    "asset_id": reference_context["primary_reference_asset_id"],
                    "version_id": reference_context["primary_reference_version_id"],
                    "role": "primary_main_image_reference",
                    "source_slot_id": reference_context["consistency_contract"]["source_slot_id"],
                }
            ]
        return context

    def _attach_canonical_final_timeline_context(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        context: dict[str, Any],
        slot: WorkflowSlotV2,
    ) -> None:
        if slot.slot_type != "final_video":
            return
        _stored_workflow, _item, _final_slot, timeline, _source = (
            self._final_timeline_service.load_or_create_and_reconcile(workflow.workflow_id)
        )
        self._final_timeline_service.project_compatibility_timeline(item, timeline)
        context["canonical_timeline"] = timeline.model_dump(mode="json")

    def _dependency_asset_ids(self, workflow: WorkflowV2, slot: WorkflowSlotV2) -> list[str]:
        asset_ids: list[str] = []
        for dependency_slot_id in slot.dependency_slot_ids:
            dependency = _find_slot(workflow, dependency_slot_id)
            if dependency and dependency.selected_asset_id:
                asset_ids.append(dependency.selected_asset_id)
        return asset_ids

    def _visual_reference_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        asset_ids: list[str] = []
        for slot_type in (
            "product_main_image",
            "character_main_image",
            "scene_main_image",
        ):
            slot = _find_slot_by_type(workflow, slot_type)
            if slot and slot.selected_asset_id:
                asset_ids.append(slot.selected_asset_id)
        return asset_ids

    def _item_reference_asset_ids(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
    ) -> list[str]:
        asset_ids = [
            str(asset_id)
            for asset_id in item.metadata.get("explicit_reference_asset_ids", [])
            if str(asset_id)
        ]
        relations = self._asset_store.list_relations(
            target_workflow_id=workflow.workflow_id,
            relation_type="reference_for_item",
        )
        for relation in relations:
            if relation.target_item_id == item.item_id and relation.source_asset_id:
                asset_ids.append(relation.source_asset_id)
        return list(dict.fromkeys(asset_ids))

    def _shot_cell_asset_ids(self, item: WorkflowItemV2) -> list[str]:
        return [
            slot.selected_asset_id
            for slot in item.slots
            if slot.slot_type.startswith("shot_cell_") and slot.selected_asset_id
        ]

    def _selected_shot_video_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        asset_ids: list[str] = []
        storyboard = _node_by_id(workflow, "storyboard")
        if storyboard is None:
            return asset_ids
        for item in sorted(_active_items(storyboard), key=lambda shot: shot.shot_index or 0):
            slot = _slot_by_type(item, "shot_video_segment")
            if (
                slot
                and slot.selected_asset_id
                and self._asset_store.asset_exists(slot.selected_asset_id)
            ):
                asset_ids.append(slot.selected_asset_id)
        return asset_ids

    def _selected_bgm_asset_id(self, workflow: WorkflowV2) -> str | None:
        slot = _find_slot_by_type(workflow, "bgm_audio")
        if (
            slot
            and slot.selected_asset_id
            and self._asset_store.asset_exists(slot.selected_asset_id)
        ):
            return slot.selected_asset_id
        return None

    def _fail_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        slot_transitions: list[dict[str, Any]],
        transition_slot: TransitionSlot,
        *,
        code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        slot.metadata["generation_error"] = message
        slot.metadata["generation_error_code"] = code
        slot.metadata["error"] = {"code": code, "message": message}
        failure_metadata = sanitize_context_for_llm_text(metadata or {})
        if isinstance(failure_metadata, dict):
            slot.metadata.update(failure_metadata)
        event_metadata = _event_safe_failure_metadata(failure_metadata)
        payload = {
            "error": message,
            "code": code,
            "error_code": code,
            "error_message": message,
            "status": "failed",
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
        }
        payload.update(event_metadata)
        transition_slot(
            workflow,
            slot,
            "failed",
            slot_transitions,
            event_type="slot_generation_failed",
            payload=payload,
        )

    def _skip_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        slot_transitions: list[dict[str, Any]],
        transition_slot: TransitionSlot,
        *,
        code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        slot.metadata["generation_error"] = message
        slot.metadata["generation_error_code"] = code
        slot.metadata["skipped_reason"] = code
        skipped_metadata = sanitize_context_for_llm_text(metadata or {})
        if isinstance(skipped_metadata, dict):
            slot.metadata.update(skipped_metadata)
        payload = {
            "reason": message,
            "code": code,
            "error_code": code,
            "error_message": message,
            "status": "skipped",
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
        }
        if isinstance(skipped_metadata, dict):
            payload.update(skipped_metadata)
        transition_slot(
            workflow,
            slot,
            "skipped",
            slot_transitions,
            event_type="slot_skipped",
            payload=payload,
        )


def _apply_reference_bundle_to_context(context: dict[str, Any], bundle: Any) -> None:
    payload = bundle.model_dump(mode="json")
    context["reference_bundle"] = payload
    context["provider_reference_assets"] = payload.get("provider_reference_assets", [])
    context["llm_context_assets"] = payload.get("llm_context_assets", [])
    context["reference_warnings"] = payload.get("reference_warnings", [])


def _initial_shot_reference_snapshot(
    references: V2ResolvedShotReferences,
) -> dict[str, Any]:
    return {
        "snapshot_version": 1,
        "shot_item_id": references.shot_item_id,
        "primary_scene_item_id": references.primary_scene_item_id,
        "reference_item_ids": list(references.reference_item_ids),
        "required_reference_asset_ids": [
            reference.asset_id for reference in references.required_assets
        ],
        "optional_reference_asset_ids": [
            reference.asset_id for reference in references.optional_assets
        ],
        "submitted_reference_asset_ids": [],
        "submitted_reference_version_ids": [],
    }


def _reference_version_ids_by_asset_id(bundle: Any) -> dict[str, str]:
    version_ids: dict[str, str] = {}
    for asset in [
        *list(bundle.provider_reference_assets),
        *list(bundle.implicit_reference_assets),
        *list(bundle.explicit_reference_assets),
    ]:
        asset_id = str(getattr(asset, "asset_id", "") or "").strip()
        version_id = str(getattr(asset, "version_id", "") or "").strip()
        if asset_id and version_id:
            version_ids.setdefault(asset_id, version_id)
    return version_ids


def _reference_version_ids_from_payload(provider_payload: dict[str, Any]) -> dict[str, str]:
    version_ids: dict[str, str] = {}
    raw_map = provider_payload.get("shot_reference_version_ids_by_asset_id")
    if isinstance(raw_map, dict):
        for asset_id, version_id in raw_map.items():
            normalized_asset_id = str(asset_id or "").strip()
            normalized_version_id = str(version_id or "").strip()
            if normalized_asset_id and normalized_version_id:
                version_ids[normalized_asset_id] = normalized_version_id
    delivery = provider_payload.get("reference_input_delivery")
    references = delivery.get("references") if isinstance(delivery, dict) else []
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            asset_id = str(reference.get("asset_id") or "").strip()
            version_id = str(reference.get("version_id") or "").strip()
            if asset_id and version_id:
                version_ids.setdefault(asset_id, version_id)
    return version_ids


def _ordered_string_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))


def _bundle_generation_mode(slot: WorkflowSlotV2, *, source_action: str | None = None) -> str:
    if source_action == "chat_revise_and_generate":
        return "chat_revise_and_generate"
    if source_action == "global_run":
        return "global_run"
    if slot.slot_type.startswith("shot_cell_"):
        return "storyboard_cell_generation"
    if slot.slot_type == "shot_video_segment":
        return "storyboard_video_generation"
    if slot.slot_type == "bgm_audio":
        return "bgm_generation"
    if slot.slot_type == "final_video":
        return "final_composition"
    if slot.slot_type == "free_output":
        return "free_generation"
    return "slot_generation"


def _node_by_id(workflow: WorkflowV2, node_id: str):
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _active_items(node) -> list[WorkflowItemV2]:
    return [item for item in node.items if item.lifecycle_state == "active"]


def _slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _find_slot(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in _active_items(node):
            for slot in item.slots:
                if slot.slot_id == slot_id:
                    return slot
    return None


def _find_slot_by_type(workflow: WorkflowV2, slot_type: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in _active_items(node):
            slot = _slot_by_type(item, slot_type)
            if slot is not None:
                return slot
    return None


def _semantic_type_for_slot(slot_type: str, media_type: str | None = None) -> str:
    if slot_type.startswith("shot_cell_"):
        return "shot_cell_image"
    if slot_type == "free_output":
        return {
            "image": "free_image",
            "video": "free_video",
            "audio": "free_audio",
        }.get(media_type or "", "free_image")
    return {
        "product_main_image": "product_main_image",
        "product_multi_view_grid": "product_multi_view_grid",
        "character_main_image": "character_main_image",
        "character_three_view": "character_three_view",
        "scene_main_image": "scene_main_image",
        "scene_multi_view_grid": "scene_multi_view_grid",
        "bgm_audio": "bgm_audio",
        "shot_video_segment": "shot_video_segment",
        "final_video": "final_video",
    }.get(slot_type, slot_type)


def _specialist_prompt_source_metadata(slot: WorkflowSlotV2) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("specialist_type", "asset_prompt_hash"):
        value = slot.metadata.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value
    audit = slot.metadata.get("specialist_quality_audit")
    if isinstance(audit, dict) and audit:
        metadata["specialist_quality_audit"] = sanitize_context_for_llm_text(audit)
    return metadata


def _contract_metadata_from_payload(provider_payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if isinstance(provider_payload.get("provider_prompt_contract"), dict):
        metadata["provider_prompt_contract"] = sanitize_context_for_llm_text(
            provider_payload["provider_prompt_contract"]
        )
    if isinstance(provider_payload.get("reference_delivery_audit"), dict):
        metadata["reference_delivery_audit"] = sanitize_context_for_llm_text(
            provider_payload["reference_delivery_audit"]
        )
    return metadata


def _main_to_multiview_metadata_from_payload(provider_payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "primary_reference_asset_id",
        "primary_reference_version_id",
        "dependency_slot_ids",
        "consistency_contract",
        "identity_contract",
    ):
        value = provider_payload.get(key)
        if value:
            metadata[key] = sanitize_context_for_llm_text(value)
    return metadata


def _detected_media_metadata(quality_result: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("mime_type", "file_extension", "detected_media_format"):
        value = quality_result.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value
    return metadata


def _event_safe_failure_metadata(metadata: Any) -> dict[str, Any]:
    """Drop renderer-only arguments before emitting a durable runtime event."""

    if not isinstance(metadata, dict):
        return {}
    return {key: value for key, value in metadata.items() if key != "ffmpeg_args"}


def _bgm_asset_metadata_from_payload(
    slot: WorkflowSlotV2,
    provider_payload: dict[str, Any],
    provider_result: V2ProviderResult,
) -> dict[str, Any]:
    if slot.slot_type != "bgm_audio":
        return {}
    result_metadata = sanitize_context_for_llm_text(provider_result.metadata)
    provider_asset = result_metadata.get("provider_asset")
    provider_asset = provider_asset if isinstance(provider_asset, dict) else {}

    def value(key: str) -> Any:
        return result_metadata.get(key) or provider_asset.get(key) or provider_payload.get(key)

    audio_constraints = result_metadata.get("audio_constraints")
    if not isinstance(audio_constraints, dict):
        audio_constraints = provider_payload.get("audio_constraints")
    if not isinstance(audio_constraints, dict):
        audio_constraints = {"no_vocals": True, "no_lyrics": True}
    duration_seconds = value("requested_duration_seconds") or value("duration_seconds")
    return {
        "duration_seconds": duration_seconds,
        "requested_duration_seconds": value("requested_duration_seconds"),
        "provider_duration_seconds": value("provider_duration_seconds"),
        "provider_action": value("provider_action"),
        "query_action": value("query_action"),
        "api_version": value("api_version"),
        "generation_version": value("generation_version"),
        "remote_task_id": provider_result.remote_task_id,
        "source_content_type": value("source_content_type"),
        "source_extension": value("source_extension"),
        "music_mood": value("music_mood") or provider_payload.get("mood"),
        "pace": value("pace"),
        "audio_constraints": audio_constraints,
        "has_audio": True,
    }


def _required_reference_asset_ids(provider_payload: dict[str, Any]) -> list[str]:
    audit = provider_payload.get("reference_audit")
    if not isinstance(audit, dict):
        return []
    values = [
        *list(audit.get("required_reference_asset_ids") or []),
        *list(audit.get("dependency_reference_asset_ids") or []),
    ]
    return list(dict.fromkeys(item for item in (str(value).strip() for value in values) if item))


def _extension_for_media_type(media_type: str) -> str:
    return {"image": "png", "video": "mp4", "audio": "mp3", "text": "txt"}.get(
        media_type,
        "bin",
    )


def _require_reference_prefix(
    actual: list[str],
    expected: list[str],
    *,
    slot: WorkflowSlotV2,
    source: str,
) -> None:
    if actual[: len(expected)] == expected:
        return
    raise V2GenerationPipelineError(
        "shot_reference_contract_mismatch",
        f"Shot reference contract mismatch for {slot.node_id}/{slot.item_id}/{slot.slot_id}: "
        f"{source} diverged from resolver.",
    )
