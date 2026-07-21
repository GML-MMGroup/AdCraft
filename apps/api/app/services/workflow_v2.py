from dataclasses import dataclass, field
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import re
import threading
from typing import Any, Iterator
from uuid import uuid4

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.front_desk import FrontDeskChatRequest, FrontDeskChatResponse
from app.schemas.workflow_v2_intent import V2FrontDeskPlanningSeed, V2IntentValidationResult
from app.schemas.workflow_v2 import (
    V2AssetOwner,
    V2AssetOwnerResponse,
    V2GenerationTarget,
    V2GenerationPlan,
    V2ProviderResult,
    V2ProviderTask,
    V2ProviderTaskListResponse,
    V2ProviderTaskPollResult,
    V2ProviderTaskPollResponse,
    V2ProviderCallSummary,
    V2SlotVersionsResponse,
    V2SlotExecutionJob,
    V2SlotExecutionResult,
    WorkflowAssetRelationV2,
    WorkflowAssetVersionV2,
    WorkflowV2ChatActionRequest,
    WorkflowV2ChatActionResponse,
    WorkflowV2ChatActionTarget,
    WorkflowV2ResolvedChatActionTarget,
    WorkflowV2WorkingVersionView,
    WorkflowV2ChatTargetRequest,
    WorkflowV2ChatTargetResponse,
    WorkflowItemV2,
    WorkflowNodeV2,
    WorkflowV2Event,
    WorkflowV2EventListResponse,
    WorkflowV2FreeNodeAbsorbRequest,
    WorkflowV2FreeNodeAbsorbResponse,
    WorkflowV2FreeNodeCreateRequest,
    WorkflowV2FreeNodeGenerateRequest,
    WorkflowV2ItemGenerateRequest,
    WorkflowV2ShotDetailPromptPatchRequest,
    WorkflowV2ShotDetailPromptRefineRequest,
    WorkflowV2ShotPrimarySceneUpdateResponse,
    WorkflowV2ReferenceAttachRequest,
    WorkflowV2ReferenceMutationResponse,
    WorkflowV2RuntimeSnapshot,
    WorkflowV2RunStartResponse,
    WorkflowV2TimelineClipCreateRequest,
    WorkflowV2TimelineClipMutationResponse,
    WorkflowRuntimeV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2PlanFromChatResponse,
    WorkflowV2NormalizedPlanningRequestView,
    WorkflowV2PlanningClarificationResponse,
    WorkflowV2RunResponse,
    WorkflowV2PlanFromPromptRequest,
)
from app.schemas.workflow_v2_screenplay import (
    V2ScriptConfirmRequest,
    V2ScriptStructuralDiff,
)
from app.schemas.workflow_v2_style import VisualStyleScopeSource
from app.schemas.workflow_v2_provider_results import (
    V2ProviderExecutionContext,
    V2ProviderResultManifest,
)
from app.services.agent_trace import V2AgentTraceWriter, utc_now
from app.services.front_desk import FrontDeskError, FrontDeskService
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_agent_router import V2AgentRouteError, V2AgentRouter
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_creative_inventory import (
    apply_creative_inventory_to_expert_brief_plan,
    creative_inventory_has_explicit_constraints,
    creative_inventory_lineage,
)
from app.services.v2_creative_inventory_reconciler import (
    V2CreativeInventoryReconciler,
    V2CreativeInventoryReconciliationError,
)
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_relative_path
from app.services.v2_execution_service import TERMINAL_EXECUTION_STATUSES, V2ExecutionService
from app.services.v2_execution_recovery import V2ExecutionRecoveryService
from app.services.v2_expert_brief_planner import (
    V2ExpertBriefPlanner,
    V2ExpertBriefPlannerError,
)
from app.services.v2_final_composition import V2FinalCompositionService
from app.services.v2_generation_pipeline import (
    V2GenerationPipeline,
    V2GenerationPipelineError,
)
from app.services.v2_generation_integrity import (
    V2_GENERATION_INTEGRITY_VERSION,
    V2GenerationIntegrityError,
    extract_planning_constraints,
    validate_expert_brief_constraints,
    validate_script_plan_constraints,
)
from app.services.v2_input_assets import asset_locator
from app.services.v2_intent_contract import (
    ExplicitConstraintScanner,
    V2IntentPlanner,
    V2IntentPlannerError,
    V2IntentValidator,
    validation_summary,
)
from app.services.v2_linked_context import V2LinkedContextSynchronizer
from app.services.v2_provider_executor import V2ProviderExecutor
from app.services.v2_provider_result_committer import (
    V2ProviderResultCommitError,
    V2ProviderResultCommitter,
)
from app.services.v2_provider_result_store import V2ProviderResultStore, V2ProviderResultStoreError
from app.services.v2_provider_task_service import V2ProviderTaskService
from app.services.v2_parallel_slot_scheduler import (
    V2ParallelSlotSchedulerState,
    V2SlotDependencyGraph,
    concurrency_config_from_settings,
    is_final_composition_slot,
)
from app.services.v2_planning_seed import build_v2_planning_seed, canonicalize_v2_planning_seed
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_script_plan_reconciler import reconcile_script_plan
from app.services.v2_script_versions import V2ScriptVersionError, V2ScriptVersionService
from app.services.v2_script_writer import V2ScriptWriterError, V2ScriptWriterService
from app.services.v2_slot_scheduler import V2SlotScheduler
from app.services.v2_shot_reference_planner import (
    reference_dependency_slot_ids,
    resolve_storyboard_shot_references,
)
from app.services.v2_shot_reference_resolver import V2ShotReferenceResolver
from app.services.v2_specialist_handoff import (
    V2SpecialistHandoffBuilder,
    V2SpecialistHandoffError,
)
from app.services.v2_storyboard_defaults import shot_cell_slot_types
from app.services.v2_storyboard_director import (
    V2StoryboardDirector,
    apply_shot_video_prompts,
)
from app.services.v2_storyboard_detail_materializer import (
    V2StoryboardDetailMaterializerError,
)
from app.services.v2_storyboard_planning import (
    plan_storyboard_config,
)
from app.services.v2_versioning import (
    V2_BACKEND_REVISION_EVIDENCE,
    V2_EXPERT_BRIEF_BUILDER_VERSION,
    V2_PLANNER_VERSION,
    V2_SCRIPT_WRITER_VERSION,
)
from app.services.v2_visual_style import V2VisualStyleService
from app.services.v2_visual_style_scope import V2VisualStyleScopeService
from app.services.v2_workflow_lock import v2_workflow_lock
from app.services.v2_workflow_planner import V2WorkflowPlanner, build_slot
from app.services.v2_workflow_store import (
    V2WorkflowStore,
    workflow_v2_path,
    workflow_v2_runtime_dir,
)

__all__ = [
    "WorkflowV2Error",
    "WorkflowV2Service",
    "workflow_v2_path",
    "workflow_v2_runtime_dir",
]


class WorkflowV2Error(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


def _intent_validation_error_details(
    stage: str,
    validation: V2IntentValidationResult,
) -> dict[str, Any]:
    sanitized = sanitize_context_for_llm_text(
        {
            "stage": stage,
            "violations": [
                violation.model_dump(mode="json") for violation in validation.violations
            ],
        }
    )
    return sanitized if isinstance(sanitized, dict) else {"stage": stage, "violations": []}


def _creative_product_identity_terms(creative_inventory: Any) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for product in getattr(creative_inventory, "products", []) or []:
        for value in (
            getattr(product, "display_name", None),
            getattr(product, "item_id", None),
        ):
            text = str(value or "").strip()
            if len(text) < 2:
                continue
            key = text.casefold()
            if key in seen:
                continue
            terms.append(text)
            seen.add(key)
    return terms


def _creative_product_display_names(creative_inventory: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for product in getattr(creative_inventory, "products", []) or []:
        name = str(getattr(product, "display_name", None) or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def _select_product_name_for_scope(
    creative_inventory: Any,
    values: list[str],
) -> str | None:
    product_names = _creative_product_display_names(creative_inventory)
    if len(product_names) == 1:
        return product_names[0]
    matches = [
        product_name
        for product_name in product_names
        if any(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(product_name)}(?![A-Za-z0-9_])",
                value,
                flags=re.IGNORECASE,
            )
            for value in values
            if isinstance(value, str) and value.strip()
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _planning_request_with_effective_visual_style(
    request: WorkflowV2PlanFromPromptRequest,
    normalized_request: dict[str, Any] | None,
    *,
    visual_style: str,
) -> tuple[WorkflowV2PlanFromPromptRequest, dict[str, Any] | None]:
    metadata = dict(request.metadata)
    front_desk_request = metadata.get("front_desk_ad_request")
    if isinstance(front_desk_request, dict):
        metadata["front_desk_ad_request"] = {
            **front_desk_request,
            "visual_style": visual_style,
        }
    effective_request = request.model_copy(
        update={"visual_style": visual_style, "metadata": metadata},
        deep=True,
    )
    effective_normalized_request = None
    if normalized_request is not None:
        effective_normalized_request = {
            **normalized_request,
            "visual_style": visual_style,
        }
    return effective_request, effective_normalized_request


def _scope_non_product_expert_briefs(
    expert_brief_plan: Any,
    *,
    product_names: list[str],
) -> Any:
    patterns = [
        re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(product_name)}(?![A-Za-z0-9_])",
            flags=re.IGNORECASE,
        )
        for product_name in product_names
        if product_name.strip()
    ]
    if not patterns:
        return expert_brief_plan

    def scoped_value(value: Any) -> Any:
        if isinstance(value, str):
            scoped = value
            for pattern in patterns:
                scoped = pattern.sub("the advertised product", scoped)
            return scoped
        if isinstance(value, list):
            return [scoped_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: scoped_value(item)
                for key, item in value.items()
                if key != "product_identity_constraints"
            }
        return value

    def scoped_brief(brief: Any) -> Any:
        return brief.model_copy(
            update={
                "description": scoped_value(brief.description),
                "item_prompt": scoped_value(brief.item_prompt),
                "creative_brief": scoped_value(brief.creative_brief),
                "slot_prompts": scoped_value(brief.slot_prompts),
                "asset_prompts": scoped_value(brief.asset_prompts),
                "metadata": scoped_value(brief.metadata),
            },
            deep=True,
        )

    return expert_brief_plan.model_copy(
        update={
            "character_briefs": [
                scoped_brief(brief) for brief in expert_brief_plan.character_briefs
            ],
            "scene_briefs": [scoped_brief(brief) for brief in expert_brief_plan.scene_briefs],
        },
        deep=True,
    )


@dataclass
class _SchedulerRunResult:
    executed_slot_ids: list[str] = field(default_factory=list)
    provider_calls: list[dict[str, Any]] = field(default_factory=list)
    slot_transitions: list[dict[str, Any]] = field(default_factory=list)
    failed_slot_ids: list[str] = field(default_factory=list)
    waiting_slot_ids: list[str] = field(default_factory=list)
    created_item_ids: list[str] = field(default_factory=list)
    created_slot_ids: list[str] = field(default_factory=list)


class WorkflowV2Service:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._asset_store = V2AssetStoreService(self._data_dir)
        self._workflow_store = V2WorkflowStore(self._data_dir)
        self._runtime_events = V2RuntimeEventService(self._data_dir)
        self._planner = V2WorkflowPlanner()
        self._explicit_constraint_scanner = ExplicitConstraintScanner()
        self._intent_planner = V2IntentPlanner(settings)
        self._intent_validator = V2IntentValidator()
        self._creative_inventory_reconciler = V2CreativeInventoryReconciler()
        self._script_writer = V2ScriptWriterService(settings)
        self._script_versions = V2ScriptVersionService(self._data_dir)
        self._specialist_handoffs = V2SpecialistHandoffBuilder(self._data_dir)
        self._expert_brief_planner = V2ExpertBriefPlanner(settings)
        self._storyboard_director = V2StoryboardDirector(settings)
        self._final_composition = V2FinalCompositionService()
        self._agent_router = V2AgentRouter()
        self._provider_executor = V2ProviderExecutor(
            settings=settings,
            data_dir=self._data_dir,
        )
        self._execution_service = V2ExecutionService(self._data_dir)
        self._execution_recovery = V2ExecutionRecoveryService(
            self._data_dir,
            stale_running_timeout_seconds=settings.v2_stale_running_timeout_seconds,
        )
        self._provider_task_store = V2ProviderTaskService(
            self._data_dir,
            poll_interval_seconds=settings.v2_provider_task_poll_interval_seconds,
            timeout_seconds=settings.v2_provider_task_timeout_seconds,
        )
        self._provider_result_store = V2ProviderResultStore(self._data_dir)
        self._provider_result_committer = V2ProviderResultCommitter(self._data_dir)
        self._visual_style_service = V2VisualStyleService()
        self._visual_style_scope_service = V2VisualStyleScopeService(
            self._visual_style_service,
            settings=settings,
        )
        self._slot_scheduler = V2SlotScheduler(
            asset_exists=self._asset_store.asset_exists,
            shot_reference_resolver=V2ShotReferenceResolver(self._data_dir),
        )
        self._execution_context = threading.local()
        self._event_context = threading.local()
        self._provider_poll_threads: dict[tuple[str, str], threading.Thread] = {}
        self._provider_poll_threads_lock = threading.Lock()
        self._generation_pipeline = V2GenerationPipeline(
            data_dir=self._data_dir,
            asset_store=self._asset_store,
            settings=settings,
            router=self._agent_router,
            provider_executor=self._provider_executor,
            task_store=self._provider_task_store,
        )

    def plan_from_prompt(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        planning_seed: V2FrontDeskPlanningSeed | None = None,
    ) -> WorkflowV2 | WorkflowV2PlanningClarificationResponse:
        self._asset_store.ensure_directories()
        normalized_request = (
            request.metadata.get("front_desk_ad_request")
            if isinstance(request.metadata.get("front_desk_ad_request"), dict)
            else None
        )
        workflow_id = f"adwf_v2_{uuid4().hex[:12]}"
        input_assets = self._resolve_input_asset_locators(request.input_asset_locators)
        if not request.product_name and any(
            record.semantic_type == "product_reference" for record in input_assets
        ):
            request = request.model_copy(update={"product_name": "Product"}, deep=True)
        explicit_constraints = self._explicit_constraint_scanner.scan(
            request,
            normalized_request=normalized_request,
        )
        planner_kwargs: dict[str, Any] = {
            "normalized_request": normalized_request,
            "explicit_constraints": explicit_constraints,
            "workflow_id_seed": workflow_id,
        }
        if planning_seed is not None:
            planner_kwargs["planning_seed"] = planning_seed
        try:
            intent_outcome = self._intent_planner.plan(
                request,
                **planner_kwargs,
            )
        except V2IntentPlannerError as exc:
            details = sanitize_context_for_llm_text(
                {
                    **exc.details,
                    "planning_id": workflow_id,
                }
            )
            if not isinstance(details, dict):
                details = {"planning_id": workflow_id}
            self._append_planning_trace(
                workflow_id,
                stage="intent",
                error_code=exc.code,
                details=details,
            )
            if exc.code == "v2_intent_clarification_required":
                return WorkflowV2PlanningClarificationResponse(
                    error_code=exc.code,
                    message=str(exc),
                    details=details,
                    suggested_actions=_intent_clarification_suggested_actions(details),
                )
            raise WorkflowV2Error(exc.code, str(exc), details=details) from exc

        try:
            reconciliation = self._creative_inventory_reconciler.reconcile(
                request,
                explicit_constraints=explicit_constraints,
                intent_plan=intent_outcome.intent_plan,
            )
        except V2CreativeInventoryReconciliationError as exc:
            raise WorkflowV2Error(exc.code, str(exc), details=exc.details) from exc

        intent_plan = reconciliation.intent_plan
        intent_product_name = intent_plan.products[0].display_name if intent_plan.products else None
        if intent_product_name and not request.product_name:
            request = request.model_copy(update={"product_name": intent_product_name}, deep=True)
        creative_inventory = reconciliation.creative_inventory
        inventory_payload = creative_inventory.model_dump(mode="json")
        inventory_lineage = creative_inventory_lineage(creative_inventory)
        if reconciliation.clarification is not None:
            clarification = reconciliation.clarification
            return WorkflowV2PlanningClarificationResponse(
                error_code=clarification.error_code or "storyboard_planning_failed",
                message=clarification.message or "Storyboard planning needs clarification.",
                details=clarification.details,
                suggested_actions=clarification.suggested_actions,
            )
        scope_product_name = _select_product_name_for_scope(
            creative_inventory,
            [
                str(request.visual_style or ""),
                str(getattr(intent_plan, "visual_style", None) or ""),
            ],
        )
        if scope_product_name is None and not creative_inventory.products:
            scope_product_name = intent_product_name or request.product_name
        style_resolution = self._visual_style_scope_service.resolve_for_planning(
            raw_visual_style=request.visual_style,
            inferred_visual_style=getattr(intent_plan, "visual_style", None),
            product_name=scope_product_name,
            product_identity_terms=_creative_product_identity_terms(creative_inventory),
        )
        visual_style_contract = self._visual_style_service.resolve_for_planning(
            request,
            intent_plan=intent_plan,
            scoped_contract=style_resolution.contract,
        )
        reconciled_intent_validation = self._intent_validator.validate(
            intent_plan,
            explicit_constraints=explicit_constraints,
            original_prompt=request.prompt,
            normalized_request=normalized_request,
        )
        if not reconciled_intent_validation.valid:
            raise WorkflowV2Error(
                "v2_intent_reconciliation_failed",
                "Reconciled intent did not preserve explicit planning constraints.",
            )
        intent_metadata = {
            "intent_contract_version": intent_plan.intent_contract_version,
            "intent_plan": intent_plan.model_dump(mode="json"),
            "intent_validation": validation_summary(reconciled_intent_validation),
            "intent_repair_used": intent_outcome.intent_repair_used,
            "intent_fallback_used": intent_outcome.intent_fallback_used,
            "explicit_constraints": explicit_constraints.model_dump(mode="json"),
            "inventory_reconciliation_audit": reconciliation.audit_metadata,
        }
        request = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "creative_inventory_spec": inventory_payload,
                    **inventory_lineage,
                    **intent_metadata,
                    "visual_style_contract": visual_style_contract.model_dump(mode="json"),
                    "visual_style_scope_audit": style_resolution.audit.model_dump(mode="json"),
                }
            },
            deep=True,
        )
        requested_shot_count = creative_inventory.storyboard_shot_count
        requested_shot_count_source = str(
            creative_inventory.source_map.get("storyboard_shot_count", {}).get("source")
            or intent_plan.storyboard.source
            or "default"
        )
        storyboard_plan = plan_storyboard_config(
            duration_seconds=request.duration_seconds,
            requested_shot_count=requested_shot_count,
            requested_shot_count_source=(
                requested_shot_count_source
                if requested_shot_count_source in {"default", "inferred", "explicit"}
                else "inferred"
            ),
        )
        if storyboard_plan.status == "needs_clarification":
            return WorkflowV2PlanningClarificationResponse(
                error_code=storyboard_plan.error_code or "storyboard_planning_failed",
                message=storyboard_plan.message or "Storyboard planning needs clarification.",
                details=storyboard_plan.details,
                suggested_actions=storyboard_plan.suggested_actions,
            )
        planning_constraints = extract_planning_constraints(
            request,
            normalized_request=normalized_request,
            storyboard_config=storyboard_plan.storyboard_config,
        )
        request = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "storyboard_config": storyboard_plan.storyboard_config,
                    "planning_constraints": planning_constraints.model_dump(mode="json"),
                    "generation_integrity_version": V2_GENERATION_INTEGRITY_VERSION,
                    **intent_metadata,
                }
            },
            deep=True,
        )
        planning_request, planning_normalized_request = (
            _planning_request_with_effective_visual_style(
                request,
                normalized_request,
                visual_style=visual_style_contract.style_prompt,
            )
        )
        input_asset_descriptors = [_input_asset_descriptor(record) for record in input_assets]
        try:
            script_plan = self._script_writer.write_script(
                planning_request,
                workflow_id=workflow_id,
                input_asset_descriptors=input_asset_descriptors,
                normalized_request=planning_normalized_request,
            )
        except V2ScriptWriterError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        script_reconciliation = reconcile_script_plan(
            script_plan,
            inventory=creative_inventory,
            storyboard_config=storyboard_plan.storyboard_config,
        )
        script_plan = script_reconciliation.script_plan
        repaired_validation_codes: list[str] = []
        script_intent_validation = self._intent_validator.validate(
            intent_plan,
            explicit_constraints=explicit_constraints,
            original_prompt=request.prompt,
            normalized_request=normalized_request,
            script_plan=script_plan,
        )
        if not script_intent_validation.valid:
            repaired_validation_codes = [
                violation.code for violation in script_intent_validation.violations
            ]
            original_error_code = (
                repaired_validation_codes[0]
                if repaired_validation_codes
                else "v2_intent_validation_failed"
            )
            try:
                fallback_draft = self._script_writer.build_deterministic_fallback(
                    planning_request,
                    workflow_id=workflow_id,
                    input_asset_descriptors=input_asset_descriptors,
                    original_error_code=original_error_code,
                )
            except Exception as exc:  # noqa: BLE001 - normalized at the fallback boundary.
                details = _intent_validation_error_details(
                    "script_fallback",
                    script_intent_validation,
                )
                self._append_planning_trace(
                    workflow_id,
                    stage="script_fallback",
                    error_code="v2_intent_fallback_failed",
                    details=details,
                    script_reconciliation=script_reconciliation.audit.model_dump(mode="json"),
                )
                raise WorkflowV2Error(
                    "v2_intent_fallback_failed",
                    "Deterministic script fallback could not produce a valid plan.",
                    details=details,
                ) from exc
            script_reconciliation = reconcile_script_plan(
                fallback_draft,
                inventory=creative_inventory,
                storyboard_config=storyboard_plan.storyboard_config,
            )
            script_plan = script_reconciliation.script_plan
            script_intent_validation = self._intent_validator.validate(
                intent_plan,
                explicit_constraints=explicit_constraints,
                original_prompt=request.prompt,
                normalized_request=normalized_request,
                script_plan=script_plan,
            )
            if not script_intent_validation.valid:
                details = _intent_validation_error_details(
                    "script_plan",
                    script_intent_validation,
                )
                self._append_planning_trace(
                    workflow_id,
                    stage="script_plan",
                    error_code="v2_intent_validation_failed",
                    details=details,
                    script_reconciliation=script_reconciliation.audit.model_dump(mode="json"),
                )
                raise WorkflowV2Error(
                    "v2_intent_validation_failed",
                    "Reconciled script plan violated the validated V2 planning contract.",
                    details=details,
                )
        try:
            validate_script_plan_constraints(script_plan, planning_constraints)
        except V2GenerationIntegrityError as exc:
            code = (
                "creative_inventory_invalid"
                if creative_inventory_has_explicit_constraints(creative_inventory)
                else exc.code
            )
            raise WorkflowV2Error(code, str(exc)) from exc
        degraded_metadata: dict[str, Any] = {}
        if script_reconciliation.audit.fallback_used:
            degraded_metadata = {
                "planning_degraded": True,
                "fallback_stage": "script_writer",
                "original_error_code": script_reconciliation.audit.original_error_code,
                "repaired_violation_codes": list(
                    dict.fromkeys(
                        [
                            *repaired_validation_codes,
                            *script_reconciliation.audit.repair_codes,
                        ]
                    )
                ),
            }
        now = utc_now().isoformat()
        workflow = WorkflowV2(
            workflow_id=workflow_id,
            name=request.product_name or "V2 Workflow",
            description="Prompt-only preset production flow.",
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            output_resolution=request.output_resolution,
            audio_mode=request.audio_mode,
            nodes=[],
            edges=[],
            runtime=WorkflowRuntimeV2(workflow_id=workflow_id),
            metadata={
                "original_user_prompt": request.prompt,
                "visual_style_contract": visual_style_contract.model_dump(mode="json"),
                "visual_style_scope_audit": style_resolution.audit.model_dump(mode="json"),
                "script_plan": script_plan.model_dump(mode="json"),
                "script_reconciliation": script_reconciliation.audit.model_dump(mode="json"),
                "v2_planner_version": V2_PLANNER_VERSION,
                "script_writer_version": V2_SCRIPT_WRITER_VERSION,
                "expert_brief_builder_version": V2_EXPERT_BRIEF_BUILDER_VERSION,
                "created_by_backend_revision": V2_BACKEND_REVISION_EVIDENCE,
                "request": request.model_dump(mode="json"),
                "input_asset_descriptors": input_asset_descriptors,
                "planner_warnings": [],
                "creative_inventory_spec": inventory_payload,
                **inventory_lineage,
                "storyboard_config": storyboard_plan.storyboard_config,
                "planning_constraints": planning_constraints.model_dump(mode="json"),
                "generation_integrity_version": V2_GENERATION_INTEGRITY_VERSION,
                **degraded_metadata,
                **intent_metadata,
            },
            created_at=now,
            updated_at=now,
        )
        resolve_storyboard_shot_references(
            workflow,
            [shot.model_dump(mode="json") for shot in script_plan.shots],
        )
        workflow = self.save_workflow(workflow)
        try:
            selected_script = self._script_versions.read_selected(workflow_id)
        except V2ScriptVersionError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        script_plan = selected_script.script
        workflow = self._workflow_store.load_workflow(workflow_id)
        self._bind_prompt_product_references(workflow, request, input_assets=input_assets)
        workflow = self.save_workflow(workflow)
        try:
            specialist_handoffs = self._specialist_handoffs.build_initial_planning_handoffs(
                workflow
            )
        except V2SpecialistHandoffError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        try:
            expert_brief_plan = self._expert_brief_planner.plan_briefs(
                script_plan,
                planning_request,
                workflow_id=workflow_id,
                input_asset_descriptors=input_asset_descriptors,
                normalized_request=planning_normalized_request,
                specialist_handoffs=specialist_handoffs,
            )
        except V2ExpertBriefPlannerError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        expert_brief_plan = apply_creative_inventory_to_expert_brief_plan(
            expert_brief_plan,
            creative_inventory,
        )
        constraint_product_name = _select_product_name_for_scope(
            creative_inventory,
            style_resolution.product_identity_constraints,
        )
        expert_brief_plan = self._visual_style_scope_service.attach_product_constraints(
            expert_brief_plan,
            product_name=constraint_product_name,
            product_identity_constraints=style_resolution.product_identity_constraints,
        )
        expert_brief_plan = _scope_non_product_expert_briefs(
            expert_brief_plan,
            product_names=_creative_product_display_names(creative_inventory),
        )
        downstream_intent_validation = self._intent_validator.validate(
            intent_plan,
            explicit_constraints=explicit_constraints,
            original_prompt=request.prompt,
            normalized_request=normalized_request,
            script_plan=script_plan,
            expert_brief_plan=expert_brief_plan,
        )
        if not downstream_intent_validation.valid:
            details = _intent_validation_error_details(
                "expert_brief_plan",
                downstream_intent_validation,
            )
            self._append_planning_trace(
                workflow_id,
                stage="expert_brief_plan",
                error_code="v2_intent_validation_failed",
                details=details,
                script_reconciliation=script_reconciliation.audit.model_dump(mode="json"),
            )
            raise WorkflowV2Error(
                "v2_intent_validation_failed",
                "Reconciled expert briefs violated the validated V2 planning contract.",
                details=details,
            )
        intent_metadata["intent_validation"] = validation_summary(downstream_intent_validation)
        try:
            validate_expert_brief_constraints(expert_brief_plan, planning_constraints)
        except V2GenerationIntegrityError as exc:
            code = (
                "creative_inventory_invalid"
                if creative_inventory_has_explicit_constraints(creative_inventory)
                else exc.code
            )
            raise WorkflowV2Error(code, str(exc)) from exc
        self._append_planning_trace(
            workflow_id,
            stage="planning_completed",
            error_code=None,
            details={
                "violations": [],
                "authoritative_inventory_lineage": inventory_lineage,
                "storyboard_config": storyboard_plan.storyboard_config,
                "visual_style_contract": visual_style_contract.model_dump(mode="json"),
                "visual_style_scope_audit": style_resolution.audit.model_dump(mode="json"),
            },
            script_reconciliation=script_reconciliation.audit.model_dump(mode="json"),
        )
        planner_warnings = _planner_warnings(expert_brief_plan)
        workflow = workflow.model_copy(
            update={
                "nodes": self._planner.build_default_nodes(
                    workflow_id,
                    planning_request,
                    script_plan,
                    expert_brief_plan,
                ),
                "edges": self._planner.build_display_edges(workflow_id),
                "metadata": {
                    **workflow.metadata,
                    "expert_brief_plan": expert_brief_plan.model_dump(mode="json"),
                    "specialist_quality_audit": dict(expert_brief_plan.specialist_quality_audit),
                    "planner_warnings": planner_warnings,
                    **intent_metadata,
                },
                "updated_at": utc_now().isoformat(),
            },
            deep=True,
        )
        initial_linked = V2LinkedContextSynchronizer().synchronize(
            workflow,
            script_plan,
            script_plan,
            V2ScriptStructuralDiff(),
        )
        workflow = initial_linked.workflow
        self._hydrate_prompt_product_reference_state(workflow)
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        if script_plan.shots:
            self._append_event(
                workflow.workflow_id,
                "workflow_structure_updated",
                payload={
                    "script_version_id": script_plan.script_version_id,
                    "added_shot_ids": [shot.shot_id for shot in script_plan.shots],
                    "archived_shot_ids": [],
                    "reactivated_shot_ids": [],
                    "item_ids": initial_linked.summary.updated_item_ids,
                    "refresh": ["workflow", "script"],
                },
            )
        if initial_linked.summary.updated_item_ids:
            self._append_event(
                workflow.workflow_id,
                "linked_context_updated",
                payload={
                    "script_version_id": script_plan.script_version_id,
                    "node_ids": initial_linked.summary.updated_node_ids,
                    "item_ids": initial_linked.summary.updated_item_ids,
                    "slot_ids": initial_linked.summary.updated_slot_ids,
                    "updated_fields": initial_linked.summary.updated_fields,
                    "selected_asset_versions_changed": False,
                    "provider_execution_started": False,
                    "refresh": initial_linked.summary.refresh,
                },
            )
        self._append_event(
            workflow.workflow_id,
            "workflow_created",
            payload={
                "workflow_id": workflow_id,
                "v2_planner_version": V2_PLANNER_VERSION,
                "script_writer_version": V2_SCRIPT_WRITER_VERSION,
                "expert_brief_builder_version": V2_EXPERT_BRIEF_BUILDER_VERSION,
                "created_by_backend_revision": V2_BACKEND_REVISION_EVIDENCE,
                "script_plan_present": bool(workflow.metadata.get("script_plan")),
                "expert_brief_plan_present": bool(workflow.metadata.get("expert_brief_plan")),
                "planning_constraints_present": bool(workflow.metadata.get("planning_constraints")),
                "generation_integrity_version": V2_GENERATION_INTEGRITY_VERSION,
            },
        )
        return self._workflow_store.load_workflow(workflow_id)

    def plan_from_chat(
        self,
        request: FrontDeskChatRequest,
        front_desk_service: FrontDeskService | None = None,
    ) -> WorkflowV2PlanFromChatResponse:
        service = front_desk_service or FrontDeskService(self._settings)
        v2_chat_request = request.model_copy(update={"workflow_schema_version": 2})
        try:
            front_desk = service.chat(v2_chat_request)
        except FrontDeskError as exc:
            raise WorkflowV2Error("front_desk_failed", str(exc)) from exc
        except Exception as exc:
            raise WorkflowV2Error("front_desk_failed", str(exc)) from exc

        if not front_desk.should_start_workflow:
            return WorkflowV2PlanFromChatResponse(front_desk=front_desk, workflow=None)
        if front_desk.ad_request is None:
            raise WorkflowV2Error(
                "invalid_front_desk_state",
                "Front Desk returned ready_for_workflow without ad_request.",
            )
        v2_request = _v2_request_from_chat(v2_chat_request, front_desk.ad_request)
        raw_seed = front_desk.v2_planning_seed or build_v2_planning_seed(front_desk.ad_request)
        canonicalization = canonicalize_v2_planning_seed(raw_seed, v2_request)
        planning_seed = canonicalization.seed
        front_desk = front_desk.model_copy(
            update={"v2_planning_seed": planning_seed},
            deep=True,
        )
        normalized_v2_request = _normalized_v2_request_view(
            v2_request,
            planning_seed=planning_seed,
        )
        workflow = self.plan_from_prompt(v2_request, planning_seed=planning_seed)
        if isinstance(workflow, WorkflowV2PlanningClarificationResponse):
            return WorkflowV2PlanFromChatResponse(
                front_desk=_front_desk_clarification_response(front_desk, workflow),
                workflow=None,
                normalized_v2_request=normalized_v2_request,
                status=workflow.status,
                error_code=workflow.error_code,
                message=workflow.message,
                details=workflow.details,
                suggested_actions=workflow.suggested_actions,
            )
        return WorkflowV2PlanFromChatResponse(
            front_desk=front_desk,
            workflow=workflow,
            normalized_v2_request=normalized_v2_request,
        )

    def _append_planning_trace(
        self,
        workflow_id: str,
        *,
        stage: str,
        error_code: str | None,
        details: dict[str, Any],
        script_reconciliation: dict[str, Any] | None = None,
    ) -> None:
        sanitized_details = sanitize_context_for_llm_text(details)
        if not isinstance(sanitized_details, dict):
            sanitized_details = {}
        sanitized_reconciliation = sanitize_context_for_llm_text(script_reconciliation or {})
        if not isinstance(sanitized_reconciliation, dict):
            sanitized_reconciliation = {}
        repair_mode = "none"
        if sanitized_reconciliation.get("fallback_used"):
            repair_mode = "fallback"
        elif sanitized_reconciliation.get("repair_used"):
            repair_mode = "repair"
        started_at = utc_now()
        V2AgentTraceWriter(self._data_dir, workflow_id).append(
            agent="V2 Planning",
            model=self._settings.llm_script_model,
            prompt="Validate reconciled V2 planning contracts.",
            output={
                "script_reconciliation": sanitized_reconciliation,
            },
            error=error_code,
            started_at=started_at,
            finished_at=utc_now(),
            duration_ms=0,
            metadata={
                "trace_role": "planning",
                "stage": stage,
                "planning_id": workflow_id,
                "error_code": error_code,
                "violations": list(sanitized_details.get("violations") or []),
                "attempts": list(sanitized_details.get("attempts") or []),
                "repair_mode": repair_mode,
                "authoritative_inventory_lineage": dict(
                    sanitized_details.get("authoritative_inventory_lineage") or {}
                ),
                "storyboard_config": dict(sanitized_details.get("storyboard_config") or {}),
                "visual_style_contract": dict(sanitized_details.get("visual_style_contract") or {}),
                "visual_style_scope_audit": dict(
                    sanitized_details.get("visual_style_scope_audit") or {}
                ),
            },
        )

    def get_workflow(self, workflow_id: str) -> WorkflowV2:
        return self._workflow_store.load_workflow(workflow_id)

    def _bind_prompt_product_references(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        input_assets: list[WorkflowAssetVersionV2] | None = None,
    ) -> None:
        product = self._find_product_reference_target(workflow)
        if product is None:
            product = self._create_default_product_item(workflow, request)
        product_main_slot = _slot_by_type(product, "product_main_image")
        seen_asset_ids: set[str] = set()
        for record in input_assets or []:
            if record.semantic_type != "product_reference":
                continue
            if product_main_slot is None:
                continue
            relation = self._asset_store.create_relation(
                relation_type="reference_for_slot",
                source_asset_id=record.asset_id,
                target_workflow_id=workflow.workflow_id,
                target_node_id="product-generation",
                target_item_id=product.item_id,
                target_slot_id=product_main_slot.slot_id,
                metadata={
                    "version_id": record.version_id,
                    "source_version_id": record.version_id,
                    "reference_kind": "explicit",
                    "reference_role": "product",
                    "source": "v2_input_asset_locator",
                    "locator": asset_locator(record.asset_id, record.version_id),
                },
            )
            _append_unique(
                product_main_slot.metadata, "reference_relation_ids", relation.relation_id
            )
            if record.asset_id not in product_main_slot.explicit_reference_ids:
                product_main_slot.explicit_reference_ids.append(record.asset_id)
            seen_asset_ids.add(record.asset_id)
        for asset in _product_reference_assets_from_request(request):
            try:
                record = self._asset_store.register_external_asset(
                    asset,
                    workflow_id=workflow.workflow_id,
                    node_id="product-generation",
                    item_id=product.item_id,
                    semantic_type="product_reference",
                )
            except V2DataBoundaryError as exc:
                raise WorkflowV2Error(exc.code, str(exc)) from exc
            if record.asset_id in seen_asset_ids:
                continue
            seen_asset_ids.add(record.asset_id)
            relation = self._asset_store.create_relation(
                relation_type="reference_for_item",
                source_asset_id=record.asset_id,
                target_workflow_id=workflow.workflow_id,
                target_node_id="product-generation",
                target_item_id=product.item_id,
                metadata={
                    "reference_kind": "product_reference",
                    "reference_mode": request.reference_mode,
                    "source": "v2_prompt_to_workflow",
                },
            )
            _append_unique(product.metadata, "reference_relation_ids", relation.relation_id)
            _append_unique(product.metadata, "explicit_reference_asset_ids", record.asset_id)
            product.metadata["reference_mode"] = request.reference_mode

    def _hydrate_prompt_product_reference_state(self, workflow: WorkflowV2) -> None:
        product = self._find_product_reference_target(workflow)
        if product is None:
            return
        product_main_slot = _slot_by_type(product, "product_main_image")
        relations = self._asset_store.list_relations(
            target_workflow_id=workflow.workflow_id,
        )
        for relation in relations:
            if relation.target_item_id != product.item_id:
                continue
            if relation.relation_type == "reference_for_slot" and product_main_slot is not None:
                if relation.target_slot_id != product_main_slot.slot_id:
                    continue
                _append_unique(
                    product_main_slot.metadata,
                    "reference_relation_ids",
                    relation.relation_id,
                )
                if relation.source_asset_id not in product_main_slot.explicit_reference_ids:
                    product_main_slot.explicit_reference_ids.append(relation.source_asset_id)
            elif relation.relation_type == "reference_for_item":
                _append_unique(
                    product.metadata,
                    "reference_relation_ids",
                    relation.relation_id,
                )
                _append_unique(
                    product.metadata,
                    "explicit_reference_asset_ids",
                    relation.source_asset_id,
                )

    def _resolve_input_asset_locators(
        self,
        locators: list[str],
    ) -> list[WorkflowAssetVersionV2]:
        records: list[WorkflowAssetVersionV2] = []
        for locator in locators:
            asset_id, version_id = _parse_input_asset_locator(locator)
            record = self._asset_store.load_asset_version(asset_id, version_id)
            if record is None:
                raise WorkflowV2Error("asset_not_found")
            try:
                from app.services.v2_data_boundary import validate_v2_relative_path

                validate_v2_relative_path(record.file_path, operation="v2-input-asset-read")
            except V2DataBoundaryError as exc:
                raise WorkflowV2Error(exc.code, str(exc)) from exc
            if not (self._data_dir / record.file_path).exists():
                raise WorkflowV2Error("asset_not_found")
            records.append(record)
        return records

    def _find_product_reference_target(self, workflow: WorkflowV2) -> WorkflowItemV2 | None:
        node = _node_by_id(workflow, "product-generation")
        if node is None:
            return None
        product_items = [
            item
            for item in node.items
            if item.lifecycle_state == "active" and item.item_type == "product"
        ]
        if not product_items:
            return None
        expert_items = [
            item
            for item in product_items
            if item.item_id != "product-1"
            and item.metadata.get("item_source") != "deterministic_fallback"
        ]
        if expert_items:
            return expert_items[0]
        return product_items[0]

    def _create_default_product_item(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> WorkflowItemV2:
        product_name = request.product_name or "Product 1"
        product = WorkflowItemV2(
            item_id="product-1",
            node_id="product-generation",
            item_type="product",
            display_name=product_name,
            description=f"Product reference target for {product_name}.",
            item_prompt=f"Product reference target for {product_name}.",
            status="empty",
            slots=[
                build_slot(
                    node_id="product-generation",
                    item_id="product-1",
                    slot_type="product_main_image",
                    media_type="image",
                    status="empty",
                    prompt=f"Create a clear main product reference image for {product_name}.",
                ),
                build_slot(
                    node_id="product-generation",
                    item_id="product-1",
                    slot_type="product_multi_view_grid",
                    media_type="image",
                    status="blocked",
                    prompt=f"Create a multi-view product reference grid for {product_name}.",
                    dependency_slot_ids=["product-1:product_main_image"],
                ),
            ],
            metadata={
                "item_source": "deterministic_fallback",
                "fallback_reason": "product_reference_binding_no_product_item",
            },
        )
        product.display_name = "Product 1"
        node = _node_by_id(workflow, "product-generation")
        if node is None:
            node = WorkflowNodeV2(
                node_id="product-generation",
                node_type="product-generation",
                title="Product Generation",
                status="ready",
                position={"x": 320, "y": -180},
                items=[],
                metadata={"workflow_id": workflow.workflow_id},
            )
            workflow.nodes.append(node)
        node.items.append(product)
        return product

    def run_workflow(
        self,
        workflow_id: str,
        *,
        wait: bool = False,
        mode: str = "fill_missing_required_slots",
        source_action: str = "global_run",
    ) -> WorkflowV2RunResponse | WorkflowV2RunStartResponse:
        self._asset_store.ensure_directories()
        workflow = self._preflight_visual_style_scope(
            workflow_id,
            source="run_preflight",
        )
        self._recover_pending_provider_manifests(workflow)
        workflow = self._execution_recovery.recover_interrupted_execution(
            workflow_id,
            trigger="run_preflight",
        ).workflow
        reopened_tasks = self._reopen_historical_provider_result_tasks(workflow)
        if reopened_tasks:
            self._poll_provider_task_batch(
                workflow_id,
                reopened_tasks,
                execution_id=None,
            )
        if reopened_tasks:
            workflow = self.get_workflow(workflow_id)
        active = self._execution_service.load_active(workflow_id)
        if active is not None:
            runtime = self.runtime_snapshot(workflow_id)
            return WorkflowV2RunStartResponse(
                workflow_id=workflow_id,
                execution_id=str(active["execution_id"]),
                status=str(active.get("status") or "running"),  # type: ignore[arg-type]
                runtime=runtime.model_dump(mode="json"),
                events_cursor=runtime.events_cursor,
                message="Active workflow execution already exists.",
            )

        execution_id = self._execution_service.new_execution_id()
        state = self._initial_execution_state(
            workflow,
            execution_id,
            mode=mode,
            source_action=source_action,
        )
        self._execution_service.save_state(workflow_id, execution_id, state)
        self._execution_service.set_active(workflow_id, execution_id)
        event = self._append_event(
            workflow_id,
            "execution_queued",
            payload={
                "workflow_id": workflow_id,
                "execution_id": execution_id,
                "target_slot_ids": state["target_slot_ids"],
            },
        )
        for slot_id in state["target_slot_ids"]:
            runtime = state["slot_runtime"].get(slot_id, {})
            event = self._append_event(
                workflow_id,
                "slot_queued",
                node_id=str(runtime.get("node_id") or "") or None,
                item_id=str(runtime.get("item_id") or "") or None,
                slot_id=slot_id,
                payload={
                    "workflow_id": workflow_id,
                    "execution_id": execution_id,
                    "status": "queued",
                    "slot_type": runtime.get("slot_type"),
                    "media_type": runtime.get("media_type"),
                },
            )
        state["events_cursor"] = event.seq
        self._execution_service.save_state(workflow_id, execution_id, state)
        holder: dict[str, WorkflowV2RunResponse] = {}
        thread = threading.Thread(
            target=self._run_execution_thread,
            args=(workflow_id, execution_id, holder, mode, source_action),
            name=f"v2-workflow-run-{execution_id}",
            daemon=True,
        )
        thread.start()
        if wait:
            thread.join(timeout=30.0)
            if "response" not in holder:
                thread.join(timeout=5.0)
        if wait and "response" in holder:
            return holder["response"]
        if wait:
            terminal_response = self._terminal_wait_response(workflow_id, execution_id)
            if terminal_response is not None:
                return terminal_response
        runtime = self._runtime_events.runtime_snapshot(
            workflow,
            active_execution=state,
            provider_tasks=self._provider_task_store.list_tasks(workflow_id),
        )
        return WorkflowV2RunStartResponse(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status=str(state.get("status") or "queued"),  # type: ignore[arg-type]
            runtime=runtime.model_dump(mode="json"),
            events_cursor=runtime.events_cursor,
            message="Workflow execution queued.",
        )

    def _terminal_wait_response(
        self,
        workflow_id: str,
        execution_id: str,
    ) -> WorkflowV2RunResponse | None:
        state = self._execution_service.load_state(workflow_id, execution_id)
        if state is None:
            return None
        status = str(state.get("status") or "")
        if status not in {"completed", "partial_failed", "failed", "cancelled"}:
            return None
        workflow = self.get_workflow(workflow_id)
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        provider_calls = (
            list(metadata.get("provider_calls"))
            if isinstance(metadata.get("provider_calls"), list)
            else []
        )
        provider_call_summaries = _provider_call_summaries(provider_calls)
        self._execution_service.clear_active(workflow_id, execution_id=execution_id)
        return WorkflowV2RunResponse(
            workflow=workflow,
            workflow_id=workflow_id,
            execution_id=execution_id,
            status=status,
            executed_slot_ids=list(state.get("completed_slot_ids") or []),
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
            waiting_slot_ids=list(state.get("waiting_slot_ids") or []),
            failed_slot_ids=list(state.get("failed_slot_ids") or []),
            blocked_slot_ids=list(
                state.get("blocked_slot_ids") or self._blocked_slot_ids(workflow)
            ),
            created_item_ids=list(metadata.get("created_item_ids") or []),
            created_slot_ids=list(metadata.get("created_slot_ids") or []),
        )

    def _run_execution_thread(
        self,
        workflow_id: str,
        execution_id: str,
        holder: dict[str, WorkflowV2RunResponse],
        mode: str,
        source_action: str,
    ) -> None:
        self._execution_context.execution_id = execution_id
        try:
            workflow = self.get_workflow(workflow_id)
            self._recover_pending_provider_manifests(workflow)
            self._storyboard_director.synchronize_structure(workflow)
            self._storyboard_director.prepare_details(
                workflow,
                append_event=self._append_event,
                execution_id=execution_id,
            )
            workflow = self.save_workflow(workflow)
            state = self._execution_service.save_state(
                workflow_id,
                execution_id,
                {
                    **self._initial_execution_state(workflow, execution_id),
                    "mode": mode,
                    "source_action": source_action,
                    "status": "running",
                    "started_at": utc_now().isoformat(),
                },
            )
            self._append_event(
                workflow_id,
                "execution_started",
                payload={
                    "workflow_id": workflow_id,
                    "execution_id": execution_id,
                    "target_slot_ids": state["target_slot_ids"],
                },
            )
            self._append_event(
                workflow_id,
                "global_run_started",
                payload={"workflow_id": workflow_id, "execution_id": execution_id},
            )
            result = self._run_missing_slot_scheduler(
                workflow,
                source_action=source_action,
                mode=mode,
                include_failed_slots=True,
            )
            execution_status = _execution_status_from_slots(
                completed_slot_ids=result.executed_slot_ids,
                waiting_slot_ids=result.waiting_slot_ids,
                failed_slot_ids=result.failed_slot_ids,
            )
            workflow = self.save_workflow(workflow)
            final_state = (
                self._sync_execution_state_from_workflow(
                    workflow,
                    execution_id,
                    extra_completed_slot_ids=result.executed_slot_ids,
                    extra_waiting_slot_ids=result.waiting_slot_ids,
                    extra_failed_slot_ids=result.failed_slot_ids,
                    metadata_updates={
                        "executed_slot_ids": result.executed_slot_ids,
                        "provider_calls": result.provider_calls,
                        "created_item_ids": result.created_item_ids,
                        "created_slot_ids": result.created_slot_ids,
                    },
                    status_override=execution_status,
                    clear_terminal_active=False,
                )
                or state
            )
            self._write_execution_record(
                workflow_id,
                mode=source_action,
                status=execution_status,
                completed_slot_ids=result.executed_slot_ids,
                failed_slot_ids=result.failed_slot_ids,
                waiting_slot_ids=result.waiting_slot_ids,
                slot_transitions=result.slot_transitions,
                source_execution_id=execution_id,
            )
            if execution_status == "waiting":
                self._append_event(
                    workflow_id,
                    "execution_waiting",
                    payload={
                        "execution_id": execution_id,
                        "waiting_slot_ids": result.waiting_slot_ids,
                    },
                )
                self._execution_service.save_state(
                    workflow_id,
                    execution_id,
                    {
                        **final_state,
                        "events_cursor": self._events_cursor(workflow_id),
                        "finished_at": None,
                    },
                )
                self._start_provider_task_poll_loop(workflow_id, execution_id)
            else:
                self._append_event(
                    workflow_id,
                    "execution_partial_failed"
                    if execution_status == "partial_failed"
                    else (
                        "execution_failed"
                        if execution_status == "failed"
                        else "execution_completed"
                    ),
                    payload={
                        "status": execution_status,
                        "execution_id": execution_id,
                        "completed_slot_ids": result.executed_slot_ids,
                        "waiting_slot_ids": result.waiting_slot_ids,
                        "failed_slot_ids": result.failed_slot_ids,
                    },
                )
                self._append_event(
                    workflow_id,
                    "global_run_partial_failed"
                    if execution_status == "partial_failed"
                    else "global_run_completed",
                    payload={
                        "status": execution_status,
                        "execution_id": execution_id,
                        "completed_slot_ids": result.executed_slot_ids,
                        "waiting_slot_ids": result.waiting_slot_ids,
                        "failed_slot_ids": result.failed_slot_ids,
                    },
                )
                self._execution_service.save_state(
                    workflow_id,
                    execution_id,
                    {
                        **final_state,
                        "events_cursor": self._events_cursor(workflow_id),
                        "finished_at": final_state.get("finished_at") or utc_now().isoformat(),
                    },
                )
                self._execution_service.clear_active(
                    workflow_id,
                    execution_id=execution_id,
                )
            provider_call_summaries = _provider_call_summaries(result.provider_calls)
            holder["response"] = WorkflowV2RunResponse(
                workflow=workflow,
                workflow_id=workflow_id,
                execution_id=execution_id,
                status=execution_status,
                executed_slot_ids=result.executed_slot_ids,
                provider_calls=[
                    summary.model_dump(mode="json") for summary in provider_call_summaries
                ],
                provider_call_summaries=provider_call_summaries,
                waiting_slot_ids=result.waiting_slot_ids,
                failed_slot_ids=result.failed_slot_ids,
                blocked_slot_ids=self._blocked_slot_ids(workflow),
                created_item_ids=result.created_item_ids,
                created_slot_ids=result.created_slot_ids,
            )
        except Exception as exc:  # noqa: BLE001 - execution failures are persisted.
            self._converge_execution_failure(workflow_id, execution_id, exc)
        finally:
            self._execution_context.execution_id = None

    def _initial_execution_state(
        self,
        workflow: WorkflowV2,
        execution_id: str,
        *,
        mode: str = "fill_missing_required_slots",
        source_action: str = "global_run",
    ) -> dict[str, Any]:
        now = utc_now().isoformat()
        slot_runtime, target_slot_ids = self._slot_scheduler.initial_slot_runtime(
            workflow,
            execution_id=execution_id,
            updated_at=now,
        )
        return {
            "workflow_id": workflow.workflow_id,
            "execution_id": execution_id,
            "mode": mode,
            "source_action": source_action,
            "status": "queued",
            "target_slot_ids": target_slot_ids,
            "slot_runtime": slot_runtime,
            "created_at": now,
            "updated_at": now,
            "events_cursor": self._runtime_events.events_cursor(workflow.workflow_id),
            "metadata": {
                "shot_reference_selections": _execution_shot_reference_selections(workflow),
            },
        }

    def _converge_execution_failure(
        self,
        workflow_id: str,
        execution_id: str,
        exc: Exception,
    ) -> None:
        state = self._execution_service.load_state(workflow_id, execution_id) or {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "target_slot_ids": [],
            "slot_runtime": {},
            "metadata": {},
            "created_at": utc_now().isoformat(),
        }
        error = {
            "code": exc.code if isinstance(exc, WorkflowV2Error) else "v2_execution_internal_error",
            "message": str(exc)[:500] or "V2 execution failed.",
            **(exc.details if isinstance(exc, WorkflowV2Error) else {}),
        }
        try:
            workflow = self.get_workflow(workflow_id)
        except WorkflowV2Error:
            workflow = None
        target_slot_ids = [str(slot_id) for slot_id in state.get("target_slot_ids", [])]
        slot_runtime = {
            str(slot_id): dict(runtime)
            for slot_id, runtime in dict(state.get("slot_runtime") or {}).items()
            if isinstance(runtime, dict)
        }
        completed_slot_ids: list[str] = []
        failed_slot_ids: list[str] = []
        if workflow is not None:
            for slot_id in target_slot_ids:
                slot = self._find_slot(workflow, slot_id)
                runtime = slot_runtime.get(slot_id, {})
                if slot is not None and self._slot_has_valid_selected_asset(slot):
                    status = "completed"
                    completed_slot_ids.append(slot_id)
                else:
                    status = "failed"
                    failed_slot_ids.append(slot_id)
                    if slot is not None:
                        slot.status = "failed"
                        slot.metadata["error"] = error
                slot_runtime[slot_id] = {
                    **runtime,
                    "slot_id": slot_id,
                    "node_id": slot.node_id if slot is not None else runtime.get("node_id"),
                    "item_id": slot.item_id if slot is not None else runtime.get("item_id"),
                    "slot_type": slot.slot_type if slot is not None else runtime.get("slot_type"),
                    "media_type": slot.media_type
                    if slot is not None
                    else runtime.get("media_type"),
                    "status": status,
                    "runtime_status": status,
                    "updated_at": utc_now().isoformat(),
                    "error": None if status == "completed" else error,
                }
            self._refresh_workflow_state(workflow)
            self.save_workflow(workflow)
        else:
            for slot_id in target_slot_ids:
                runtime = slot_runtime.get(slot_id, {})
                if runtime.get("status") == "completed":
                    completed_slot_ids.append(slot_id)
                    continue
                failed_slot_ids.append(slot_id)
                slot_runtime[slot_id] = {
                    **runtime,
                    "slot_id": slot_id,
                    "status": "failed",
                    "runtime_status": "failed",
                    "updated_at": utc_now().isoformat(),
                    "error": error,
                }
        status = "partial_failed" if completed_slot_ids else "failed"
        converged_state = self._execution_service.save_state(
            workflow_id,
            execution_id,
            {
                **state,
                "status": status,
                "error": error,
                "running_slot_ids": [],
                "waiting_slot_ids": [],
                "completed_slot_ids": completed_slot_ids,
                "failed_slot_ids": failed_slot_ids,
                "slot_runtime": slot_runtime,
                "metadata": {
                    **dict(state.get("metadata") or {}),
                    "terminal_convergence_error": error,
                },
                "finished_at": utc_now().isoformat(),
            },
        )
        converged_event = self._append_event(
            workflow_id,
            "execution_state_converged",
            execution_id=execution_id,
            payload={
                "execution_id": execution_id,
                "status": status,
                "completed_slot_ids": completed_slot_ids,
                "failed_slot_ids": failed_slot_ids,
            },
        )
        failure_event = self._append_event(
            workflow_id,
            "execution_failed",
            execution_id=execution_id,
            payload={"execution_id": execution_id, "error": error},
        )
        self._execution_service.save_state(
            workflow_id,
            execution_id,
            {
                **converged_state,
                "events_cursor": failure_event.seq,
                "metadata": {
                    **dict(converged_state.get("metadata") or {}),
                    "converged_event_seq": converged_event.seq,
                },
            },
        )
        self._execution_service.clear_active(workflow_id, execution_id=execution_id)

    def confirm_shot_summary(
        self,
        workflow_id: str,
        shot_id: str,
        shot_summary_prompt: str,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        shot = self._find_item(workflow, "storyboard", shot_id)
        if shot is None or shot.item_type != "shot":
            raise WorkflowV2Error("shot_not_found")
        try:
            self._storyboard_director.refine_shot_summary(workflow, shot, shot_summary_prompt)
        except V2StoryboardDetailMaterializerError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        self._append_event(
            workflow_id,
            "storyboard_summary_refined",
            node_id=shot.node_id,
            item_id=shot.item_id,
            payload={"shot_summary_prompt": shot_summary_prompt},
        )
        self._refresh_workflow_state(workflow)
        return self.save_workflow(workflow)

    def patch_shot_detail_prompts(
        self,
        workflow_id: str,
        shot_id: str,
        request: WorkflowV2ShotDetailPromptPatchRequest,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        shot = self._find_item(workflow, "storyboard", shot_id)
        if shot is None or shot.item_type != "shot":
            raise WorkflowV2Error("shot_not_found")
        updated_fields = _patch_detail_prompts(shot, request.model_dump(exclude_unset=True))
        if not updated_fields:
            raise WorkflowV2Error("detail_prompt_empty")
        _mark_detail_prompt_dirty_fields(shot, updated_fields, reset=False)
        _sync_shot_video_detail_prompt(shot)
        self._append_event(
            workflow_id,
            "storyboard_detail_prompts_updated",
            node_id=shot.node_id,
            item_id=shot.item_id,
            payload={"updated_fields": updated_fields},
        )
        self._refresh_workflow_state(workflow)
        return self.save_workflow(workflow)

    def update_shot_primary_scene(
        self,
        workflow_id: str,
        shot_id: str,
        scene_item_id: str,
    ) -> WorkflowV2ShotPrimarySceneUpdateResponse:
        workflow = self.get_workflow(workflow_id)
        shot = self._find_item(workflow, "storyboard", shot_id)
        if shot is None or shot.item_type != "shot" or shot.lifecycle_state != "active":
            raise WorkflowV2Error("shot_not_found")
        scene = next(
            (
                candidate
                for node in workflow.nodes
                for candidate in node.items
                if candidate.item_id == scene_item_id
            ),
            None,
        )
        if scene is None:
            raise WorkflowV2Error("shot_primary_scene_not_found")
        if (
            scene.lifecycle_state != "active"
            or scene.item_type != "scene"
            or scene.node_id != "scene-generation"
        ):
            raise WorkflowV2Error("shot_primary_scene_invalid_owner")

        previous_scene_item_id = shot.primary_scene_item_id
        reference_item_ids = _primary_scene_reference_item_ids(workflow, shot, scene.item_id)
        if not reference_item_ids:
            raise WorkflowV2Error("shot_reference_contract_mismatch")
        dependencies = reference_dependency_slot_ids(workflow, reference_item_ids)
        if not dependencies or dependencies[-1] != f"{scene.item_id}:scene_main_image":
            raise WorkflowV2Error("shot_reference_contract_mismatch")

        shot.primary_scene_item_id = scene.item_id
        shot.reference_item_ids = reference_item_ids
        shot.metadata["primary_scene_item_id"] = scene.item_id
        shot.metadata["reference_item_ids"] = list(reference_item_ids)
        _update_shot_script_metadata(workflow, shot, scene.item_id, reference_item_ids)
        affected_slot_ids: list[str] = []
        selected_slot_ids: list[str] = []
        for slot in shot.slots:
            slot.metadata["reference_item_ids"] = list(reference_item_ids)
            if not slot.slot_type.startswith("shot_cell_"):
                continue
            slot.dependency_slot_ids = list(dependencies)
            affected_slot_ids.append(slot.slot_id)
            if slot.selected_asset_id and slot.selected_version_id:
                selected_slot_ids.append(slot.slot_id)
            if not (slot.prompt_source == "user" or slot.manual_prompt_dirty or slot.user_prompt):
                slot.metadata["system_detail_context_outdated"] = True
                shot.metadata["detail_prompts_outdated"] = True
        video_slot = _slot_by_type(shot, "shot_video_segment")
        if video_slot is not None:
            video_slot.metadata["reference_item_ids"] = list(reference_item_ids)
            affected_slot_ids.append(video_slot.slot_id)

        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "shot_primary_scene_updated",
            node_id="storyboard",
            item_id=shot.item_id,
            payload={
                "previous_primary_scene_item_id": previous_scene_item_id,
                "primary_scene_item_id": scene.item_id,
                "affected_slot_ids": affected_slot_ids,
                "selected_asset_versions_changed": False,
            },
        )
        if selected_slot_ids:
            self._append_event(
                workflow_id,
                "weak_link_hint_updated",
                node_id="storyboard",
                item_id=shot.item_id,
                payload={
                    "affected_slot_ids": selected_slot_ids,
                    "reason": "shot_primary_scene_changed",
                },
            )
        self._append_event(
            workflow_id,
            "graph_updated",
            node_id="storyboard",
            item_id=shot.item_id,
            payload={"refresh": ["workflow", "storyboard"]},
        )
        return WorkflowV2ShotPrimarySceneUpdateResponse(
            workflow=workflow,
            shot_id=shot.item_id,
            previous_primary_scene_item_id=previous_scene_item_id,
            primary_scene_item_id=scene.item_id,
            reference_item_ids=reference_item_ids,
            affected_slot_ids=affected_slot_ids,
            selected_asset_versions_changed=False,
            provider_execution_started=False,
            events_cursor=self._events_cursor(workflow_id),
        )

    def refine_shot_detail_prompts(
        self,
        workflow_id: str,
        shot_id: str,
        request: WorkflowV2ShotDetailPromptRefineRequest,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        shot = self._find_item(workflow, "storyboard", shot_id)
        if shot is None or shot.item_type != "shot":
            raise WorkflowV2Error("shot_not_found")
        try:
            generated = self._storyboard_director.materialize_detail_prompts_for_shot(
                workflow,
                shot,
                summary=shot.shot_summary_prompt or shot.item_prompt or shot.item_id,
            )
        except V2StoryboardDetailMaterializerError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        dirty_fields = set(_detail_prompt_dirty_fields(shot))
        for field_name, value in generated.items():
            if dirty_fields and field_name in dirty_fields and not request.overwrite_user_edits:
                continue
            shot.detail_prompts[field_name] = value
        if request.overwrite_user_edits:
            shot.metadata["detail_prompt_dirty_fields"] = []
        shot.metadata["detail_prompts_outdated"] = False
        _sync_shot_video_detail_prompt(shot)
        self._append_event(
            workflow_id,
            "storyboard_detail_prompts_refined",
            node_id=shot.node_id,
            item_id=shot.item_id,
            payload={"overwrite_user_edits": request.overwrite_user_edits},
        )
        self._refresh_workflow_state(workflow)
        return self.save_workflow(workflow)

    def delete_selected_slot_asset(self, workflow_id: str, slot_id: str) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        self._clear_selected_version_for_slot(
            workflow,
            slot,
            source_action="delete_selected_asset",
        )
        slot.selected_asset_id = None
        slot.selected_version_id = None
        if slot.required:
            slot.status = "empty"
        self._refresh_workflow_state(workflow)
        self._append_event(
            workflow_id,
            "slot_selected_asset_cleared",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={"source_action": "delete_selected_asset"},
        )
        self._append_event(
            workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={"status": slot.status},
        )
        return self.save_workflow(workflow)

    def update_item_prompt(
        self,
        workflow_id: str,
        item_id: str,
        item_prompt: str,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        item = self._find_item_any_node(workflow, item_id)
        if item is None:
            raise WorkflowV2Error("item_not_found")
        item.item_prompt = item_prompt
        item.user_prompt = item_prompt
        item.prompt_source = "user"
        item.manual_prompt_dirty = True
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "item_prompt_updated",
            node_id=item.node_id,
            item_id=item.item_id,
            payload={"item_prompt": item_prompt},
        )
        return workflow

    def update_slot_prompt(
        self,
        workflow_id: str,
        slot_id: str,
        *,
        slot_prompt: str | None = None,
        negative_prompt: str | None = None,
        detail_prompt_key: str | None = None,
        visual_style_override: str | None = None,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        if slot_prompt is not None:
            slot.slot_prompt = slot_prompt
            slot.user_prompt = slot_prompt
        if negative_prompt is not None:
            slot.negative_prompt = negative_prompt
        if detail_prompt_key is not None:
            slot.metadata["detail_prompt_key"] = detail_prompt_key
        if visual_style_override is not None:
            slot.metadata["visual_style_contract"] = (
                self._visual_style_service.resolve_slot_override(visual_style_override).model_dump(
                    mode="json"
                )
            )
        slot.prompt_source = "user"
        slot.manual_prompt_dirty = True
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "slot_prompt_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={
                "slot_prompt": slot.slot_prompt,
                "negative_prompt": slot.negative_prompt,
                "detail_prompt_key": detail_prompt_key,
                "visual_style_override": visual_style_override,
            },
        )
        return workflow

    def generate_slot(self, workflow_id: str, slot_id: str) -> WorkflowV2RunResponse:
        return self._run_single_slot(
            workflow_id,
            slot_id,
            mode="slot_generate",
            source_action="slot_generate",
        )

    def regenerate_slot(self, workflow_id: str, slot_id: str) -> WorkflowV2RunResponse:
        return self._run_single_slot(
            workflow_id,
            slot_id,
            mode="slot_regenerate",
            source_action="slot_regenerate",
        )

    def _run_single_slot(
        self,
        workflow_id: str,
        slot_id: str,
        *,
        mode: str,
        source_action: str,
    ) -> WorkflowV2RunResponse:
        workflow = self._preflight_visual_style_scope(
            workflow_id,
            source=source_action,  # type: ignore[arg-type]
        )
        target = self._find_slot(workflow, slot_id)
        if target is None:
            raise WorkflowV2Error("slot_not_found")
        item = self._find_item(workflow, target.node_id, target.item_id)
        if item is None:
            raise WorkflowV2Error("item_not_found")
        if not self._dependencies_satisfied(workflow, target):
            code = (
                self._final_composition_dependency_error_code(workflow)
                if target.slot_type == "final_video"
                else "slot_dependency_not_satisfied"
            )
            target.status = "blocked"
            target.metadata["blocked_reason"] = code
            self._refresh_workflow_state(workflow)
            self.save_workflow(workflow)
            self._append_event(
                workflow_id,
                "runtime_snapshot_updated",
                node_id=target.node_id,
                item_id=target.item_id,
                slot_id=target.slot_id,
                payload={"status": "blocked", "blocked_reason": code},
            )
            raise WorkflowV2Error(code)
        if target.slot_type == "final_video":
            self._ensure_final_composition_item(workflow)
            refreshed_item = self._find_item(workflow, target.node_id, target.item_id)
            if refreshed_item is not None:
                item = refreshed_item
                refreshed_slot = _slot_by_type(refreshed_item, "final_video")
                if refreshed_slot is not None:
                    target = refreshed_slot
        executed_slot_ids: list[str] = []
        provider_calls: list[dict[str, Any]] = []
        slot_transitions: list[dict[str, Any]] = []
        try:
            with self._local_shot_reference_selection(workflow, item, target):
                self._generate_slot(
                    workflow,
                    item,
                    target,
                    executed_slot_ids,
                    provider_calls,
                    select_generated=target.slot_type == "final_video",
                    source_action=source_action,
                    slot_transitions=slot_transitions,
                )
        except WorkflowV2Error:
            self._write_execution_record(
                workflow_id,
                mode=mode,
                status="failed",
                failed_slot_ids=[target.slot_id],
                slot_transitions=slot_transitions,
            )
            raise
        if executed_slot_ids:
            self._clear_outdated_hints_for_slot(workflow, target)
        self._refresh_workflow_state(workflow)
        execution_status, waiting_slot_ids = _execution_status(slot_transitions)
        self._write_execution_record(
            workflow_id,
            mode=mode,
            status=execution_status,
            completed_slot_ids=executed_slot_ids,
            waiting_slot_ids=waiting_slot_ids,
            slot_transitions=slot_transitions,
        )
        workflow = self.save_workflow(workflow)
        provider_call_summaries = _provider_call_summaries(provider_calls)
        return WorkflowV2RunResponse(
            workflow=workflow,
            executed_slot_ids=executed_slot_ids,
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
        )

    @contextmanager
    def _local_shot_reference_selection(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> Iterator[None]:
        if item.item_type != "shot" or not slot.slot_type.startswith("shot_cell_"):
            yield
            return
        selection = _execution_shot_reference_selections(workflow).get(item.item_id)
        if selection is None:
            yield
            return
        metadata_key = "execution_shot_reference_selections"
        existing = workflow.metadata.get(metadata_key)
        selections = dict(existing) if isinstance(existing, dict) else {}
        selections[item.item_id] = selection
        workflow.metadata[metadata_key] = selections
        try:
            yield
        finally:
            if existing is None:
                workflow.metadata.pop(metadata_key, None)
            else:
                workflow.metadata[metadata_key] = existing

    def generate_item(
        self,
        workflow_id: str,
        item_id: str,
        request: WorkflowV2ItemGenerateRequest,
    ) -> WorkflowV2RunResponse:
        workflow = self.get_workflow(workflow_id)
        item = (
            self._find_item(workflow, request.node_id, item_id)
            if request.node_id
            else self._find_item_any_node(workflow, item_id)
        )
        if item is None:
            raise WorkflowV2Error("item_not_found")

        executed_slot_ids: list[str] = []
        provider_calls: list[dict[str, Any]] = []
        slot_transitions: list[dict[str, Any]] = []
        try:
            for slot_type in _slot_plan_for_item(item):
                slot = _slot_by_type(item, slot_type)
                if slot is None:
                    continue
                if request.mode == "missing_only" and self._slot_has_valid_selected_asset(slot):
                    slot.status = "completed"
                    continue
                if not self._dependencies_satisfied(workflow, slot):
                    slot.status = "blocked"
                    self._refresh_workflow_state(workflow)
                    continue
                self._generate_slot(
                    workflow,
                    item,
                    slot,
                    executed_slot_ids,
                    provider_calls,
                    select_generated=request.select_generated,
                    source_action="item_generate",
                    slot_transitions=slot_transitions,
                )
                self._refresh_workflow_state(workflow)
        except WorkflowV2Error:
            self._write_execution_record(
                workflow_id,
                mode="item_generate",
                status="failed",
                completed_slot_ids=executed_slot_ids,
                failed_slot_ids=[
                    transition["slot_id"]
                    for transition in slot_transitions
                    if transition["to_status"] == "failed"
                ],
                slot_transitions=slot_transitions,
            )
            self.save_workflow(workflow)
            raise

        self._refresh_workflow_state(workflow)
        execution_status, waiting_slot_ids = _execution_status(slot_transitions)
        self._write_execution_record(
            workflow_id,
            mode="item_generate",
            status=execution_status,
            completed_slot_ids=executed_slot_ids,
            waiting_slot_ids=waiting_slot_ids,
            slot_transitions=slot_transitions,
        )
        workflow = self.save_workflow(workflow)
        provider_call_summaries = _provider_call_summaries(provider_calls)
        return WorkflowV2RunResponse(
            workflow=workflow,
            executed_slot_ids=executed_slot_ids,
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
        )

    def chat_target(
        self,
        workflow_id: str,
        request: WorkflowV2ChatTargetRequest,
    ) -> WorkflowV2ChatTargetResponse:
        workflow = self.get_workflow(workflow_id)
        if request.target.workflow_id and request.target.workflow_id != workflow_id:
            raise WorkflowV2Error("target_not_found")

        target, item, slot = self._resolve_chat_target(workflow, request)
        self._append_event(
            workflow_id,
            "chat_target_resolved",
            node_id=target.node_id,
            item_id=target.item_id,
            slot_id=target.slot_id,
            asset_id=target.asset_id,
            payload={"target": target.model_dump(mode="json")},
        )
        try:
            route = self._agent_router.route(target)
        except V2AgentRouteError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        route_snapshot = sanitize_context_for_llm_text(route.model_dump(mode="json"))
        self._append_event(
            workflow_id,
            "specialist_route_resolved",
            node_id=target.node_id,
            item_id=target.item_id,
            slot_id=target.slot_id,
            asset_id=target.asset_id,
            payload={"agent_route": route_snapshot, "specialist": route.specialist},
        )

        try:
            materialized_revision = self._generation_pipeline.materialize_chat_revision(
                workflow,
                item,
                slot,
                target,
                route,
                request,
            )
        except V2GenerationPipelineError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        except V2DataBoundaryError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc
        except Exception as exc:
            raise WorkflowV2Error("prompt_materialization_failed", str(exc)) from exc

        updated_scope, affected_slot_ids = self._apply_chat_prompt_update(
            workflow,
            request,
            item=item,
            slot=slot,
            materialized_prompt=materialized_revision,
        )
        sanitized_refs = sanitize_context_for_llm_text(request.asset_references)
        self._append_event(
            workflow_id,
            "prompt_updated",
            node_id=target.node_id,
            item_id=item.item_id if item else target.item_id,
            slot_id=slot.slot_id if slot else target.slot_id,
            asset_id=target.asset_id,
            payload={
                "updated_prompt_scope": updated_scope,
                "affected_slot_ids": affected_slot_ids,
                "asset_references": sanitized_refs,
            },
        )

        executed_slot_ids: list[str] = []
        provider_calls: list[dict[str, Any]] = []
        slot_transitions: list[dict[str, Any]] = []
        if request.action_mode == "revise_and_generate":
            for affected_slot_id in affected_slot_ids:
                target_slot = self._find_slot(workflow, affected_slot_id)
                if target_slot is None:
                    continue
                target_item = self._find_item(workflow, target_slot.node_id, target_slot.item_id)
                if target_item is None:
                    continue
                if not self._dependencies_satisfied(workflow, target_slot):
                    target_slot.status = "blocked"
                    continue
                self._generate_slot(
                    workflow,
                    target_item,
                    target_slot,
                    executed_slot_ids,
                    provider_calls,
                    select_generated=False,
                    source_action="chat_revise_and_generate",
                    slot_transitions=slot_transitions,
                )
        if executed_slot_ids:
            self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        provider_call_summaries = _provider_call_summaries(provider_calls)
        return WorkflowV2ChatTargetResponse(
            workflow_id=workflow_id,
            target=request.target.model_copy(update={"workflow_id": workflow_id}),
            specialist=route.specialist,
            action_mode=request.action_mode,
            applied=True,
            generated=bool(executed_slot_ids),
            updated_prompt_scope=updated_scope,
            affected_slot_ids=affected_slot_ids,
            agent_route_snapshot={
                **route_snapshot,
                "asset_references": sanitized_refs,
                "materializer_mode": materialized_revision.materializer_mode,
                "materializer_warnings": materialized_revision.warnings,
            },
            warnings=materialized_revision.warnings,
            executed_slot_ids=executed_slot_ids,
            asset_ids=[str(call["asset_id"]) for call in provider_calls if call.get("asset_id")],
            version_ids=[
                str(call["version_id"]) for call in provider_calls if call.get("version_id")
            ],
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
            workflow=workflow,
            compatibility_only=True,
            canonical_endpoint=f"/api/v2/workflows/{workflow_id}/chat-actions",
        )

    def chat_action(
        self,
        workflow_id: str,
        request: WorkflowV2ChatActionRequest,
    ) -> WorkflowV2ChatActionResponse:
        workflow = self.get_workflow(workflow_id)
        if request.target.target_type == "node" and request.target.node_id == "script":
            return self._chat_script_action(workflow, request)
        action_mode = _resolve_chat_action_mode(request)
        if action_mode == "clarification_required":
            raise WorkflowV2Error(
                "clarification_required",
                "The requested chat action is ambiguous. Choose revise, generate, select, or discard.",
            )
        action_id = f"act_{uuid4().hex[:12]}"
        conversation_id = str(request.metadata.get("conversation_id") or f"conv_{workflow_id}")
        target, item, slot = self._resolve_chat_action_target(workflow, request)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        try:
            route = self._agent_router.route(target)
        except V2AgentRouteError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc

        created_event = self._append_event(
            workflow_id,
            "chat_action_created",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=target.asset_id,
            payload={
                "action_id": action_id,
                "conversation_id": conversation_id,
                "action_mode": action_mode,
                "target": request.target.model_dump(mode="json"),
            },
        )
        self._append_event(
            workflow_id,
            "chat_action_resolved",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=target.asset_id,
            payload={"action_id": action_id, "specialist": route.specialist},
        )
        events = [created_event.event_type, "chat_action_resolved"]
        working_version: WorkflowV2WorkingVersionView | None = None

        if action_mode == "revise_prompt":
            slot.slot_prompt = request.message
            slot.user_prompt = request.message
            slot.prompt_source = "user"
            slot.manual_prompt_dirty = True
            workflow = self.save_workflow(workflow)
            self._append_event(
                workflow_id,
                "slot_prompt_updated",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                payload={"slot_prompt": request.message, "source_action": "chat_action"},
            )
            events.append("slot_prompt_updated")
            message = "Updated the target slot prompt."
        elif action_mode == "revise_and_generate":
            slot.slot_prompt = request.message
            slot.user_prompt = request.message
            slot.prompt_source = "user"
            slot.manual_prompt_dirty = True
            if not self._dependencies_satisfied(workflow, slot):
                slot.status = "blocked"
                self._refresh_workflow_state(workflow)
                self.save_workflow(workflow)
                raise WorkflowV2Error("slot_dependency_not_satisfied")
            executed_slot_ids: list[str] = []
            provider_calls: list[dict[str, Any]] = []
            slot_transitions: list[dict[str, Any]] = []
            target_item = (
                item
                if item is not None
                else self._find_item(
                    workflow,
                    slot.node_id,
                    slot.item_id,
                )
            )
            if target_item is None:
                raise WorkflowV2Error("item_not_found")
            self._generate_slot(
                workflow,
                target_item,
                slot,
                executed_slot_ids,
                provider_calls,
                select_generated=False,
                source_action="chat_revise_and_generate",
                slot_transitions=slot_transitions,
            )
            self._refresh_workflow_state(workflow)
            workflow = self.save_workflow(workflow)
            if slot.current_working_asset_id and slot.current_working_version_id:
                working_version = WorkflowV2WorkingVersionView(
                    asset_id=slot.current_working_asset_id,
                    version_id=slot.current_working_version_id,
                )
            events.extend(["slot_prompt_updated", "slot_working_version_updated"])
            message = "Generated a new working version for the target slot."
        elif action_mode == "select_version":
            asset_id = request.asset_id or request.target.asset_id or target.asset_id
            version_id = request.version_id or request.target.version_id
            if not asset_id or not version_id:
                raise WorkflowV2Error("version_not_found")
            from app.schemas.workflow_v2 import SelectSlotVersionRequestV2
            from app.services.v2_workflow_assets import V2WorkflowAssetError, V2WorkflowAssetService

            try:
                V2WorkflowAssetService(self._data_dir).select_slot_version(
                    workflow_id,
                    slot.slot_id,
                    SelectSlotVersionRequestV2(asset_id=asset_id, version_id=version_id),
                )
            except V2WorkflowAssetError as exc:
                raise WorkflowV2Error(exc.code, str(exc)) from exc
            workflow = self.get_workflow(workflow_id)
            events.append("slot_selected_version_updated")
            message = "Selected the requested version for the target slot."
        else:
            workflow = self.discard_working_version(workflow_id, slot.slot_id)
            events.append("slot_working_version_discarded")
            message = "Discarded the current working version for the target slot."

        resolved_target = WorkflowV2ResolvedChatActionTarget(
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
        )
        response = WorkflowV2ChatActionResponse(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            action_id=action_id,
            target=request.target,
            resolved_target=resolved_target,
            specialist=route.specialist,
            action_mode=action_mode,
            applied=True,
            working_version=working_version,
            events=list(dict.fromkeys(events)),
            message=message,
            workflow=workflow,
        )
        self._write_chat_action_audit(
            workflow_id,
            action_id,
            {
                "workflow_id": workflow_id,
                "conversation_id": conversation_id,
                "action_id": action_id,
                "original_user_message": request.message,
                "target": request.target.model_dump(mode="json"),
                "resolved_target": resolved_target.model_dump(mode="json"),
                "specialist": route.specialist,
                "action_mode": action_mode,
                "created_at": utc_now().isoformat(),
                "status": "completed",
                "generated": working_version.model_dump(mode="json") if working_version else None,
                "error_code": None,
            },
        )
        return response

    def _chat_script_action(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2ChatActionRequest,
    ) -> WorkflowV2ChatActionResponse:
        if request.action_mode not in {"auto", "revise_prompt"}:
            raise WorkflowV2Error(
                "invalid_script_chat_action",
                "Screenplay chat actions support revise_prompt only.",
            )
        try:
            selected = self._script_versions.read_selected(workflow.workflow_id)
        except V2ScriptVersionError as exc:
            raise WorkflowV2Error(
                exc.code,
                str(exc),
                details={"stage": exc.stage, "violations": exc.violations},
            ) from exc
        try:
            document = self._script_writer.normalize_edit_document(
                selected.script,
                request.message,
                workflow_id=workflow.workflow_id,
            )
        except V2ScriptWriterError as exc:
            raise WorkflowV2Error("script_edit_normalization_failed", str(exc)) from exc
        try:
            confirmed = self._script_versions.confirm(
                workflow.workflow_id,
                V2ScriptConfirmRequest(
                    base_script_version_id=selected.selected_script_version_id,
                    document=document,
                    source_action="agent_chat_edit",
                ),
            )
        except V2ScriptVersionError as exc:
            raise WorkflowV2Error(
                exc.code,
                str(exc),
                details={"stage": exc.stage, "violations": exc.violations},
            ) from exc
        action_id = f"act_{uuid4().hex[:12]}"
        conversation_id = str(
            request.metadata.get("conversation_id") or f"conv_{workflow.workflow_id}"
        )
        self._append_event(
            workflow.workflow_id,
            "chat_action_created",
            node_id="script",
            payload={
                "action_id": action_id,
                "conversation_id": conversation_id,
                "action_mode": "revise_prompt",
                "target": request.target.model_dump(mode="json"),
            },
        )
        self._append_event(
            workflow.workflow_id,
            "chat_action_resolved",
            node_id="script",
            payload={
                "action_id": action_id,
                "script_version_id": confirmed.selected_script_version_id,
            },
        )
        return WorkflowV2ChatActionResponse(
            workflow_id=workflow.workflow_id,
            conversation_id=conversation_id,
            action_id=action_id,
            target=request.target,
            action_mode="revise_prompt",
            applied=True,
            events=[
                "script_version_created",
                "script_selected_version_updated",
                "linked_context_updated",
                "chat_action_created",
                "chat_action_resolved",
            ],
            message="Screenplay edit confirmed.",
            workflow=self._workflow_store.load_workflow(workflow.workflow_id),
        )

    def _resolve_chat_action_target(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2ChatActionRequest,
    ) -> tuple[V2GenerationTarget, WorkflowItemV2 | None, WorkflowSlotV2 | None]:
        target = request.target
        if target.locator:
            target = _target_from_locator(target.locator, target)
        if target.target_type == "slot":
            chat_request = WorkflowV2ChatTargetRequest(
                target={
                    "target_type": "slot",
                    "workflow_id": workflow.workflow_id,
                    "slot_id": target.slot_id,
                },
                instruction=request.message,
            )
            return self._resolve_chat_target(workflow, chat_request)
        if target.target_type == "asset":
            chat_request = WorkflowV2ChatTargetRequest(
                target={
                    "target_type": "asset",
                    "workflow_id": workflow.workflow_id,
                    "asset_id": target.asset_id,
                },
                instruction=request.message,
            )
            return self._resolve_chat_target(workflow, chat_request)
        if target.target_type == "free_node":
            if not target.node_id:
                raise WorkflowV2Error("free_node_not_found")
            node = _node_by_id(workflow, target.node_id)
            if node is None or node.node_type != "free-generation":
                raise WorkflowV2Error("free_node_not_found")
            items = _active_items(node)
            if not items:
                raise WorkflowV2Error("item_not_found")
            item = items[0]
            slot = _slot_by_type(item, "free_output")
            if slot is None:
                raise WorkflowV2Error("slot_not_found")
            return (
                V2GenerationTarget(
                    workflow_id=workflow.workflow_id,
                    target_type="slot",
                    node_id=node.node_id,
                    node_type=node.node_type,
                    item_id=item.item_id,
                    item_type=item.item_type,
                    slot_id=slot.slot_id,
                    slot_type=slot.slot_type,
                    media_type=slot.media_type,
                    is_free_generation=True,
                ),
                item,
                slot,
            )
        raise WorkflowV2Error("target_type_not_supported")

    def _write_chat_action_audit(
        self,
        workflow_id: str,
        action_id: str,
        payload: dict[str, Any],
    ) -> None:
        root = workflow_v2_runtime_dir(self._data_dir, workflow_id) / "chat_actions"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{action_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list_slot_versions(self, workflow_id: str, slot_id: str) -> V2SlotVersionsResponse:
        workflow = self.get_workflow(workflow_id)
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        relations = self._asset_store.list_relations(
            target_workflow_id=workflow_id,
            target_slot_id=slot_id,
        )
        version_relations = [
            relation
            for relation in relations
            if relation.relation_type
            in {
                "selected_for_slot",
                "working_version_for_slot",
                "history_version_for_slot",
            }
        ]
        versions: list[WorkflowAssetVersionV2] = []
        seen_pairs: set[tuple[str, str]] = set()
        for relation in version_relations:
            version_id = str(
                relation.metadata.get("version_id")
                or self._version_id_for_asset(relation.source_asset_id)
                or ""
            )
            if not version_id:
                continue
            pair = (relation.source_asset_id, version_id)
            if pair in seen_pairs:
                continue
            version = self._asset_store.load_asset_version(relation.source_asset_id, version_id)
            if version is None:
                continue
            seen_pairs.add(pair)
            versions.append(version)
        return V2SlotVersionsResponse(
            workflow_id=workflow_id,
            slot_id=slot_id,
            selected_asset_id=slot.selected_asset_id,
            working_asset_id=slot.current_working_asset_id,
            current_working_version_id=slot.current_working_version_id,
            versions=versions,
            relations=version_relations,
        )

    def select_slot_version(
        self,
        workflow_id: str,
        slot_id: str,
        version_id: str,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        version = self._asset_store.find_asset_version(slot_id=slot_id, version_id=version_id)
        if version is None:
            raise WorkflowV2Error("asset_version_not_found")
        old_selected_asset_id = slot.selected_asset_id
        old_selected_version_id = slot.selected_version_id or (
            self._version_id_for_asset(old_selected_asset_id) if old_selected_asset_id else None
        )
        if old_selected_asset_id and old_selected_version_id:
            slot.history_version_ids = list(
                dict.fromkeys([*slot.history_version_ids, old_selected_version_id])
            )
            self._append_history_version_for_slot(
                workflow,
                slot,
                asset_id=old_selected_asset_id,
                version_id=old_selected_version_id,
                source_action="select_version",
            )
        slot.selected_asset_id = version.asset_id
        slot.selected_version_id = version.version_id
        slot.current_working_asset_id = version.asset_id
        slot.current_working_version_id = version.version_id
        slot.status = "completed"
        self._set_selected_version_for_slot(
            workflow,
            slot,
            asset_id=version.asset_id,
            version_id=version.version_id,
            source_action="select_version",
        )
        self._set_working_version_for_slot(
            workflow,
            slot,
            asset_id=version.asset_id,
            version_id=version.version_id,
            source_action="select_version",
        )
        self._clear_outdated_hints_for_slot(workflow, slot)
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        return workflow

    def discard_working_version(self, workflow_id: str, slot_id: str) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        slot = self._find_slot(workflow, slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        removed = self._clear_working_version_for_slot(
            workflow,
            slot,
            source_action="discard_working_version",
        )
        slot.current_working_asset_id = None
        slot.current_working_version_id = None
        self._append_event(
            workflow_id,
            "slot_working_version_discarded",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={
                "removed_relation_ids": [relation.relation_id for relation in removed],
                "source_action": "discard_working_version",
            },
        )
        self._refresh_workflow_state(workflow)
        return self.save_workflow(workflow)

    def resolve_asset_owner(self, workflow_id: str, asset_id: str) -> V2AssetOwnerResponse:
        self.get_workflow(workflow_id)
        relation = self._owner_relation_for_asset(workflow_id, asset_id)
        if relation is None:
            raise WorkflowV2Error("asset_owner_not_found")
        relations = self._asset_store.list_relations(
            target_workflow_id=workflow_id,
            source_asset_id=asset_id,
        )
        self._append_event(
            workflow_id,
            "asset_owner_resolved",
            node_id=relation.target_node_id,
            item_id=relation.target_item_id,
            slot_id=relation.target_slot_id,
            asset_id=asset_id,
            payload={
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
            },
        )
        return V2AssetOwnerResponse(
            workflow_id=workflow_id,
            asset_id=asset_id,
            owner=V2AssetOwner(
                node_id=relation.target_node_id,
                item_id=relation.target_item_id,
                slot_id=relation.target_slot_id,
                relation_type=relation.relation_type,
                relation_id=relation.relation_id,
            ),
            relations=relations,
        )

    def attach_reference(
        self,
        workflow_id: str,
        request: WorkflowV2ReferenceAttachRequest,
    ) -> WorkflowV2ReferenceMutationResponse:
        workflow = self.get_workflow(workflow_id)
        if not self._asset_store.asset_exists(request.source_asset_id):
            raise WorkflowV2Error("asset_not_found")
        target_node_id: str | None = None
        target_item_id: str | None = None
        target_slot_id: str | None = None
        if request.target_type == "item":
            item = self._find_item_any_node(workflow, request.target_id)
            if item is None:
                raise WorkflowV2Error("item_not_found")
            target_node_id = item.node_id
            target_item_id = item.item_id
            relation_type = "reference_for_item"
        else:
            slot = self._find_slot(workflow, request.target_id)
            if slot is None:
                raise WorkflowV2Error("slot_not_found")
            target_node_id = slot.node_id
            target_item_id = slot.item_id
            target_slot_id = slot.slot_id
            relation_type = "reference_for_slot"
        relation = self._asset_store.create_relation(
            relation_type=relation_type,
            source_asset_id=request.source_asset_id,
            target_workflow_id=workflow_id,
            target_node_id=target_node_id,
            target_item_id=target_item_id,
            target_slot_id=target_slot_id,
            metadata={"reference_kind": request.reference_kind, **request.metadata},
        )
        if request.target_type == "item":
            item = self._find_item_any_node(workflow, request.target_id)
            if item:
                _append_unique(item.metadata, "reference_relation_ids", relation.relation_id)
                _append_unique(
                    item.metadata, "explicit_reference_asset_ids", request.source_asset_id
                )
        elif target_slot_id:
            slot = self._find_slot(workflow, target_slot_id)
            if slot:
                _append_unique(slot.metadata, "reference_relation_ids", relation.relation_id)
                slot.explicit_reference_ids = list(
                    dict.fromkeys([*slot.explicit_reference_ids, request.source_asset_id])
                )
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "reference_attached",
            node_id=target_node_id,
            item_id=target_item_id,
            slot_id=target_slot_id,
            asset_id=request.source_asset_id,
            payload={"relation_id": relation.relation_id, "relation_type": relation.relation_type},
        )
        return WorkflowV2ReferenceMutationResponse(workflow=workflow, relation=relation)

    def remove_reference(
        self,
        workflow_id: str,
        relation_id: str,
    ) -> WorkflowV2ReferenceMutationResponse:
        workflow = self.get_workflow(workflow_id)
        relation = self._asset_store.delete_relation(relation_id)
        if relation is None:
            raise WorkflowV2Error("relation_not_found")
        self._remove_relation_from_workflow(workflow, relation)
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "reference_removed",
            node_id=relation.target_node_id,
            item_id=relation.target_item_id,
            slot_id=relation.target_slot_id,
            asset_id=relation.source_asset_id,
            version_id=str(relation.metadata.get("version_id") or "") or None,
            payload={
                "relation_id": relation_id,
                "reference_role": relation.metadata.get("reference_role"),
            },
        )
        self._append_event(
            workflow_id,
            "runtime_snapshot_updated",
            node_id=relation.target_node_id,
            item_id=relation.target_item_id,
            slot_id=relation.target_slot_id,
            asset_id=relation.source_asset_id,
            version_id=str(relation.metadata.get("version_id") or "") or None,
        )
        return WorkflowV2ReferenceMutationResponse(
            workflow=workflow,
            removed_relation_id=relation_id,
        )

    def runtime_snapshot(self, workflow_id: str) -> WorkflowV2RuntimeSnapshot:
        workflow = self.get_workflow(workflow_id)
        self._refresh_workflow_state(workflow)
        active_pointer = self._execution_service.load_active(
            workflow_id,
            include_terminal=True,
        )
        active_execution = (
            active_pointer
            if active_pointer is not None
            and str(active_pointer.get("status") or "") not in TERMINAL_EXECUTION_STATUSES
            else None
        )
        snapshot = self._runtime_events.runtime_snapshot(
            workflow,
            active_execution=active_execution,
            provider_tasks=self._provider_task_store.list_tasks(workflow_id),
        )
        terminal_execution = (
            self._execution_service.load_latest_terminal(workflow_id)
            if active_execution is None
            else None
        )
        if terminal_execution is None:
            return snapshot
        return snapshot.model_copy(update={"execution_status": str(terminal_execution["status"])})

    def list_events(self, workflow_id: str, after_seq: int = 0) -> WorkflowV2EventListResponse:
        self.get_workflow(workflow_id)
        return self._runtime_events.list_events(workflow_id, after_seq=after_seq)

    def create_free_node(
        self,
        workflow_id: str,
        request: WorkflowV2FreeNodeCreateRequest,
    ) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        ordinal = len([node for node in workflow.nodes if node.node_type == "free-generation"]) + 1
        node_id = f"free-generation-{ordinal}"
        item_id = f"free-item-{ordinal}"
        slot = build_slot(
            node_id=node_id,
            item_id=item_id,
            slot_type="free_output",
            media_type="image",
            status="empty",
            prompt=request.slot_prompt or "Free generation output.",
        )
        slot.negative_prompt = request.negative_prompt
        slot.provider = request.provider
        slot.provider_params = dict(request.provider_params)
        workflow.nodes.append(
            WorkflowNodeV2(
                node_id=node_id,
                node_type="free-generation",
                title=f"Free Generation {ordinal}",
                status="ready",
                position={"x": 320, "y": 520 + (ordinal - 1) * 140},
                items=[
                    WorkflowItemV2(
                        item_id=item_id,
                        node_id=node_id,
                        item_type="free",
                        display_name=f"Free Item {ordinal}",
                        item_prompt=request.slot_prompt,
                        status="empty",
                        slots=[slot],
                    )
                ],
                metadata={"resolved_media_type": None, "resolved_node_role": None},
            )
        )
        workflow = self.save_workflow(workflow)
        self._append_event(workflow_id, "free_node_created", node_id=node_id, item_id=item_id)
        return workflow

    def generate_free_node(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowV2FreeNodeGenerateRequest,
    ) -> WorkflowV2RunResponse:
        workflow = self.get_workflow(workflow_id)
        node = _node_by_id(workflow, node_id)
        if node is None or node.node_type != "free-generation":
            raise WorkflowV2Error("free_node_not_found")
        items = _active_items(node)
        if not items:
            raise WorkflowV2Error("item_not_found")
        item = items[0]
        slot = _slot_by_type(item, "free_output")
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        slot.media_type = request.output_media_type
        executed_slot_ids: list[str] = []
        provider_calls: list[dict[str, Any]] = []
        slot_transitions: list[dict[str, Any]] = []
        self._generate_slot(
            workflow,
            item,
            slot,
            executed_slot_ids,
            provider_calls,
            select_generated=False,
            source_action="slot_generate",
            slot_transitions=slot_transitions,
        )
        node.metadata["resolved_media_type"] = request.output_media_type
        node.metadata["resolved_node_role"] = _free_role_for_media_type(request.output_media_type)
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        provider_call_summaries = _provider_call_summaries(provider_calls)
        return WorkflowV2RunResponse(
            workflow=workflow,
            executed_slot_ids=executed_slot_ids,
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
        )

    def absorb_free_node(
        self,
        workflow_id: str,
        node_id: str,
        request: WorkflowV2FreeNodeAbsorbRequest,
    ) -> WorkflowV2FreeNodeAbsorbResponse:
        workflow = self.get_workflow(workflow_id)
        free_node = _node_by_id(workflow, node_id)
        if free_node is None or free_node.node_type != "free-generation":
            raise WorkflowV2Error("free_node_not_found")
        resolved_role = free_node.metadata.get("resolved_node_role")
        if not isinstance(resolved_role, str):
            raise WorkflowV2Error("free_node_role_unresolved")
        if not _free_absorb_allowed(resolved_role, request.target_node_id):
            raise WorkflowV2Error("invalid_free_node_absorb_target")
        if not self._asset_store.asset_exists(request.asset_id):
            raise WorkflowV2Error("asset_not_found")
        relations: list[WorkflowAssetRelationV2] = []
        if resolved_role == "free-video":
            relations.append(
                self._asset_store.create_relation(
                    relation_type="absorbed_into",
                    source_asset_id=request.asset_id,
                    target_workflow_id=workflow_id,
                    target_node_id=request.target_node_id,
                    target_item_id=request.target_item_id,
                    target_slot_id=request.target_slot_id,
                    metadata={"absorb_role": request.absorb_role, **request.metadata},
                )
            )
            relations.append(
                self._asset_store.create_relation(
                    relation_type="available_for_composition",
                    source_asset_id=request.asset_id,
                    target_workflow_id=workflow_id,
                    target_node_id=request.target_node_id,
                    target_item_id=request.target_item_id,
                    target_slot_id=request.target_slot_id,
                    metadata={"absorb_role": request.absorb_role, **request.metadata},
                )
            )
            self._record_available_composition_asset(workflow, request)
        else:
            relations.append(
                self._asset_store.create_relation(
                    relation_type="absorbed_into",
                    source_asset_id=request.asset_id,
                    target_workflow_id=workflow_id,
                    target_node_id=request.target_node_id,
                    target_item_id=request.target_item_id,
                    target_slot_id=request.target_slot_id,
                    metadata={"absorb_role": request.absorb_role, **request.metadata},
                )
            )
            relation_type = "reference_for_slot" if request.target_slot_id else "reference_for_item"
            relations.append(
                self._asset_store.create_relation(
                    relation_type=relation_type,
                    source_asset_id=request.asset_id,
                    target_workflow_id=workflow_id,
                    target_node_id=request.target_node_id,
                    target_item_id=request.target_item_id,
                    target_slot_id=request.target_slot_id,
                    metadata={"reference_kind": "absorbed", **request.metadata},
                )
            )
            self._record_absorbed_reference(workflow, request, relations)
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "reference_attached",
            node_id=request.target_node_id,
            item_id=request.target_item_id,
            slot_id=request.target_slot_id,
            asset_id=request.asset_id,
            payload={
                "source_free_node_id": node_id,
                "relation_ids": [relation.relation_id for relation in relations],
            },
        )
        return WorkflowV2FreeNodeAbsorbResponse(workflow=workflow, relations=relations)

    def delete_free_node(self, workflow_id: str, node_id: str) -> WorkflowV2:
        workflow = self.get_workflow(workflow_id)
        before = len(workflow.nodes)
        workflow.nodes = [node for node in workflow.nodes if node.node_id != node_id]
        if len(workflow.nodes) == before:
            raise WorkflowV2Error("free_node_not_found")
        workflow = self.save_workflow(workflow)
        self._append_event(workflow_id, "free_node_deleted", node_id=node_id)
        return workflow

    def create_timeline_clip(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineClipCreateRequest,
    ) -> WorkflowV2TimelineClipMutationResponse:
        workflow = self.get_workflow(workflow_id)
        if not self._asset_store.asset_exists(request.source_asset_id):
            raise WorkflowV2Error("asset_not_found")
        item = self._final_composition_item(workflow)
        if item is None:
            raise WorkflowV2Error("final_composition_not_ready")
        relation = self._asset_store.create_relation(
            relation_type="selected_for_timeline",
            source_asset_id=request.source_asset_id,
            target_workflow_id=workflow_id,
            target_node_id="final-composition",
            target_item_id=item.item_id,
            metadata={"clip_type": request.clip_type},
        )
        clip = {
            "clip_id": f"clip_{uuid4().hex[:12]}",
            "source_asset_id": request.source_asset_id,
            "source_slot_id": None,
            "clip_type": request.clip_type,
            "start_time": request.start_time,
            "duration": request.duration,
            "track_index": request.track_index,
            "trim_in": request.trim_in,
            "trim_out": request.trim_out,
            "volume": request.volume,
            "relation_id": relation.relation_id,
            "metadata": dict(request.metadata),
        }
        item.timeline_clips.append(clip)
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "reference_attached",
            node_id="final-composition",
            item_id=item.item_id,
            asset_id=request.source_asset_id,
            payload={"relation_id": relation.relation_id, "clip_id": clip["clip_id"]},
        )
        return WorkflowV2TimelineClipMutationResponse(workflow=workflow, clip=clip)

    def delete_timeline_clip(
        self,
        workflow_id: str,
        clip_id: str,
    ) -> WorkflowV2TimelineClipMutationResponse:
        workflow = self.get_workflow(workflow_id)
        item = self._final_composition_item(workflow)
        if item is None:
            raise WorkflowV2Error("final_composition_not_ready")
        clip = next((clip for clip in item.timeline_clips if clip.get("clip_id") == clip_id), None)
        if clip is None:
            raise WorkflowV2Error("timeline_clip_not_found")
        relation_id = clip.get("relation_id")
        if isinstance(relation_id, str):
            self._asset_store.delete_relation(relation_id)
        item.timeline_clips = [
            clip for clip in item.timeline_clips if clip.get("clip_id") != clip_id
        ]
        workflow = self.save_workflow(workflow)
        self._append_event(
            workflow_id,
            "reference_removed",
            node_id="final-composition",
            item_id=item.item_id,
            asset_id=str(clip.get("source_asset_id") or ""),
            payload={"clip_id": clip_id, "relation_id": relation_id},
        )
        return WorkflowV2TimelineClipMutationResponse(
            workflow=workflow,
            removed_clip_id=clip_id,
        )

    def get_provider_task(self, workflow_id: str, task_id: str) -> V2ProviderTask:
        self.get_workflow(workflow_id)
        task = self._provider_task_store.load_task(workflow_id, task_id)
        if task is None:
            raise WorkflowV2Error("v2_provider_task_not_found")
        return task

    def list_provider_tasks(
        self,
        workflow_id: str,
        *,
        slot_id: str | None = None,
    ) -> V2ProviderTaskListResponse:
        self.get_workflow(workflow_id)
        return V2ProviderTaskListResponse(
            tasks=self._provider_task_store.list_tasks(workflow_id, slot_id=slot_id)
        )

    def poll_provider_task(
        self,
        workflow_id: str,
        task_id: str,
        *,
        resume_scheduler: bool = True,
    ) -> V2ProviderTaskPollResponse:
        if not resume_scheduler:
            with v2_workflow_lock(self._data_dir, workflow_id):
                return self._poll_provider_task_locked(
                    workflow_id,
                    task_id,
                    resume_scheduler=False,
                )
        return self._poll_provider_task_locked(
            workflow_id,
            task_id,
            resume_scheduler=True,
        )

    def _poll_provider_task_locked(
        self,
        workflow_id: str,
        task_id: str,
        *,
        resume_scheduler: bool,
    ) -> V2ProviderTaskPollResponse:
        workflow = self.get_workflow(workflow_id)
        task = self._provider_task_store.load_task(workflow_id, task_id)
        if task is None:
            raise WorkflowV2Error("v2_provider_task_not_found")
        slot = self._find_slot(workflow, task.slot_id)
        if slot is None:
            raise WorkflowV2Error("slot_not_found")
        item = self._find_item(workflow, slot.node_id, slot.item_id)
        if item is None:
            raise WorkflowV2Error("item_not_found")
        if task.status == "completed":
            self._refresh_workflow_state(workflow)
            workflow = self.save_workflow(workflow)
            return V2ProviderTaskPollResponse(
                task=task,
                workflow=workflow,
                provider_result=self._provider_result_from_completed_task(task),
                blocked_slot_ids=self._blocked_slot_ids(workflow),
            )
        if task.status in {"failed", "cancelled"}:
            raise WorkflowV2Error(
                "provider_task_already_terminal",
                f"Provider task {task.task_id} is already {task.status}.",
            )
        if _provider_task_timed_out(task) and not _expired_remote_reconciliation_eligible(task):
            result = V2ProviderResult(
                status="failed",
                media_type=_provider_task_media_type(task),
                remote_task_id=task.remote_task_id,
                provider=task.provider,
                provider_model=task.provider_model,
                provider_payload_snapshot=task.provider_payload_snapshot,
                error_code="v2_provider_task_timeout",
                error_message="Provider task exceeded backend timeout.",
                metadata={
                    "provider_task_id": task.task_id,
                    "timeout_at": task.metadata.get("timeout_at"),
                },
            )
        else:
            if _provider_task_timed_out(task):
                task = self._provider_task_store.mark_expired_remote_reconciliation_started(task)
            self._append_provider_task_event(workflow, task, "provider_task_polled")
            result = self._generation_pipeline.poll_provider_task(task)
        if _provider_poll_retryable(task, result, self._settings):
            is_download_retry = _is_retryable_provider_result_download(result)
            if not is_download_retry:
                self._record_provider_cooldown(workflow, task, result)
            retry_metadata = {
                **result.metadata,
                "waiting_reason": (
                    "provider_result_download_retry"
                    if is_download_retry
                    else "retryable_provider_poll_error"
                ),
                "retryable_error_code": result.error_code,
                "retryable_error_message": result.error_message,
                "next_poll_delay_seconds": _provider_retry_delay_seconds(
                    task,
                    result,
                    self._settings,
                ),
            }
            if is_download_retry:
                retry_metadata.update(
                    {
                        "download_attempt": task.download_attempt_count + 1,
                        "max_download_attempts": _provider_download_max_attempts(self._settings),
                        "remote_status": result.metadata.get("remote_status") or "succeeded",
                    }
                )
            result = result.model_copy(
                update={
                    "status": "waiting",
                    "metadata": retry_metadata,
                }
            )
        elif _download_result_retry_budget_exhausted(task, result, self._settings):
            result = _provider_result_download_exhausted(task, result, self._settings)
        if _historical_result_recovery_should_be_exhausted(task, result):
            task = self._provider_task_store.mark_historical_result_recovery_exhausted(task)
        if result.status == "completed":
            manifest = self._persist_completed_provider_task_manifest(
                workflow,
                item,
                slot,
                task,
                result,
            )
            workflow, updated_task, scheduler_result, should_continue = (
                self._commit_completed_provider_task_manifest(manifest, task, result)
            )
            workflow = self._execution_recovery.recover_interrupted_execution(
                workflow_id,
                trigger="provider_completion",
            ).workflow
            if should_continue and resume_scheduler:
                scheduler_result = self._resume_missing_slot_scheduler_after_provider_task(
                    self.get_workflow(workflow_id),
                    updated_task,
                )
                workflow = self.get_workflow(workflow_id)
            safe_result = result.model_copy(update={"asset_bytes": None})
            provider_call_summaries = _provider_call_summaries(scheduler_result.provider_calls)
            return V2ProviderTaskPollResponse(
                task=self._provider_task_store.load_task(workflow_id, task_id) or updated_task,
                workflow=workflow,
                provider_result=safe_result,
                executed_slot_ids=scheduler_result.executed_slot_ids,
                provider_calls=[
                    summary.model_dump(mode="json") for summary in provider_call_summaries
                ],
                provider_call_summaries=provider_call_summaries,
                waiting_slot_ids=scheduler_result.waiting_slot_ids,
                failed_slot_ids=scheduler_result.failed_slot_ids,
                blocked_slot_ids=self._blocked_slot_ids(workflow),
                created_item_ids=scheduler_result.created_item_ids,
                created_slot_ids=scheduler_result.created_slot_ids,
            )
        slot_transitions: list[dict[str, Any]] = []
        asset = self._generation_pipeline.apply_provider_task_result(
            workflow,
            item,
            slot,
            task,
            result,
            slot_transitions=slot_transitions,
            transition_slot=self._transition_slot,
            set_working_version_for_slot=self._set_working_version_for_slot,
            set_selected_version_for_slot=self._set_selected_version_for_slot,
            append_event=self._append_event,
        )
        updated_task = self._provider_task_store.mark_poll_result(task, result)
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        scheduler_result = _SchedulerRunResult()
        if result.status == "completed":
            self._append_provider_task_event(
                workflow,
                updated_task,
                "provider_task_completed",
                result=result,
                asset_id=asset.asset_id if asset else updated_task.asset_id,
                version_id=asset.version_id if asset else updated_task.version_id,
            )
            scheduler_result = self._resume_missing_slot_scheduler_after_provider_task(
                workflow,
                updated_task,
            )
            workflow = self.save_workflow(workflow)
        elif result.status == "waiting":
            self._append_provider_task_event(
                workflow,
                updated_task,
                "provider_task_waiting",
                result=result,
            )
            scheduler_result.waiting_slot_ids = [slot.slot_id]
        else:
            self._append_provider_task_event(
                workflow,
                updated_task,
                "provider_task_failed",
                result=result,
            )
            scheduler_result.failed_slot_ids = [slot.slot_id]
        if updated_task.execution_id:
            self._sync_execution_state_from_workflow(
                workflow,
                updated_task.execution_id,
                extra_completed_slot_ids=scheduler_result.executed_slot_ids,
                extra_waiting_slot_ids=scheduler_result.waiting_slot_ids,
                extra_failed_slot_ids=scheduler_result.failed_slot_ids,
            )
        safe_result = result.model_copy(update={"asset_bytes": None})
        provider_call_summaries = _provider_call_summaries(scheduler_result.provider_calls)
        return V2ProviderTaskPollResponse(
            task=self._provider_task_store.load_task(workflow_id, task_id) or updated_task,
            workflow=workflow,
            provider_result=safe_result,
            executed_slot_ids=scheduler_result.executed_slot_ids,
            provider_calls=[summary.model_dump(mode="json") for summary in provider_call_summaries],
            provider_call_summaries=provider_call_summaries,
            waiting_slot_ids=scheduler_result.waiting_slot_ids,
            failed_slot_ids=scheduler_result.failed_slot_ids,
            blocked_slot_ids=self._blocked_slot_ids(workflow),
            created_item_ids=scheduler_result.created_item_ids,
            created_slot_ids=scheduler_result.created_slot_ids,
        )

    def _persist_completed_provider_task_manifest(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        task: V2ProviderTask,
        result: V2ProviderResult,
    ) -> V2ProviderResultManifest:
        if result.status != "completed":
            raise WorkflowV2Error(
                "v2_provider_result_manifest_invalid",
                "Only completed provider task results can be persisted as manifests.",
            )
        execution_id = task.execution_id or f"task_{task.task_id}"
        attempt_id = str(task.metadata.get("attempt_id") or f"attempt_{task.task_id}")
        input_fingerprint = str(
            task.metadata.get("input_fingerprint")
            or self._generation_pipeline.input_fingerprint(workflow, item, slot)
        )
        context = V2ProviderExecutionContext(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            node_id=task.node_id,
            item_id=task.item_id,
            slot_id=task.slot_id,
            slot_type=slot.slot_type,
            media_type=slot.media_type,
            input_fingerprint=input_fingerprint,
            source_action=str(task.metadata.get("source_action") or "provider_task_poll"),
            select_generated=bool(task.metadata.get("select_generated", True)),
        )
        stored_plan = task.metadata.get("generation_plan_snapshot")
        try:
            plan = V2GenerationPlan.model_validate(stored_plan)
        except (TypeError, ValueError):
            plan = self._generation_pipeline.build_plan(
                workflow,
                item,
                slot,
                source_action=context.source_action,
            )
        provider_payload = sanitize_context_for_llm_text(
            {
                **task.provider_payload_snapshot,
                **result.provider_payload_snapshot,
            }
        )
        try:
            staging_path = self._provider_result_store.stage_provider_output(
                context=context,
                asset_bytes=result.asset_bytes,
                local_file_path=result.local_file_path,
            )
            return self._provider_result_store.persist_immediate_result(
                context=context,
                provider_name=result.provider or task.provider or "unknown-provider",
                provider_model=result.provider_model or task.provider_model,
                staging_path=staging_path,
                generation_plan_snapshot=plan.model_dump(mode="json"),
                provider_payload_snapshot=provider_payload,
                provider_result_metadata={
                    **result.metadata,
                    "provider_task_id": task.task_id,
                    "remote_task_id": result.remote_task_id or task.remote_task_id,
                    "completion_source": "provider_task_poll",
                },
                reference_asset_ids=list(
                    result.reference_asset_ids or task.metadata.get("reference_asset_ids") or []
                ),
            )
        except V2ProviderResultStoreError as exc:
            if exc.code == "v2_provider_result_output_missing":
                raise WorkflowV2Error(
                    "v2_provider_result_recovery_unavailable",
                    "The completed provider task output is no longer available for recovery.",
                ) from exc
            raise WorkflowV2Error(exc.code, str(exc)) from exc

    def _commit_completed_provider_task_manifest(
        self,
        manifest: V2ProviderResultManifest,
        task: V2ProviderTask,
        provider_result: V2ProviderResult,
    ) -> tuple[WorkflowV2, V2ProviderTask, _SchedulerRunResult, bool]:
        with self._defer_events() as deferred_events:
            result = self._commit_completed_provider_task_manifest_unbuffered(
                manifest,
                task,
                provider_result,
            )
        self._flush_deferred_events(deferred_events)
        workflow, updated_task, scheduler_result, should_continue = result
        if updated_task.execution_id:
            self._sync_execution_state_from_workflow(
                workflow,
                updated_task.execution_id,
                extra_completed_slot_ids=scheduler_result.executed_slot_ids,
            )
        return result

    def _commit_completed_provider_task_manifest_unbuffered(
        self,
        manifest: V2ProviderResultManifest,
        task: V2ProviderTask,
        provider_result: V2ProviderResult,
    ) -> tuple[WorkflowV2, V2ProviderTask, _SchedulerRunResult, bool]:
        scheduler_result = _SchedulerRunResult()
        with v2_workflow_lock(self._data_dir, manifest.workflow_id):
            workflow = self.get_workflow(manifest.workflow_id)
            slot = self._find_slot(workflow, manifest.slot_id)
            item = (
                self._find_item(workflow, manifest.node_id, manifest.item_id)
                if slot is not None
                else None
            )
            if slot is None or item is None:
                error = V2ProviderResultCommitError(
                    "v2_provider_result_manifest_invalid",
                    "Provider result manifest owner is no longer present in the workflow.",
                )
                self._provider_result_committer.reject(manifest, error)
                raise WorkflowV2Error(error.code, str(error))
            plan = V2GenerationPlan.model_validate(manifest.generation_plan_snapshot)
            output = next(output for output in manifest.outputs if output.is_primary)
            commit_result = provider_result.model_copy(
                update={
                    "asset_bytes": None,
                    "local_file_path": output.staging_path,
                    "metadata": {
                        **provider_result.metadata,
                        **manifest.provider_result_metadata,
                        "source_attempt_id": manifest.attempt_id,
                        "source_execution_id": manifest.execution_id,
                        "source_input_fingerprint": manifest.input_fingerprint,
                        "source_provider_result_id": manifest.provider_result_id,
                        "source_output_index": output.output_index,
                    },
                }
            )
            execution_result = V2SlotExecutionResult(
                job=V2SlotExecutionJob(
                    workflow_id=manifest.workflow_id,
                    execution_id=manifest.execution_id,
                    attempt_id=manifest.attempt_id,
                    input_fingerprint=manifest.input_fingerprint,
                    node_id=manifest.node_id,
                    item_id=manifest.item_id,
                    slot_id=manifest.slot_id,
                    slot_type=manifest.slot_type,
                    media_type=manifest.media_type,
                    source_action=manifest.source_action,
                    select_generated=manifest.select_generated,
                ),
                status="completed",
                plan=plan,
                provider_result=commit_result,
                provider_payload_snapshot=manifest.provider_payload_snapshot,
                provider_result_id=manifest.provider_result_id,
            )
            was_completed = slot.status == "completed" and (
                self._selected_provider_result_id(slot) == manifest.provider_result_id
            )
            self._commit_slot_execution_result(
                workflow,
                item,
                slot,
                execution_result,
                scheduler_result,
                source_action=manifest.source_action,
                mark_manifest_committed=False,
            )
            self._refresh_workflow_state(workflow)
            workflow = self.save_workflow(workflow)
            committed_slot = self._find_slot(workflow, manifest.slot_id)
            if committed_slot is None:
                raise WorkflowV2Error("slot_not_found")
            updated_task = self._provider_task_store.mark_poll_result(task, provider_result)
            updated_task = updated_task.model_copy(
                update={
                    "asset_id": (
                        committed_slot.current_working_asset_id
                        or committed_slot.selected_asset_id
                        or updated_task.asset_id
                    ),
                    "version_id": (
                        committed_slot.current_working_version_id
                        or committed_slot.selected_version_id
                        or updated_task.version_id
                    ),
                    "metadata": {
                        **updated_task.metadata,
                        "provider_result_id": manifest.provider_result_id,
                    },
                }
            )
            updated_task = self._provider_task_store.save_task(updated_task)
            self._append_provider_task_event(
                workflow,
                updated_task,
                "provider_task_completed",
                result=provider_result,
                asset_id=updated_task.asset_id,
                version_id=updated_task.version_id,
            )
            if updated_task.execution_id:
                self._sync_execution_state_from_workflow(
                    workflow,
                    updated_task.execution_id,
                    extra_completed_slot_ids=scheduler_result.executed_slot_ids,
                )
            if updated_task.asset_id and updated_task.version_id:
                self._provider_result_committer.mark_committed(
                    manifest,
                    asset_id=updated_task.asset_id,
                    version_id=updated_task.version_id,
                )
                self._append_event(
                    workflow.workflow_id,
                    "provider_result_committed",
                    execution_id=manifest.execution_id,
                    node_id=manifest.node_id,
                    item_id=manifest.item_id,
                    slot_id=manifest.slot_id,
                    asset_id=updated_task.asset_id,
                    version_id=updated_task.version_id,
                    payload={
                        "attempt_id": manifest.attempt_id,
                        "provider_result_id": manifest.provider_result_id,
                        "provider_task_id": updated_task.task_id,
                    },
                )
            return workflow, updated_task, scheduler_result, not was_completed

    def poll_due_provider_tasks(
        self,
        workflow_id: str,
        *,
        execution_id: str | None = None,
        limit: int | None = None,
    ) -> V2ProviderTaskPollResult:
        self.get_workflow(workflow_id)
        due_tasks = self._provider_task_store.list_due_tasks(
            workflow_id,
            execution_id=execution_id,
            limit=limit or self._settings.v2_provider_task_max_concurrent_polls,
        )
        return self._poll_provider_task_batch(
            workflow_id,
            due_tasks,
            execution_id=execution_id,
        )

    def _poll_provider_task_batch(
        self,
        workflow_id: str,
        tasks: list[V2ProviderTask],
        *,
        execution_id: str | None,
    ) -> V2ProviderTaskPollResult:
        result = V2ProviderTaskPollResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
        )
        completed_tasks: list[V2ProviderTask] = []
        previous_execution_id = getattr(self._execution_context, "execution_id", None)
        try:
            for task in tasks:
                self._execution_context.execution_id = task.execution_id
                try:
                    response = self.poll_provider_task(
                        workflow_id,
                        task.task_id,
                        resume_scheduler=False,
                    )
                except Exception as exc:
                    try:
                        response = self._record_provider_task_poll_exception(
                            workflow_id,
                            task,
                            exc,
                        )
                    except Exception as recovery_exc:
                        self._append_event(
                            workflow_id,
                            "provider_poll_loop_error",
                            execution_id=task.execution_id,
                            node_id=task.node_id,
                            item_id=task.item_id,
                            slot_id=task.slot_id,
                            payload={
                                "error_code": "v2_provider_task_poll_recording_failed",
                                "provider_task_id": task.task_id,
                                "poll_exception_type": exc.__class__.__name__,
                                "recording_exception_type": recovery_exc.__class__.__name__,
                                "message": str(recovery_exc)[:500],
                            },
                        )
                        result.polled_task_ids.append(task.task_id)
                        result.failed_task_ids.append(task.task_id)
                        result.failed_slot_ids.append(task.slot_id)
                        continue
                result.polled_task_ids.append(task.task_id)
                if response.task.status == "completed":
                    result.completed_task_ids.append(task.task_id)
                    if not _provider_task_response_reused_terminal_result(response):
                        completed_tasks.append(response.task)
                elif response.task.status == "failed":
                    result.failed_task_ids.append(task.task_id)
                else:
                    result.waiting_task_ids.append(task.task_id)
                result.executed_slot_ids.extend(response.executed_slot_ids)
                result.waiting_slot_ids.extend(response.waiting_slot_ids)
                result.failed_slot_ids.extend(response.failed_slot_ids)
            if completed_tasks:
                scheduler_result = self._resume_missing_slot_scheduler_after_provider_tasks(
                    self.get_workflow(workflow_id),
                    completed_tasks,
                )
                result.executed_slot_ids.extend(scheduler_result.executed_slot_ids)
                result.waiting_slot_ids.extend(scheduler_result.waiting_slot_ids)
                result.failed_slot_ids.extend(scheduler_result.failed_slot_ids)
                workflow = self.get_workflow(workflow_id)
                for completed_execution_id in {
                    task.execution_id for task in completed_tasks if task.execution_id
                }:
                    self._sync_execution_state_from_workflow(
                        workflow,
                        completed_execution_id,
                        extra_completed_slot_ids=scheduler_result.executed_slot_ids,
                        extra_waiting_slot_ids=scheduler_result.waiting_slot_ids,
                        extra_failed_slot_ids=scheduler_result.failed_slot_ids,
                    )
        finally:
            self._execution_context.execution_id = previous_execution_id
        return result.model_copy(
            update={
                "polled_task_ids": list(dict.fromkeys(result.polled_task_ids)),
                "completed_task_ids": list(dict.fromkeys(result.completed_task_ids)),
                "waiting_task_ids": list(dict.fromkeys(result.waiting_task_ids)),
                "failed_task_ids": list(dict.fromkeys(result.failed_task_ids)),
                "executed_slot_ids": list(dict.fromkeys(result.executed_slot_ids)),
                "waiting_slot_ids": list(dict.fromkeys(result.waiting_slot_ids)),
                "failed_slot_ids": list(dict.fromkeys(result.failed_slot_ids)),
            }
        )

    def _record_provider_task_poll_exception(
        self,
        workflow_id: str,
        task: V2ProviderTask,
        exc: Exception,
    ) -> V2ProviderTaskPollResponse:
        with v2_workflow_lock(self._data_dir, workflow_id):
            return self._record_provider_task_poll_exception_locked(
                workflow_id,
                task,
                exc,
            )

    def _record_provider_task_poll_exception_locked(
        self,
        workflow_id: str,
        task: V2ProviderTask,
        exc: Exception,
    ) -> V2ProviderTaskPollResponse:
        workflow = self.get_workflow(workflow_id)
        current_task = self._provider_task_store.load_task(workflow_id, task.task_id) or task
        if current_task.status == "completed":
            return V2ProviderTaskPollResponse(
                task=current_task,
                workflow=workflow,
                provider_result=self._provider_result_from_completed_task(current_task),
                blocked_slot_ids=self._blocked_slot_ids(workflow),
            )
        if current_task.status in {"failed", "cancelled"}:
            return V2ProviderTaskPollResponse(
                task=current_task,
                workflow=workflow,
                blocked_slot_ids=self._blocked_slot_ids(workflow),
            )
        slot = self._find_slot(workflow, current_task.slot_id)
        item = (
            self._find_item(workflow, current_task.node_id, current_task.item_id)
            if slot is not None
            else None
        )
        if slot is None or item is None:
            raise WorkflowV2Error(
                "slot_not_found",
                "Provider task owner is no longer present in the workflow.",
            ) from exc
        retryable = current_task.retry_count + 1 < _provider_task_max_attempts(
            current_task,
            self._settings,
        )
        error_code = (
            "v2_provider_task_poll_exception"
            if retryable
            else "v2_provider_task_poll_exception_exhausted"
        )
        result = V2ProviderResult(
            status="waiting" if retryable else "failed",
            media_type=_provider_task_media_type(current_task),
            remote_task_id=current_task.remote_task_id,
            provider=current_task.provider,
            provider_model=current_task.provider_model,
            provider_payload_snapshot=current_task.provider_payload_snapshot,
            error_code=error_code,
            error_message=str(exc)[:500] or exc.__class__.__name__,
            metadata={
                "stage": "provider_task_poll",
                "exception_type": exc.__class__.__name__,
                "waiting_reason": "retryable_provider_poll_error" if retryable else None,
                "next_poll_delay_seconds": _provider_retry_delay_seconds(
                    current_task,
                    V2ProviderResult(
                        status="failed",
                        media_type=_provider_task_media_type(current_task),
                        error_code=error_code,
                    ),
                    self._settings,
                )
                if retryable
                else None,
            },
        )
        slot_transitions: list[dict[str, Any]] = []
        self._generation_pipeline.apply_provider_task_result(
            workflow,
            item,
            slot,
            current_task,
            result,
            slot_transitions=slot_transitions,
            transition_slot=self._transition_slot,
            set_working_version_for_slot=self._set_working_version_for_slot,
            set_selected_version_for_slot=self._set_selected_version_for_slot,
            append_event=self._append_event,
        )
        updated_task = self._provider_task_store.mark_poll_result(current_task, result)
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        event_type = "provider_task_waiting" if retryable else "provider_task_failed"
        self._append_provider_task_event(workflow, updated_task, event_type, result=result)
        waiting_slot_ids = [slot.slot_id] if retryable else []
        failed_slot_ids = [] if retryable else [slot.slot_id]
        if updated_task.execution_id:
            self._sync_execution_state_from_workflow(
                workflow,
                updated_task.execution_id,
                extra_waiting_slot_ids=waiting_slot_ids,
                extra_failed_slot_ids=failed_slot_ids,
            )
        return V2ProviderTaskPollResponse(
            task=updated_task,
            workflow=workflow,
            provider_result=result,
            waiting_slot_ids=waiting_slot_ids,
            failed_slot_ids=failed_slot_ids,
            blocked_slot_ids=self._blocked_slot_ids(workflow),
        )

    def _start_provider_task_poll_loop(self, workflow_id: str, execution_id: str) -> None:
        if self._settings.media_mode.strip().lower() != "real":
            return
        key = (workflow_id, execution_id)
        with self._provider_poll_threads_lock:
            existing = self._provider_poll_threads.get(key)
            if existing is not None and existing.is_alive():
                return
            thread = threading.Thread(
                target=self._provider_task_poll_loop,
                args=(workflow_id, execution_id),
                name=f"v2-provider-task-poll-{execution_id}",
                daemon=True,
            )
            self._provider_poll_threads[key] = thread
            thread.start()

    def recover_active_provider_task_polling(self, workflow_id: str) -> bool:
        """Restart polling after process startup without submitting replacement work."""

        active = self._execution_service.load_active(workflow_id)
        if active is None:
            return False
        execution_id = str(active.get("execution_id") or "")
        if not execution_id:
            return False
        tasks = self._provider_task_store.list_nonterminal_tasks(
            workflow_id,
            execution_id=execution_id,
        )
        if not tasks:
            return False
        self._start_provider_task_poll_loop(workflow_id, execution_id)
        return True

    def _provider_task_poll_loop(self, workflow_id: str, execution_id: str) -> None:
        key = (workflow_id, execution_id)
        try:
            interval = max(1, self._settings.v2_provider_task_poll_interval_seconds)
            while True:
                active = self._execution_service.load_active(workflow_id)
                if not active or active.get("execution_id") != execution_id:
                    return
                tasks = self._provider_task_store.list_nonterminal_tasks(
                    workflow_id,
                    execution_id=execution_id,
                )
                if not tasks:
                    return
                try:
                    self.poll_due_provider_tasks(workflow_id, execution_id=execution_id)
                except Exception as exc:
                    self._append_event(
                        workflow_id,
                        "provider_poll_loop_error",
                        execution_id=execution_id,
                        payload={
                            "error_code": "v2_provider_poll_loop_exception",
                            "exception_type": exc.__class__.__name__,
                            "message": str(exc)[:500],
                        },
                    )
                    threading.Event().wait(interval)
                    continue
                active = self._execution_service.load_active(workflow_id)
                if not active or active.get("execution_id") != execution_id:
                    return
                if not self._provider_task_store.list_nonterminal_tasks(
                    workflow_id,
                    execution_id=execution_id,
                ):
                    return
                threading.Event().wait(interval)
        finally:
            with self._provider_poll_threads_lock:
                self._provider_poll_threads.pop(key, None)

    def resume_execution(
        self,
        workflow_id: str,
        execution_id: str,
    ) -> WorkflowV2RuntimeSnapshot:
        workflow = self.get_workflow(workflow_id)
        state = self._execution_service.load_state(workflow_id, execution_id)
        if state is None:
            raise WorkflowV2Error(
                "v2_execution_state_not_found",
                f"Execution state not found: {execution_id}.",
            )
        previous_execution_id = getattr(self._execution_context, "execution_id", None)
        self._execution_context.execution_id = execution_id
        try:
            workflow = self._execution_recovery.recover_interrupted_execution(
                workflow_id,
                trigger="explicit_resume",
            ).workflow
            self._reopen_historical_provider_result_tasks(
                workflow,
                execution_id=execution_id,
            )
            tasks = self._provider_task_store.list_nonterminal_tasks(
                workflow_id,
                execution_id=execution_id,
            )
            self._poll_provider_task_batch(
                workflow_id,
                tasks,
                execution_id=execution_id,
            )
            workflow = self.get_workflow(workflow_id)
            self._sync_execution_state_from_workflow(workflow, execution_id)
            self._start_provider_task_poll_loop(workflow_id, execution_id)
            return self.runtime_snapshot(workflow_id)
        finally:
            self._execution_context.execution_id = previous_execution_id

    def _reopen_historical_provider_result_tasks(
        self,
        workflow: WorkflowV2,
        *,
        execution_id: str | None = None,
    ) -> list[V2ProviderTask]:
        reopened: list[V2ProviderTask] = []
        for task in self._provider_task_store.list_tasks(workflow.workflow_id):
            if not self._historical_provider_result_recovery_eligible(
                workflow,
                task,
                execution_id=execution_id,
            ):
                continue
            updated_task = self._provider_task_store.reopen_for_result_retrieval(task)
            if updated_task.status != "waiting":
                continue
            slot = self._find_slot(workflow, updated_task.slot_id)
            if slot is None:
                continue
            slot.status = "waiting"
            slot.metadata.update(
                {
                    "provider_task_id": updated_task.task_id,
                    "remote_task_id": updated_task.remote_task_id,
                    "waiting_reason": "historical_provider_result_recovery",
                    "recovery_source": "historical_provider_result",
                }
            )
            reopened.append(updated_task)
        if not reopened:
            return []
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        for task in reopened:
            self._append_provider_task_event(
                workflow,
                task,
                "provider_task_waiting",
                result=V2ProviderResult(
                    status="waiting",
                    media_type=_provider_task_media_type(task),
                    remote_task_id=task.remote_task_id,
                    provider=task.provider,
                    provider_model=task.provider_model,
                    metadata={
                        "waiting_reason": "historical_provider_result_recovery",
                        "recovery_source": "historical_provider_result",
                        "download_attempt": task.download_attempt_count,
                        "max_download_attempts": _provider_download_max_attempts(self._settings),
                        "remote_status": task.metadata.get("remote_status"),
                    },
                ),
            )
        return reopened

    def _historical_provider_result_recovery_eligible(
        self,
        workflow: WorkflowV2,
        task: V2ProviderTask,
        *,
        execution_id: str | None,
    ) -> bool:
        if task.status != "failed" or not task.remote_task_id:
            return False
        if execution_id is not None and task.execution_id != execution_id:
            return False
        recovery = task.metadata.get("historical_result_recovery")
        if isinstance(recovery, dict) and recovery.get("exhausted") is True:
            return False
        slot = self._find_slot(workflow, task.slot_id)
        if slot is None or self._slot_has_valid_selected_asset(slot):
            return False
        remote_status = str(task.metadata.get("remote_status") or "").strip().lower()
        remote_success_reported = remote_status in {"succeeded", "completed", "success"}
        locally_timed_out = task.last_error_code == "v2_provider_task_timeout"
        if not remote_success_reported and not locally_timed_out:
            return False
        download_status = str(task.metadata.get("download_status") or "").strip().lower()
        download_error_code = str(task.metadata.get("download_error_code") or "").strip()
        if download_error_code == "provider_result_unavailable":
            return False
        if locally_timed_out:
            return True
        local_path = task.metadata.get("local_path")
        if (
            download_status == "failed"
            or bool(download_error_code)
            or not isinstance(local_path, str)
        ):
            return True
        try:
            relative_path = validate_v2_relative_path(
                local_path,
                operation="v2-historical-provider-result-recovery",
            )
        except V2DataBoundaryError:
            return True
        return not (self._data_dir / relative_path).exists()

    def _resume_missing_slot_scheduler_after_provider_task(
        self,
        workflow: WorkflowV2,
        task: V2ProviderTask,
    ) -> _SchedulerRunResult:
        return self._resume_missing_slot_scheduler_after_provider_tasks(workflow, [task])

    def _resume_missing_slot_scheduler_after_provider_tasks(
        self,
        workflow: WorkflowV2,
        tasks: list[V2ProviderTask],
    ) -> _SchedulerRunResult:
        if not tasks:
            return _SchedulerRunResult()
        result = self._run_missing_slot_scheduler(
            workflow,
            source_action="provider_task_resume",
            include_failed_slots=False,
        )
        source_task = tasks[0]
        source_task_ids = [task.task_id for task in tasks]
        source_slot_ids = [task.slot_id for task in tasks]
        execution_status = _execution_status_from_slots(
            completed_slot_ids=result.executed_slot_ids,
            waiting_slot_ids=result.waiting_slot_ids,
            failed_slot_ids=result.failed_slot_ids,
        )
        self._write_execution_record(
            workflow.workflow_id,
            mode="provider_task_resume",
            status=execution_status,
            completed_slot_ids=result.executed_slot_ids,
            failed_slot_ids=result.failed_slot_ids,
            waiting_slot_ids=result.waiting_slot_ids,
            slot_transitions=result.slot_transitions,
            source_execution_id=source_task.execution_id,
        )
        self._append_event(
            workflow.workflow_id,
            "scheduler_resumed",
            payload={
                "reason": "provider_tasks_reconciled",
                "source_task_id": source_task.task_id,
                "source_slot_id": source_task.slot_id,
                "source_task_ids": source_task_ids,
                "source_slot_ids": source_slot_ids,
                "status": execution_status,
                "completed_slot_ids": result.executed_slot_ids,
                "waiting_slot_ids": result.waiting_slot_ids,
                "failed_slot_ids": result.failed_slot_ids,
                "created_item_ids": result.created_item_ids,
                "created_slot_ids": result.created_slot_ids,
            },
        )
        self._append_event(
            workflow.workflow_id,
            "global_run_resumed",
            payload={
                "reason": "provider_tasks_reconciled",
                "source_task_id": source_task.task_id,
                "source_task_ids": source_task_ids,
                "status": execution_status,
                "completed_slot_ids": result.executed_slot_ids,
                "waiting_slot_ids": result.waiting_slot_ids,
                "failed_slot_ids": result.failed_slot_ids,
            },
        )
        return result

    def _append_provider_task_event(
        self,
        workflow: WorkflowV2,
        task: V2ProviderTask,
        event_type: str,
        *,
        result: V2ProviderResult | None = None,
        asset_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowV2Event:
        payload: dict[str, Any] = {
            "task_id": task.task_id,
            "provider_task_id": task.task_id,
            "execution_id": task.execution_id,
            "node_id": task.node_id,
            "item_id": task.item_id,
            "slot_id": task.slot_id,
            "task_status": task.status,
            "status": task.status,
            "remote_task_id": task.remote_task_id,
            "provider": task.provider,
            "provider_model": task.provider_model,
            "slot_type": task.metadata.get("slot_type"),
            "media_type": task.metadata.get("media_type"),
            "provider_result_id": task.metadata.get("provider_result_id"),
        }
        if result is not None:
            payload.update(
                {
                    "provider_result_status": result.status,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                    "waiting_reason": result.metadata.get("waiting_reason"),
                    "download_attempt": result.metadata.get("download_attempt"),
                    "max_download_attempts": result.metadata.get("max_download_attempts"),
                    "remote_status": result.metadata.get("remote_status"),
                    "recovery_source": result.metadata.get("recovery_source"),
                }
            )
        return self._append_event(
            workflow.workflow_id,
            event_type,
            node_id=task.node_id,
            item_id=task.item_id,
            slot_id=task.slot_id,
            asset_id=asset_id,
            version_id=version_id,
            payload=payload,
        )

    def _sync_execution_state_from_workflow(
        self,
        workflow: WorkflowV2,
        execution_id: str,
        *,
        extra_completed_slot_ids: list[str] | None = None,
        extra_waiting_slot_ids: list[str] | None = None,
        extra_failed_slot_ids: list[str] | None = None,
        metadata_updates: dict[str, Any] | None = None,
        status_override: str | None = None,
        clear_terminal_active: bool = True,
    ) -> dict[str, Any] | None:
        state = self._execution_service.load_state(workflow.workflow_id, execution_id)
        if state is None:
            return None
        snapshot = self._runtime_events.runtime_snapshot(
            workflow,
            active_execution=state,
            provider_tasks=self._provider_task_store.list_tasks(workflow.workflow_id),
        )
        completed_slot_ids = list(
            dict.fromkeys([*snapshot.completed_slot_ids, *(extra_completed_slot_ids or [])])
        )
        waiting_slot_ids = list(
            dict.fromkeys([*snapshot.waiting_slot_ids, *(extra_waiting_slot_ids or [])])
        )
        failed_slot_ids = list(
            dict.fromkeys([*snapshot.failed_slot_ids, *(extra_failed_slot_ids or [])])
        )
        status = snapshot.execution_status
        if not waiting_slot_ids and not snapshot.running_slot_ids:
            if failed_slot_ids and completed_slot_ids:
                status = "partial_failed"
            elif failed_slot_ids:
                status = "failed"
            else:
                status = "completed"
        if status_override:
            status = status_override
        metadata = {
            **dict(state.get("metadata") or {}),
            **dict(metadata_updates or {}),
        }
        updated_state = self._execution_service.save_state(
            workflow.workflow_id,
            execution_id,
            {
                **state,
                "status": status,
                "running_slot_ids": snapshot.running_slot_ids,
                "waiting_slot_ids": waiting_slot_ids,
                "completed_slot_ids": completed_slot_ids,
                "failed_slot_ids": failed_slot_ids,
                "blocked_slot_ids": snapshot.blocked_slot_ids,
                "skipped_slot_ids": snapshot.skipped_slot_ids,
                "slot_runtime": snapshot.slot_runtime,
                "events_cursor": snapshot.events_cursor,
                "metadata": metadata,
                "finished_at": utc_now().isoformat()
                if status in {"completed", "partial_failed", "failed", "cancelled"}
                else None,
            },
        )
        if clear_terminal_active and status in {
            "completed",
            "partial_failed",
            "failed",
            "cancelled",
        }:
            self._execution_service.clear_active(
                workflow.workflow_id,
                execution_id=execution_id,
            )
        return updated_state

    def _provider_result_from_completed_task(self, task: V2ProviderTask) -> V2ProviderResult:
        return V2ProviderResult(
            status="completed",
            media_type=_provider_task_media_type(task),
            remote_task_id=task.remote_task_id,
            provider=task.provider,
            provider_model=task.provider_model,
            provider_payload_snapshot=task.provider_payload_snapshot,
            reference_asset_ids=[
                str(asset_id) for asset_id in task.metadata.get("reference_asset_ids", [])
            ],
            metadata={"terminal_task_reused": True},
        )

    def save_workflow(self, workflow: WorkflowV2) -> WorkflowV2:
        return self._workflow_store.save_workflow(workflow)

    def _preflight_visual_style_scope(
        self,
        workflow_id: str,
        *,
        source: VisualStyleScopeSource,
    ) -> WorkflowV2:
        with v2_workflow_lock(self._data_dir, workflow_id):
            workflow = self._workflow_store.load_workflow(workflow_id)
            result = self._visual_style_scope_service.repair_persisted_contract(
                workflow,
                source=source,
            )
            if result.changed:
                workflow = self._workflow_store.save_workflow(result.workflow)
            else:
                workflow = result.workflow
            if result.contract_repaired:
                self._append_event(
                    workflow_id,
                    "visual_style_scope_repaired",
                    payload={
                        "source": result.audit.source,
                        "repair_mode": result.audit.repair_mode,
                        "removed_scopes": list(result.audit.removed_scopes),
                        "original_contract_hash": result.audit.original_contract_hash,
                        "effective_contract_hash": result.audit.effective_contract_hash,
                    },
                )
        return workflow

    def _run_missing_slot_scheduler(
        self,
        workflow: WorkflowV2,
        *,
        source_action: str,
        mode: str = "fill_missing_required_slots",
        include_failed_slots: bool,
    ) -> _SchedulerRunResult:
        result = _SchedulerRunResult()
        execution_id = getattr(self._execution_context, "execution_id", None)
        config = self._scheduler_concurrency_config(workflow)
        state = V2ParallelSlotSchedulerState()
        futures: dict[Future[Any], str] = {}
        attempted_slot_ids: set[str] = set()
        max_workers = max(1, config.max_parallel_generation_jobs)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                try:
                    self._unlock_dynamic_v2_slots(workflow, result)
                except Exception as exc:  # noqa: BLE001 - drain submitted workers before failure.
                    self._drain_started_scheduler_futures(
                        workflow,
                        futures,
                        state,
                        result,
                        source_action=source_action,
                    )
                    raise WorkflowV2Error(
                        "v2_execution_internal_error",
                        "V2 scheduler coordination failed after submitted provider work was drained.",
                        details={"stage": "scheduler_preflight", "cause": str(exc)[:500]},
                    ) from exc
                graph = V2SlotDependencyGraph(
                    scheduler=self._slot_scheduler,
                    workflow=workflow,
                    mode=mode,
                    include_failed_slots=include_failed_slots,
                )
                submitted = False
                for item, slot in graph.ready_slots():
                    if slot.slot_id in attempted_slot_ids:
                        continue
                    if slot.slot_id in state.running_slot_ids:
                        continue
                    if is_final_composition_slot(slot):
                        if state.running_slot_ids:
                            continue
                        attempted_slot_ids.add(slot.slot_id)
                        try:
                            self._generate_slot(
                                workflow,
                                item,
                                slot,
                                result.executed_slot_ids,
                                result.provider_calls,
                                select_generated=True,
                                source_action=source_action,
                                slot_transitions=result.slot_transitions,
                            )
                        except WorkflowV2Error:
                            result.failed_slot_ids.append(slot.slot_id)
                            self._refresh_workflow_state(workflow)
                        submitted = True
                        break
                    if not state.can_submit(slot, config):
                        continue
                    attempted_slot_ids.add(slot.slot_id)
                    self._transition_slot(
                        workflow,
                        slot,
                        "running",
                        result.slot_transitions,
                        event_type="slot_generation_started",
                        payload={
                            "execution_id": execution_id,
                            "node_id": slot.node_id,
                            "item_id": item.item_id,
                            "slot_id": slot.slot_id,
                            "slot_type": slot.slot_type,
                            "media_type": slot.media_type,
                            "status": "running",
                        },
                    )
                    state.mark_submitted(slot)
                    workflow_snapshot = workflow.model_copy(deep=True)
                    if execution_id:
                        execution_state = (
                            self._execution_service.load_state(
                                workflow.workflow_id,
                                execution_id,
                            )
                            or {}
                        )
                        selections = dict(
                            (execution_state.get("metadata") or {}).get("shot_reference_selections")
                            or {}
                        )
                        if selections:
                            workflow_snapshot.metadata["execution_shot_reference_selections"] = (
                                selections
                            )
                    snapshot_slot = self._find_slot(workflow_snapshot, slot.slot_id)
                    snapshot_item = (
                        self._find_item(workflow_snapshot, slot.node_id, slot.item_id)
                        if snapshot_slot is not None
                        else None
                    )
                    if snapshot_item is None or snapshot_slot is None:
                        result.failed_slot_ids.append(slot.slot_id)
                        state.mark_finished(slot)
                        self._transition_slot(
                            workflow,
                            slot,
                            "failed",
                            result.slot_transitions,
                            event_type="slot_generation_failed",
                            payload={
                                "error_code": "slot_snapshot_failed",
                                "status": "failed",
                                "slot_type": slot.slot_type,
                                "media_type": slot.media_type,
                            },
                        )
                        continue
                    futures[
                        executor.submit(
                            self._generation_pipeline.execute_slot_provider,
                            workflow_snapshot,
                            snapshot_item,
                            snapshot_slot,
                            source_action=source_action,
                            execution_id=execution_id,
                            append_worker_event=self._append_event,
                        )
                    ] = slot.slot_id
                    submitted = True
                if futures:
                    done, _pending = wait(
                        futures.keys(),
                        timeout=0 if submitted else None,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done and submitted:
                        continue
                    try:
                        for future in done:
                            self._consume_scheduler_future(
                                workflow,
                                future,
                                futures,
                                state,
                                result,
                                source_action=source_action,
                            )
                    except WorkflowV2Error:
                        self._drain_started_scheduler_futures(
                            workflow,
                            futures,
                            state,
                            result,
                            source_action=source_action,
                        )
                        raise
                    continue
                if submitted:
                    continue
                break
        self._refresh_workflow_state(workflow)
        result.waiting_slot_ids = _waiting_slot_ids(result.slot_transitions)
        result.failed_slot_ids = list(
            dict.fromkeys(
                [
                    *result.failed_slot_ids,
                    *[
                        str(transition["slot_id"])
                        for transition in result.slot_transitions
                        if transition.get("to_status") == "failed"
                    ],
                ]
            )
        )
        return result

    def _drain_started_scheduler_futures(
        self,
        workflow: WorkflowV2,
        futures: dict[Future[Any], str],
        state: V2ParallelSlotSchedulerState,
        scheduler_result: _SchedulerRunResult,
        *,
        source_action: str,
    ) -> None:
        """Consume every submitted worker before a coordinator failure becomes terminal."""
        for future in list(futures):
            try:
                self._consume_scheduler_future(
                    workflow,
                    future,
                    futures,
                    state,
                    scheduler_result,
                    source_action=source_action,
                )
            except WorkflowV2Error:
                continue

    def _consume_scheduler_future(
        self,
        workflow: WorkflowV2,
        future: Future[Any],
        futures: dict[Future[Any], str],
        state: V2ParallelSlotSchedulerState,
        scheduler_result: _SchedulerRunResult,
        *,
        source_action: str,
    ) -> None:
        slot_id = futures.pop(future)
        current_slot = self._find_slot(workflow, slot_id)
        current_item = (
            self._find_item(workflow, current_slot.node_id, current_slot.item_id)
            if current_slot is not None
            else None
        )
        if current_slot is None or current_item is None:
            scheduler_result.failed_slot_ids.append(slot_id)
            return
        state.mark_finished(current_slot)
        try:
            execution_result = future.result()
        except Exception as exc:  # noqa: BLE001 - provider failures remain slot-scoped.
            scheduler_result.failed_slot_ids.append(slot_id)
            current_slot.metadata["error"] = {
                "code": "provider_generation_failed",
                "message": str(exc),
            }
            self._transition_slot(
                workflow,
                current_slot,
                "failed",
                scheduler_result.slot_transitions,
                event_type="slot_generation_failed",
                payload={
                    "error_code": "provider_generation_failed",
                    "error_message": str(exc),
                    "status": "failed",
                    "slot_type": current_slot.slot_type,
                    "media_type": current_slot.media_type,
                },
            )
            return
        try:
            self._commit_slot_execution_result(
                workflow,
                current_item,
                current_slot,
                execution_result,
                scheduler_result,
                source_action=source_action,
            )
        except V2GenerationPipelineError:
            scheduler_result.failed_slot_ids.append(slot_id)
            self._refresh_workflow_state(workflow)
        except Exception as exc:  # noqa: BLE001 - canonical commit errors stop new work.
            raise WorkflowV2Error(
                "v2_execution_internal_error",
                "V2 scheduler canonical commit failed after provider completion.",
                details={"stage": "scheduler_commit", "cause": str(exc)[:500]},
            ) from exc

    def _commit_slot_execution_result(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        execution_result: Any,
        scheduler_result: _SchedulerRunResult,
        *,
        source_action: str,
        mark_manifest_committed: bool = True,
    ) -> None:
        with v2_workflow_lock(self._data_dir, workflow.workflow_id):
            current_workflow = self.get_workflow(workflow.workflow_id)
            current_slot = self._find_slot(
                current_workflow,
                execution_result.job.slot_id,
            )
            current_item = (
                self._find_item(
                    current_workflow,
                    execution_result.job.node_id,
                    execution_result.job.item_id,
                )
                if current_slot is not None
                else None
            )
            if current_slot is None or current_item is None:
                raise WorkflowV2Error(
                    "v2_provider_result_manifest_invalid",
                    "Provider result target no longer exists in the workflow.",
                )
            self._commit_slot_execution_result_locked(
                current_workflow,
                current_item,
                current_slot,
                execution_result,
                scheduler_result,
                source_action=source_action,
                mark_manifest_committed=mark_manifest_committed,
            )
            self._overwrite_workflow_model(workflow, current_workflow)

    def _commit_slot_execution_result_locked(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        execution_result: Any,
        scheduler_result: _SchedulerRunResult,
        *,
        source_action: str,
        mark_manifest_committed: bool = True,
    ) -> None:
        manifest = None
        if execution_result.provider_result_id and execution_result.job.attempt_id:
            execution_id = execution_result.job.execution_id
            if execution_id:
                manifest = self._provider_result_store.load_manifest(
                    workflow_id=workflow.workflow_id,
                    execution_id=execution_id,
                    slot_id=slot.slot_id,
                    attempt_id=execution_result.job.attempt_id,
                )
        if manifest is not None:
            try:
                self._provider_result_committer.validate_manifest(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    manifest=manifest,
                    expected_input_fingerprint=self._generation_pipeline.input_fingerprint(
                        workflow,
                        item,
                        slot,
                    ),
                )
                selected_provider_result_id = self._selected_provider_result_id(slot)
                if (
                    manifest.select_generated
                    and slot.selected_asset_id is not None
                    and selected_provider_result_id != manifest.provider_result_id
                ):
                    raise V2ProviderResultCommitError(
                        "v2_provider_result_input_mismatch",
                        "Provider result would overwrite a newer selected asset version.",
                    )
            except V2ProviderResultCommitError as exc:
                self._provider_result_committer.reject(manifest, exc)
                self._append_event(
                    workflow.workflow_id,
                    "provider_result_rejected",
                    execution_id=execution_result.job.execution_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    payload={
                        "attempt_id": execution_result.job.attempt_id,
                        "provider_result_id": manifest.provider_result_id,
                        "error_code": exc.code,
                        "error_message": str(exc),
                    },
                )

                execution_result = execution_result.model_copy(
                    update={
                        "status": "failed",
                        "provider_result": V2ProviderResult(
                            status="failed",
                            media_type=slot.media_type,
                            provider=slot.provider,
                            error_code=exc.code,
                            error_message=str(exc),
                        ),
                        "error_code": exc.code,
                        "error_message": str(exc),
                    }
                )
            else:
                self._append_event(
                    workflow.workflow_id,
                    "provider_result_commit_started",
                    execution_id=execution_result.job.execution_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    payload={
                        "attempt_id": execution_result.job.attempt_id,
                        "provider_result_id": manifest.provider_result_id,
                    },
                )
                existing_asset = self._canonical_asset_for_manifest(manifest)
                slot.metadata["provider_result_id"] = manifest.provider_result_id
                provider_task_id = manifest.provider_result_metadata.get("provider_task_id")
                if isinstance(provider_task_id, str) and provider_task_id:
                    slot.metadata["provider_task_id"] = provider_task_id
                if existing_asset is not None:
                    self._finalize_existing_manifest_commit(
                        workflow,
                        slot,
                        manifest,
                        scheduler_result,
                        source_action=source_action,
                        mark_manifest_committed=mark_manifest_committed,
                    )
                    return
        self._generation_pipeline.apply_slot_execution_result(
            workflow,
            item,
            slot,
            execution_result,
            scheduler_result.executed_slot_ids,
            scheduler_result.provider_calls,
            select_generated=execution_result.job.select_generated,
            source_action=source_action,
            slot_transitions=scheduler_result.slot_transitions,
            transition_slot=self._transition_slot,
            set_working_version_for_slot=self._set_working_version_for_slot,
            set_selected_version_for_slot=self._set_selected_version_for_slot,
            append_event=self._append_event,
        )
        if (
            mark_manifest_committed
            and manifest is not None
            and execution_result.provider_result.status == "completed"
        ):
            asset_id = slot.selected_asset_id or slot.current_working_asset_id
            version_id = slot.selected_version_id or slot.current_working_version_id
            if asset_id and version_id:
                self._provider_result_committer.mark_committed(
                    manifest,
                    asset_id=asset_id,
                    version_id=version_id,
                )
                self._append_event(
                    workflow.workflow_id,
                    "provider_result_committed",
                    execution_id=execution_result.job.execution_id,
                    node_id=slot.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    asset_id=asset_id,
                    version_id=version_id,
                    payload={
                        "attempt_id": execution_result.job.attempt_id,
                        "provider_result_id": manifest.provider_result_id,
                    },
                )

    def _canonical_asset_for_manifest(
        self,
        manifest: Any,
    ) -> WorkflowAssetVersionV2 | None:
        asset = self._asset_store.load_asset_version(
            f"asset_{manifest.provider_result_id}",
            f"ver_{manifest.provider_result_id}_0",
        )
        if asset is None:
            return None
        if asset.metadata.get("source_provider_result_id") != manifest.provider_result_id:
            return None
        return asset

    def _selected_provider_result_id(self, slot: WorkflowSlotV2) -> str | None:
        if not slot.selected_asset_id or not slot.selected_version_id:
            return None
        asset = self._asset_store.load_asset_version(
            slot.selected_asset_id,
            slot.selected_version_id,
        )
        if asset is None:
            return None
        value = asset.metadata.get("source_provider_result_id")
        return str(value) if value else None

    def _finalize_existing_manifest_commit(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        manifest: Any,
        scheduler_result: _SchedulerRunResult,
        *,
        source_action: str,
        mark_manifest_committed: bool = True,
    ) -> None:
        asset = self._canonical_asset_for_manifest(manifest)
        if asset is None:
            raise WorkflowV2Error(
                "v2_provider_result_manifest_invalid",
                "Canonical provider result asset could not be recovered.",
            )
        self._set_working_version_for_slot(
            workflow,
            slot,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            source_action=source_action,
        )
        self._set_selected_version_for_slot(
            workflow,
            slot,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            source_action=source_action,
        )
        if slot.status != "completed":
            self._transition_slot(
                workflow,
                slot,
                "completed",
                scheduler_result.slot_transitions,
                event_type="slot_generation_completed",
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                payload={
                    "status": "completed",
                    "recovered_provider_result": True,
                    "slot_type": slot.slot_type,
                    "media_type": slot.media_type,
                },
            )
        if slot.slot_id not in scheduler_result.executed_slot_ids:
            scheduler_result.executed_slot_ids.append(slot.slot_id)
        if mark_manifest_committed:
            self._provider_result_committer.mark_committed(
                manifest,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
            )
            self._append_event(
                workflow.workflow_id,
                "provider_result_committed",
                execution_id=manifest.execution_id,
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=asset.asset_id,
                version_id=asset.version_id,
                payload={
                    "attempt_id": manifest.attempt_id,
                    "provider_result_id": manifest.provider_result_id,
                    "recovered_existing_canonical_asset": True,
                },
            )

    def _recover_pending_provider_manifests(self, workflow: WorkflowV2) -> list[str]:
        workflow_id = workflow.workflow_id
        recovered_slot_ids: list[str] = []
        recovered_slot_ids_by_execution: dict[str, list[str]] = {}
        scheduler_result = _SchedulerRunResult()
        with v2_workflow_lock(self._data_dir, workflow_id):
            current_workflow = self.get_workflow(workflow_id)
            for manifest in self._provider_result_store.list_manifests(workflow_id=workflow_id):
                if manifest.provider_status != "succeeded" or manifest.commit_status != "pending":
                    continue
                slot = self._find_slot(current_workflow, manifest.slot_id)
                item = (
                    self._find_item(current_workflow, manifest.node_id, manifest.item_id)
                    if slot is not None
                    else None
                )
                if slot is None or item is None:
                    self._provider_result_committer.reject(
                        manifest,
                        V2ProviderResultCommitError(
                            "v2_provider_result_manifest_invalid",
                            "Provider result manifest owner is no longer present in the workflow.",
                        ),
                    )
                    continue
                self._append_event(
                    current_workflow.workflow_id,
                    "provider_result_recovery_started",
                    execution_id=manifest.execution_id,
                    node_id=manifest.node_id,
                    item_id=manifest.item_id,
                    slot_id=manifest.slot_id,
                    payload={
                        "attempt_id": manifest.attempt_id,
                        "provider_result_id": manifest.provider_result_id,
                    },
                )
                try:
                    plan = V2GenerationPlan.model_validate(manifest.generation_plan_snapshot)
                except ValueError:
                    self._provider_result_committer.reject(
                        manifest,
                        V2ProviderResultCommitError(
                            "v2_provider_result_manifest_invalid",
                            "Provider result manifest cannot reconstruct its generation plan.",
                        ),
                    )
                    continue
                output = next(output for output in manifest.outputs if output.is_primary)
                execution_result = V2SlotExecutionResult(
                    job=V2SlotExecutionJob(
                        workflow_id=current_workflow.workflow_id,
                        execution_id=manifest.execution_id,
                        attempt_id=manifest.attempt_id,
                        input_fingerprint=manifest.input_fingerprint,
                        node_id=manifest.node_id,
                        item_id=manifest.item_id,
                        slot_id=manifest.slot_id,
                        slot_type=manifest.slot_type,
                        media_type=manifest.media_type,
                        source_action=manifest.source_action,
                        select_generated=manifest.select_generated,
                    ),
                    status="completed",
                    plan=plan,
                    provider_result=V2ProviderResult(
                        status="completed",
                        media_type=manifest.media_type,
                        local_file_path=output.staging_path,
                        provider=manifest.provider_name,
                        provider_model=manifest.provider_model,
                        provider_payload_snapshot=manifest.provider_payload_snapshot,
                        reference_asset_ids=manifest.reference_asset_ids,
                        metadata={
                            **manifest.provider_result_metadata,
                            "source_attempt_id": manifest.attempt_id,
                            "source_execution_id": manifest.execution_id,
                            "source_input_fingerprint": manifest.input_fingerprint,
                            "source_provider_result_id": manifest.provider_result_id,
                            "source_output_index": output.output_index,
                        },
                    ),
                    provider_payload_snapshot=manifest.provider_payload_snapshot,
                    provider_result_id=manifest.provider_result_id,
                )
                previous_execution_id = getattr(self._execution_context, "execution_id", None)
                self._execution_context.execution_id = manifest.execution_id
                try:
                    self._commit_slot_execution_result(
                        current_workflow,
                        item,
                        slot,
                        execution_result,
                        scheduler_result,
                        source_action=manifest.source_action,
                    )
                except V2GenerationPipelineError:
                    continue
                finally:
                    self._execution_context.execution_id = previous_execution_id
                recovered_slot_ids.append(slot.slot_id)
                recovered_slot_ids_by_execution.setdefault(manifest.execution_id, []).append(
                    slot.slot_id
                )
                committed_manifest = self._provider_result_store.load_manifest(
                    workflow_id=manifest.workflow_id,
                    execution_id=manifest.execution_id,
                    slot_id=manifest.slot_id,
                    attempt_id=manifest.attempt_id,
                )
                if (
                    committed_manifest is not None
                    and committed_manifest.commit_status == "committed"
                ):
                    self._append_event(
                        current_workflow.workflow_id,
                        "provider_result_recovery_completed",
                        execution_id=manifest.execution_id,
                        node_id=manifest.node_id,
                        item_id=manifest.item_id,
                        slot_id=manifest.slot_id,
                        asset_id=(committed_manifest.canonical_asset_ids or [None])[0],
                        version_id=(committed_manifest.canonical_version_ids or [None])[0],
                        payload={
                            "attempt_id": manifest.attempt_id,
                            "provider_result_id": manifest.provider_result_id,
                        },
                    )
            if recovered_slot_ids:
                current_workflow = self.save_workflow(current_workflow)
                for execution_id, completed_slot_ids in recovered_slot_ids_by_execution.items():
                    self._sync_execution_state_from_workflow(
                        current_workflow,
                        execution_id,
                        extra_completed_slot_ids=completed_slot_ids,
                    )
            self._overwrite_workflow_model(workflow, current_workflow)
        return recovered_slot_ids

    @staticmethod
    def _overwrite_workflow_model(target: WorkflowV2, source: WorkflowV2) -> None:
        for field_name in type(source).model_fields:
            setattr(target, field_name, getattr(source, field_name))

    def _unlock_dynamic_v2_slots(
        self,
        workflow: WorkflowV2,
        result: _SchedulerRunResult,
    ) -> None:
        self._refresh_workflow_state(workflow)
        if self._visual_reference_bundles_complete(workflow):
            new_items, new_slots = self._ensure_storyboard_shots(workflow)
            result.created_item_ids.extend(new_items)
            result.created_slot_ids.extend(new_slots)
        self._refresh_workflow_state(workflow)
        if self._final_inputs_ready(workflow):
            new_items, new_slots = self._ensure_final_composition_item(workflow)
            result.created_item_ids.extend(new_items)
            result.created_slot_ids.extend(new_slots)
        self._refresh_workflow_state(workflow)

    def _scheduler_concurrency_config(self, workflow: WorkflowV2):
        config = concurrency_config_from_settings(self._settings)
        cooldowns = workflow.metadata.get("provider_cooldowns")
        if not isinstance(cooldowns, dict):
            return config
        now = datetime.now(timezone.utc)
        image_limit = config.max_parallel_image_jobs
        video_limit = config.max_parallel_video_jobs
        for media_type, cooldown in cooldowns.items():
            if not isinstance(cooldown, dict) or not _cooldown_is_active(cooldown, now):
                continue
            try:
                reduced_jobs = int(cooldown.get("reduced_parallel_jobs"))
            except (TypeError, ValueError):
                continue
            if media_type == "image":
                image_limit = max(1, min(image_limit, reduced_jobs))
            elif media_type == "video":
                video_limit = max(1, min(video_limit, reduced_jobs))
        return config.model_copy(
            update={
                "max_parallel_image_jobs": image_limit,
                "max_parallel_video_jobs": video_limit,
            }
        )

    def _record_provider_cooldown(
        self,
        workflow: WorkflowV2,
        task: V2ProviderTask,
        result: V2ProviderResult,
    ) -> None:
        if result.error_code != "provider_rate_limited":
            return
        media_type = _provider_task_media_type(task)
        if media_type not in {"image", "video"}:
            return
        reduced_jobs = (
            self._settings.v2_provider_rate_limit_reduced_image_jobs
            if media_type == "image"
            else self._settings.v2_provider_rate_limit_reduced_video_jobs
        )
        active_until = (
            datetime.now(timezone.utc)
            + timedelta(seconds=self._settings.v2_provider_rate_limit_cooldown_seconds)
        ).isoformat()
        cooldowns = dict(workflow.metadata.get("provider_cooldowns") or {})
        cooldowns[media_type] = {
            "media_type": media_type,
            "reason": result.error_code,
            "active_until": active_until,
            "reduced_parallel_jobs": reduced_jobs,
            "provider_task_id": task.task_id,
            "remote_task_id": task.remote_task_id,
        }
        workflow.metadata["provider_cooldowns"] = cooldowns

    def _run_slot_types(
        self,
        workflow: WorkflowV2,
        slot_types: tuple[str, ...],
        executed_slot_ids: list[str],
        provider_calls: list[dict[str, Any]],
        slot_transitions: list[dict[str, Any]],
        failed_slot_ids: list[str],
        *,
        source_action: str,
        mode: str,
        include_failed_slots: bool,
    ) -> None:
        for item, slot in self._slot_scheduler.targetable_slots(
            workflow,
            slot_types,
            mode=mode,
            include_failed=include_failed_slots,
        ):
            try:
                self._generate_slot(
                    workflow,
                    item,
                    slot,
                    executed_slot_ids,
                    provider_calls,
                    select_generated=True,
                    source_action=source_action,
                    slot_transitions=slot_transitions,
                )
            except WorkflowV2Error:
                failed_slot_ids.append(slot.slot_id)
                self._refresh_workflow_state(workflow)

    def _generate_slot(
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
    ) -> None:
        try:
            self._generation_pipeline.generate_slot(
                workflow,
                item,
                slot,
                executed_slot_ids,
                provider_calls,
                select_generated=select_generated,
                source_action=source_action,
                slot_transitions=slot_transitions,
                transition_slot=self._transition_slot,
                set_working_version_for_slot=self._set_working_version_for_slot,
                set_selected_version_for_slot=self._set_selected_version_for_slot,
                append_event=self._append_event,
                execution_id=getattr(self._execution_context, "execution_id", None),
            )
        except V2GenerationPipelineError as exc:
            raise WorkflowV2Error(exc.code, str(exc)) from exc

    def _transition_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        to_status: str,
        slot_transitions: list[dict[str, Any]],
        *,
        event_type: str,
        asset_id: str | None = None,
        version_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        from_status = slot.status
        if payload is not None:
            payload = dict(payload)
            for key in ("provider_task_id", "provider_result_id"):
                value = slot.metadata.get(key)
                if value and key not in payload:
                    payload[key] = value
        if to_status in {"queued", "running"}:
            for key in (
                "generation_error",
                "generation_error_code",
                "error",
                "skipped_reason",
                "recoverable",
            ):
                slot.metadata.pop(key, None)
        if to_status in {"completed", "failed", "skipped"}:
            slot.metadata.pop("waiting_reason", None)
        slot.status = to_status  # type: ignore[assignment]
        self._refresh_workflow_state(workflow)
        workflow = self.save_workflow(workflow)
        event = self._append_event(
            workflow.workflow_id,
            event_type,
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=asset_id,
            version_id=version_id,
            payload=payload,
        )
        slot_transitions.append(
            {
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "from_status": from_status,
                "to_status": to_status,
                "created_at": event.created_at,
                "event_seq": event.seq,
            }
        )
        snapshot_payload: dict[str, Any] = {"status": to_status}
        if isinstance(payload, dict) and isinstance(payload.get("prompt_audit"), dict):
            snapshot_payload["prompt_audit"] = sanitize_context_for_llm_text(
                payload["prompt_audit"]
            )
        runtime_event = self._append_event(
            workflow.workflow_id,
            "runtime_snapshot_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload=snapshot_payload,
        )
        execution_id = getattr(self._execution_context, "execution_id", None)
        if not execution_id:
            active = self._execution_service.load_active(workflow.workflow_id)
            execution_id = active.get("execution_id") if active else None
        if execution_id:
            self._execution_service.update_slot_runtime(
                workflow.workflow_id,
                str(execution_id),
                _slot_runtime_from_transition(
                    slot,
                    to_status,
                    execution_id=str(execution_id),
                    updated_at=runtime_event.created_at,
                    last_event_seq=runtime_event.seq,
                    last_event_type=runtime_event.event_type,
                    payload=payload,
                    asset_id=asset_id,
                    version_id=version_id,
                ),
                events_cursor=runtime_event.seq,
            )

    def _set_working_version_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        asset_id: str,
        version_id: str,
        source_action: str,
    ) -> WorkflowAssetRelationV2:
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="working_version_for_slot",
        )
        relation = self._asset_store.create_relation(
            relation_type="working_version_for_slot",
            source_asset_id=asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata=self._slot_relation_metadata(slot, version_id, source_action),
        )
        self._emit_slot_relation_events(
            workflow,
            relation,
            slot,
            version_id=version_id,
            event_type="slot_working_version_updated",
        )
        self._append_event(
            workflow.workflow_id,
            "slot_working_version_created",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload={
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "asset_id": relation.source_asset_id,
                "version_id": version_id,
                "slot_id": slot.slot_id,
                "source_action": relation.metadata.get("source_action"),
            },
        )
        return relation

    def _set_selected_version_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        asset_id: str,
        version_id: str,
        source_action: str,
    ) -> WorkflowAssetRelationV2:
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="selected_for_slot",
        )
        relation = self._asset_store.create_relation(
            relation_type="selected_for_slot",
            source_asset_id=asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata=self._slot_relation_metadata(slot, version_id, source_action),
        )
        self._emit_slot_relation_events(
            workflow,
            relation,
            slot,
            version_id=version_id,
            event_type="slot_selected_version_updated",
        )
        slot.metadata.pop("stale", None)
        return relation

    def _append_history_version_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        asset_id: str,
        version_id: str,
        source_action: str,
    ) -> WorkflowAssetRelationV2:
        existing = self._asset_store.list_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="history_version_for_slot",
        )
        for relation in existing:
            if relation.metadata.get("version_id") == version_id:
                return relation
        relation = self._asset_store.create_relation(
            relation_type="history_version_for_slot",
            source_asset_id=asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata=self._slot_relation_metadata(slot, version_id, source_action),
        )
        self._emit_slot_relation_events(
            workflow,
            relation,
            slot,
            version_id=version_id,
            event_type="slot_history_updated",
        )
        return relation

    def _clear_selected_version_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        source_action: str,
    ) -> list[WorkflowAssetRelationV2]:
        removed = self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="selected_for_slot",
        )
        for relation in removed:
            self._append_event(
                workflow.workflow_id,
                "asset_relation_updated",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=relation.source_asset_id,
                version_id=str(relation.metadata.get("version_id") or ""),
                payload={
                    "relation_id": relation.relation_id,
                    "relation_type": relation.relation_type,
                    "source_action": source_action,
                    "removed": True,
                },
            )
        return removed

    def _clear_working_version_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        source_action: str,
    ) -> list[WorkflowAssetRelationV2]:
        removed = self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="working_version_for_slot",
        )
        for relation in removed:
            self._append_event(
                workflow.workflow_id,
                "asset_relation_updated",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=relation.source_asset_id,
                version_id=str(relation.metadata.get("version_id") or ""),
                payload={
                    "relation_id": relation.relation_id,
                    "relation_type": relation.relation_type,
                    "source_action": source_action,
                    "removed": True,
                },
            )
        return removed

    def _slot_relation_metadata(
        self,
        slot: WorkflowSlotV2,
        version_id: str,
        source_action: str,
    ) -> dict[str, Any]:
        return {
            "version_id": version_id,
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "semantic_type": _semantic_type_for_slot(slot.slot_type, slot.media_type),
            "source_action": source_action,
        }

    def _emit_slot_relation_events(
        self,
        workflow: WorkflowV2,
        relation: WorkflowAssetRelationV2,
        slot: WorkflowSlotV2,
        *,
        version_id: str,
        event_type: str,
    ) -> None:
        payload = {
            "relation_id": relation.relation_id,
            "relation_type": relation.relation_type,
            "asset_id": relation.source_asset_id,
            "version_id": version_id,
            "slot_id": slot.slot_id,
            "source_action": relation.metadata.get("source_action"),
        }
        self._append_event(
            workflow.workflow_id,
            event_type,
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload=payload,
        )
        self._append_event(
            workflow.workflow_id,
            "asset_relation_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            asset_id=relation.source_asset_id,
            version_id=version_id,
            payload=payload,
        )

    def _slot_is_targetable(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        mode: str = "fill_missing_required_slots",
        include_failed: bool = True,
    ) -> bool:
        return self._slot_scheduler.slot_is_targetable(
            workflow,
            slot,
            mode=mode,
            include_failed=include_failed,
        )

    def _refresh_workflow_state(self, workflow: WorkflowV2) -> None:
        self._slot_scheduler.refresh_workflow_state(workflow)

    def _item_status(self, item: WorkflowItemV2) -> Any:
        return self._slot_scheduler.item_status(item)

    def _node_status(self, workflow: WorkflowV2, node: WorkflowNodeV2) -> Any:
        return self._slot_scheduler.node_status(workflow, node)

    def _dependencies_satisfied(self, workflow: WorkflowV2, slot: WorkflowSlotV2) -> bool:
        return self._slot_scheduler.dependencies_satisfied(workflow, slot)

    def _slot_has_valid_selected_asset(self, slot: WorkflowSlotV2) -> bool:
        return self._slot_scheduler.slot_has_valid_selected_asset(slot)

    def _visual_reference_bundles_complete(self, workflow: WorkflowV2) -> bool:
        return self._slot_scheduler.visual_reference_bundles_complete(workflow)

    def _final_inputs_ready(self, workflow: WorkflowV2) -> bool:
        return self._slot_scheduler.final_inputs_ready(workflow)

    def _final_composition_dependency_error_code(self, workflow: WorkflowV2) -> str:
        return self._slot_scheduler.final_composition_dependency_error_code(workflow)

    def _node_bundle_complete(
        self,
        workflow: WorkflowV2,
        node_id: str,
        required_slot_types: tuple[str, ...],
    ) -> bool:
        return self._slot_scheduler.node_bundle_complete(
            workflow,
            node_id,
            required_slot_types,
        )

    def _ensure_storyboard_shots(self, workflow: WorkflowV2) -> tuple[list[str], list[str]]:
        before_items = set(_item_ids(workflow))
        before_slots = set(_slot_ids(workflow))
        self._storyboard_director.synchronize_structure(workflow)
        created_item_ids = [
            item_id for item_id in _item_ids(workflow) if item_id not in before_items
        ]
        created_slot_ids = [
            slot_id for slot_id in _slot_ids(workflow) if slot_id not in before_slots
        ]
        if created_item_ids or created_slot_ids:
            self._append_event(
                workflow.workflow_id,
                "storyboard_unlocked",
                node_id="storyboard",
                payload={"created_item_ids": created_item_ids},
            )
            self._append_event(
                workflow.workflow_id,
                "storyboard_shots_created",
                node_id="storyboard",
                payload={
                    "created_item_ids": created_item_ids,
                    "created_slot_ids": created_slot_ids,
                },
            )
        return created_item_ids, created_slot_ids

    def _ensure_final_composition_item(self, workflow: WorkflowV2) -> tuple[list[str], list[str]]:
        before_items = set(_item_ids(workflow))
        before_slots = set(_slot_ids(workflow))
        self._final_composition.ensure_final_composition_item(
            workflow,
            selected_shot_video_slots=self._selected_shot_video_slots(workflow),
            bgm_slot=self._selected_bgm_slot(workflow),
        )
        created_item_ids = [
            item_id for item_id in _item_ids(workflow) if item_id not in before_items
        ]
        created_slot_ids = [
            slot_id for slot_id in _slot_ids(workflow) if slot_id not in before_slots
        ]
        if created_item_ids or created_slot_ids:
            self._append_event(
                workflow.workflow_id,
                "final_composition_unlocked",
                node_id="final-composition",
                payload={"created_item_ids": created_item_ids},
            )
            self._append_event(
                workflow.workflow_id,
                "final_composition_timeline_created",
                node_id="final-composition",
                item_id=created_item_ids[0] if created_item_ids else None,
                payload={
                    "created_item_ids": created_item_ids,
                    "created_slot_ids": created_slot_ids,
                },
            )
        return created_item_ids, created_slot_ids

    def _visual_reference_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        return self._slot_scheduler.visual_reference_asset_ids(workflow)

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

    def _dependency_asset_ids(self, workflow: WorkflowV2, slot: WorkflowSlotV2) -> list[str]:
        return self._slot_scheduler.dependency_asset_ids(workflow, slot)

    def _selected_shot_video_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        return self._slot_scheduler.selected_shot_video_asset_ids(workflow)

    def _selected_shot_video_slots(
        self, workflow: WorkflowV2
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        return self._slot_scheduler.selected_shot_video_slots(workflow)

    def _selected_bgm_asset_id(self, workflow: WorkflowV2) -> str | None:
        return self._slot_scheduler.selected_bgm_asset_id(workflow)

    def _selected_bgm_slot(self, workflow: WorkflowV2) -> WorkflowSlotV2 | None:
        return self._slot_scheduler.selected_bgm_slot(workflow)

    def _final_composition_item(self, workflow: WorkflowV2) -> WorkflowItemV2 | None:
        return self._slot_scheduler.final_composition_item(workflow)

    def _slots_for_node(self, workflow: WorkflowV2, node_id: str) -> list[WorkflowSlotV2]:
        return self._slot_scheduler.slots_for_node(workflow, node_id)

    def _blocked_slot_ids(self, workflow: WorkflowV2) -> list[str]:
        return self._slot_scheduler.blocked_slot_ids(workflow)

    def _find_item(
        self,
        workflow: WorkflowV2,
        node_id: str,
        item_id_or_shot_id: str,
    ) -> WorkflowItemV2 | None:
        node = _node_by_id(workflow, node_id)
        if node is None:
            return None
        for item in _active_items(node):
            if item.item_id == item_id_or_shot_id or item.shot_id == item_id_or_shot_id:
                return item
        return None

    def _find_slot(self, workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
        for node in workflow.nodes:
            for item in _active_items(node):
                for slot in item.slots:
                    if slot.slot_id == slot_id:
                        return slot
        return None

    def _find_slot_by_type(
        self,
        workflow: WorkflowV2,
        slot_type: str,
    ) -> WorkflowSlotV2 | None:
        for node in workflow.nodes:
            for item in _active_items(node):
                slot = _slot_by_type(item, slot_type)
                if slot is not None:
                    return slot
        return None

    def _find_item_any_node(
        self,
        workflow: WorkflowV2,
        item_id: str,
    ) -> WorkflowItemV2 | None:
        for node in workflow.nodes:
            for item in _active_items(node):
                if item.item_id == item_id:
                    return item
        return None

    def _resolve_chat_target(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2ChatTargetRequest,
    ) -> tuple[V2GenerationTarget, WorkflowItemV2 | None, WorkflowSlotV2 | None]:
        target = request.target
        if target.target_type == "node":
            if not target.node_id:
                raise WorkflowV2Error("target_not_found")
            node = _node_by_id(workflow, target.node_id)
            if node is None:
                raise WorkflowV2Error("target_not_found")
            item = _active_items(node)[0] if _active_items(node) else None
            return (
                V2GenerationTarget(
                    workflow_id=workflow.workflow_id,
                    target_type="node",
                    node_id=node.node_id,
                    node_type=node.node_type,
                    item_id=item.item_id if item else None,
                    item_type=item.item_type if item else None,
                    media_type=_first_slot_media_type(item),
                    is_free_generation=node.node_type == "free-generation",
                ),
                item,
                None,
            )
        if target.target_type == "item":
            if not target.item_id:
                raise WorkflowV2Error("target_not_found")
            item = (
                self._find_item(workflow, target.node_id, target.item_id)
                if target.node_id
                else self._find_item_any_node(workflow, target.item_id)
            )
            if item is None:
                raise WorkflowV2Error("item_not_found")
            node = _node_by_id(workflow, item.node_id)
            return (
                V2GenerationTarget(
                    workflow_id=workflow.workflow_id,
                    target_type="item",
                    node_id=item.node_id,
                    node_type=node.node_type if node else item.node_id,
                    item_id=item.item_id,
                    item_type=item.item_type,
                    media_type=_first_slot_media_type(item),
                    is_free_generation=item.item_type == "free",
                ),
                item,
                None,
            )
        if target.target_type == "slot":
            if not target.slot_id:
                raise WorkflowV2Error("target_not_found")
            slot = self._find_slot(workflow, target.slot_id)
            if slot is None:
                raise WorkflowV2Error("slot_not_found")
            item = self._find_item(workflow, slot.node_id, slot.item_id)
            if item is None:
                raise WorkflowV2Error("item_not_found")
            node = _node_by_id(workflow, slot.node_id)
            return (
                V2GenerationTarget(
                    workflow_id=workflow.workflow_id,
                    target_type="slot",
                    node_id=slot.node_id,
                    node_type=node.node_type if node else slot.node_id,
                    item_id=item.item_id,
                    item_type=item.item_type,
                    slot_id=slot.slot_id,
                    slot_type=slot.slot_type,
                    media_type=slot.media_type,
                    is_free_generation=item.item_type == "free",
                ),
                item,
                slot,
            )
        if target.target_type == "asset":
            if not target.asset_id:
                raise WorkflowV2Error("target_not_found")
            if not self._asset_store.asset_exists(target.asset_id):
                raise WorkflowV2Error("asset_not_found")
            relation = self._owner_relation_for_asset(workflow.workflow_id, target.asset_id)
            if relation is None:
                raise WorkflowV2Error("agent_route_not_found")
            return self._target_from_asset_relation(workflow, target.asset_id, relation)
        raise WorkflowV2Error("target_not_found")

    def _owner_relation_for_asset(
        self,
        workflow_id: str,
        asset_id: str,
    ) -> WorkflowAssetRelationV2 | None:
        absorbed_relations = self._asset_store.list_relations(
            target_workflow_id=workflow_id,
            source_asset_id=asset_id,
            relation_type="absorbed_into",
        )
        for relation_type in (
            "selected_for_slot",
            "working_version_for_slot",
            "history_version_for_slot",
            "absorbed_into",
            "reference_for_slot",
            "reference_for_item",
            "available_for_composition",
            "selected_for_timeline",
        ):
            relations = self._asset_store.list_relations(
                target_workflow_id=workflow_id,
                source_asset_id=asset_id,
                relation_type=relation_type,  # type: ignore[arg-type]
            )
            for relation in relations:
                if (
                    relation.target_node_id
                    and relation.target_node_id.startswith("free-generation")
                    and absorbed_relations
                ):
                    continue
                return relation
        return None

    def _target_from_asset_relation(
        self,
        workflow: WorkflowV2,
        asset_id: str,
        relation: WorkflowAssetRelationV2,
    ) -> tuple[V2GenerationTarget, WorkflowItemV2 | None, WorkflowSlotV2 | None]:
        slot = (
            self._find_slot(workflow, relation.target_slot_id) if relation.target_slot_id else None
        )
        item = (
            self._find_item(workflow, slot.node_id, slot.item_id)
            if slot
            else (
                self._find_item_any_node(workflow, relation.target_item_id)
                if relation.target_item_id
                else None
            )
        )
        node_id = slot.node_id if slot else (item.node_id if item else relation.target_node_id)
        if node_id is None:
            raise WorkflowV2Error("agent_route_not_found")
        node = _node_by_id(workflow, node_id)
        media_type = slot.media_type if slot else _first_slot_media_type(item)
        return (
            V2GenerationTarget(
                workflow_id=workflow.workflow_id,
                target_type="asset",
                node_id=node_id,
                node_type=node.node_type if node else node_id,
                item_id=item.item_id if item else relation.target_item_id,
                item_type=item.item_type if item else None,
                slot_id=slot.slot_id if slot else relation.target_slot_id,
                slot_type=slot.slot_type if slot else None,
                asset_id=asset_id,
                media_type=media_type,
                is_free_generation=node_id.startswith("free-generation"),
            ),
            item,
            slot,
        )

    def _apply_chat_prompt_update(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2ChatTargetRequest,
        *,
        item: WorkflowItemV2 | None,
        slot: WorkflowSlotV2 | None,
        materialized_prompt: Any | None = None,
    ) -> tuple[str | None, list[str]]:
        if slot is not None and request.prompt_scope in {"auto", "slot"}:
            prompt = (
                request.slot_prompt
                or getattr(materialized_prompt, "provider_prompt", None)
                or request.instruction
            )
            slot.slot_prompt = prompt
            slot.user_prompt = prompt
            if request.negative_prompt is not None:
                slot.negative_prompt = request.negative_prompt
            if request.dialogue_prompt is not None:
                slot.dialogue_prompt = request.dialogue_prompt
            if request.audio_description_prompt is not None:
                slot.audio_description_prompt = request.audio_description_prompt
            if request.voice_style_prompt is not None:
                slot.voice_style_prompt = request.voice_style_prompt
            if request.negative_constraints is not None:
                slot.negative_constraints = request.negative_constraints
            slot.prompt_source = "user"
            slot.manual_prompt_dirty = True
            affected = [slot.slot_id]
            self._mark_chat_slots_stale(workflow, affected, request.instruction)
            return "slot", affected

        if item is not None:
            prompt = (
                request.item_prompt
                or getattr(materialized_prompt, "summary_prompt", None)
                or getattr(materialized_prompt, "provider_prompt", None)
                or request.instruction
            )
            if item.item_type == "shot":
                item.shot_summary_prompt = prompt
            else:
                item.item_prompt = prompt
            item.user_prompt = prompt
            item.prompt_source = "user"
            item.manual_prompt_dirty = True
            affected = [slot.slot_id for slot in item.slots if slot.required]
            self._mark_chat_slots_stale(workflow, affected, request.instruction)
            return "item", affected

        node = _node_by_id(workflow, request.target.node_id or "")
        if node is not None:
            node.metadata["chat_prompt_instruction"] = request.instruction
            return "node", []
        return None, []

    def _mark_chat_slots_stale(
        self,
        workflow: WorkflowV2,
        slot_ids: list[str],
        instruction: str,
    ) -> None:
        for slot_id in slot_ids:
            slot = self._find_slot(workflow, slot_id)
            if slot is None:
                continue
            slot.metadata["stale"] = True
            slot.metadata["prompt_revision_instruction"] = instruction
            slot.status = "ready" if self._dependencies_satisfied(workflow, slot) else "blocked"
            self._append_event(
                workflow.workflow_id,
                "slot_marked_stale",
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                payload={"status": slot.status},
            )

    def _version_id_for_asset(self, asset_id: str | None) -> str | None:
        if not asset_id:
            return None
        metadata_root = self._data_dir / "assets" / "metadata" / asset_id
        if not metadata_root.exists():
            return None
        first = next(iter(sorted(metadata_root.glob("*.json"))), None)
        return first.stem if first else None

    def add_downstream_outdated_hint_from_slot(
        self,
        workflow: WorkflowV2,
        *,
        source_slot_id: str,
        old_asset_id: str | None,
        new_asset_id: str,
    ) -> list[WorkflowSlotV2]:
        if not old_asset_id or old_asset_id == new_asset_id:
            return []
        source_slot = self._find_slot(workflow, source_slot_id)
        if source_slot is None:
            return []
        hint = {
            "source_slot_id": source_slot_id,
            "old_asset_id": old_asset_id,
            "new_asset_id": new_asset_id,
            "reason": "upstream_selected_version_changed",
            "created_at": utc_now().isoformat(),
        }
        affected_slots: list[WorkflowSlotV2] = []
        for slot in self._downstream_outdated_slots(workflow, source_slot):
            if self._add_outdated_hint_to_slot(workflow, slot, hint):
                affected_slots.append(slot)
        self._emit_outdated_hint_scope_events(workflow, affected_slots, hint)
        return affected_slots

    def _mark_consumers_outdated(
        self,
        workflow: WorkflowV2,
        *,
        source_slot: WorkflowSlotV2,
        old_asset_id: str | None,
        new_asset_id: str,
    ) -> None:
        self.add_downstream_outdated_hint_from_slot(
            workflow,
            source_slot_id=source_slot.slot_id,
            old_asset_id=old_asset_id,
            new_asset_id=new_asset_id,
        )

    def _downstream_outdated_slots(
        self,
        workflow: WorkflowV2,
        source_slot: WorkflowSlotV2,
    ) -> list[WorkflowSlotV2]:
        targets: list[WorkflowSlotV2] = []
        source_item = self._find_item(workflow, source_slot.node_id, source_slot.item_id)
        if source_slot.slot_type in {
            "product_main_image",
            "character_main_image",
            "scene_main_image",
        }:
            companion_slot_type = {
                "product_main_image": "product_multi_view_grid",
                "character_main_image": "character_three_view",
                "scene_main_image": "scene_multi_view_grid",
            }[source_slot.slot_type]
            if source_item is not None:
                companion = _slot_by_type(source_item, companion_slot_type)
                if companion is not None:
                    targets.append(companion)
            for shot in self._storyboard_items(workflow):
                targets.extend(
                    slot for slot in shot.slots if slot.slot_type.startswith("shot_cell_")
                )
                if self._shot_has_selected_cells(shot):
                    video_slot = _slot_by_type(shot, "shot_video_segment")
                    if video_slot is not None:
                        targets.append(video_slot)
        elif source_slot.slot_type in {
            "product_multi_view_grid",
            "character_three_view",
            "scene_multi_view_grid",
        }:
            for shot in self._storyboard_items(workflow):
                targets.extend(
                    slot for slot in shot.slots if slot.slot_type.startswith("shot_cell_")
                )
                if self._shot_has_selected_cells(shot):
                    video_slot = _slot_by_type(shot, "shot_video_segment")
                    if video_slot is not None:
                        targets.append(video_slot)
        elif source_slot.slot_type.startswith("shot_cell_"):
            if source_item is not None:
                video_slot = _slot_by_type(source_item, "shot_video_segment")
                if video_slot is not None:
                    targets.append(video_slot)
        elif source_slot.slot_type in {"shot_video_segment", "bgm_audio"}:
            final_slot = self._find_slot_by_type(workflow, "final_video")
            if final_slot is not None:
                targets.append(final_slot)
        deduped: list[WorkflowSlotV2] = []
        seen_slot_ids: set[str] = set()
        for slot in targets:
            if slot.slot_id == source_slot.slot_id or slot.slot_id in seen_slot_ids:
                continue
            seen_slot_ids.add(slot.slot_id)
            deduped.append(slot)
        return deduped

    def _storyboard_items(self, workflow: WorkflowV2) -> list[WorkflowItemV2]:
        return self._slot_scheduler.storyboard_items(workflow)

    def _shot_has_selected_cells(self, item: WorkflowItemV2) -> bool:
        return any(
            slot.selected_asset_id for slot in item.slots if slot.slot_type.startswith("shot_cell_")
        )

    def _add_storyboard_summary_outdated_hints(
        self,
        workflow: WorkflowV2,
        shot: WorkflowItemV2,
    ) -> None:
        affected_slots: list[WorkflowSlotV2] = []
        created_at = utc_now().isoformat()
        for slot in shot.slots:
            if not slot.selected_asset_id:
                continue
            hint = {
                "source_slot_id": f"{shot.item_id}:shot_summary_prompt",
                "old_asset_id": slot.selected_asset_id,
                "new_asset_id": slot.selected_asset_id,
                "reason": "storyboard_summary_refined",
                "created_at": created_at,
            }
            if self._add_outdated_hint_to_slot(workflow, slot, hint):
                affected_slots.append(slot)
        if affected_slots:
            self._emit_outdated_hint_scope_events(
                workflow,
                affected_slots,
                {
                    "source_slot_id": f"{shot.item_id}:shot_summary_prompt",
                    "old_asset_id": "",
                    "new_asset_id": "",
                    "reason": "storyboard_summary_refined",
                    "created_at": created_at,
                },
            )

    def _add_outdated_hint_to_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        hint: dict[str, Any],
    ) -> bool:
        sources = [
            dict(source)
            for source in slot.metadata.get("outdated_sources", [])
            if isinstance(source, dict)
        ]
        duplicate = any(
            source.get("source_slot_id") == hint.get("source_slot_id")
            and source.get("old_asset_id") == hint.get("old_asset_id")
            and source.get("new_asset_id") == hint.get("new_asset_id")
            and source.get("reason") == hint.get("reason")
            for source in sources
        )
        if duplicate:
            return False
        sources.append(dict(hint))
        slot.metadata["outdated_hint"] = True
        slot.metadata["outdated_sources"] = sources
        slot.metadata["reference_outdated"] = True
        slot.metadata["linked_source_has_new_version"] = True
        slot.metadata["outdated_source_asset_id"] = hint.get("old_asset_id")
        slot.metadata["latest_source_asset_id"] = hint.get("new_asset_id")
        slot.metadata["outdated_at"] = hint.get("created_at")
        self._append_event(
            workflow.workflow_id,
            "slot_outdated_hint_added",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload=dict(hint),
        )
        self._append_event(
            workflow.workflow_id,
            "weak_link_hint_updated",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={
                "outdated_source_asset_id": hint.get("old_asset_id"),
                "latest_source_asset_id": hint.get("new_asset_id"),
            },
        )
        return True

    def _emit_outdated_hint_scope_events(
        self,
        workflow: WorkflowV2,
        slots: list[WorkflowSlotV2],
        hint: dict[str, Any],
    ) -> None:
        seen_items: set[tuple[str, str]] = set()
        seen_nodes: set[str] = set()
        for slot in slots:
            item_key = (slot.node_id, slot.item_id)
            if item_key not in seen_items:
                seen_items.add(item_key)
                self._append_event(
                    workflow.workflow_id,
                    "item_outdated_hint_added",
                    node_id=slot.node_id,
                    item_id=slot.item_id,
                    payload=dict(hint),
                )
            if slot.node_id not in seen_nodes:
                seen_nodes.add(slot.node_id)
                self._append_event(
                    workflow.workflow_id,
                    "node_outdated_hint_added",
                    node_id=slot.node_id,
                    payload=dict(hint),
                )

    def _clear_outdated_hints_for_slot(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
    ) -> None:
        existing_sources = [
            source
            for source in slot.metadata.get("outdated_sources", [])
            if isinstance(source, dict)
        ]
        had_hint = bool(slot.metadata.get("outdated_hint") or existing_sources)
        if not had_hint:
            return
        for key in (
            "outdated_hint",
            "outdated_sources",
            "reference_outdated",
            "linked_source_has_new_version",
            "outdated_source_asset_id",
            "latest_source_asset_id",
            "outdated_at",
        ):
            slot.metadata.pop(key, None)
        self._append_event(
            workflow.workflow_id,
            "slot_outdated_hint_cleared",
            node_id=slot.node_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            payload={"cleared_sources": existing_sources},
        )

    def _remove_relation_from_workflow(
        self,
        workflow: WorkflowV2,
        relation: WorkflowAssetRelationV2,
    ) -> None:
        if relation.target_slot_id:
            slot = self._find_slot(workflow, relation.target_slot_id)
            if slot:
                _remove_value(slot.metadata, "reference_relation_ids", relation.relation_id)
                slot.explicit_reference_ids = [
                    asset_id
                    for asset_id in slot.explicit_reference_ids
                    if asset_id != relation.source_asset_id
                ]
        if relation.target_item_id:
            item = self._find_item_any_node(workflow, relation.target_item_id)
            if item:
                _remove_value(item.metadata, "reference_relation_ids", relation.relation_id)
                _remove_value(
                    item.metadata,
                    "explicit_reference_asset_ids",
                    relation.source_asset_id,
                )

    def _record_absorbed_reference(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2FreeNodeAbsorbRequest,
        relations: list[WorkflowAssetRelationV2],
    ) -> None:
        relation_ids = [relation.relation_id for relation in relations]
        if request.target_slot_id:
            slot = self._find_slot(workflow, request.target_slot_id)
            if slot:
                for relation_id in relation_ids:
                    _append_unique(slot.metadata, "reference_relation_ids", relation_id)
                slot.explicit_reference_ids = list(
                    dict.fromkeys([*slot.explicit_reference_ids, request.asset_id])
                )
        if request.target_item_id:
            item = self._find_item_any_node(workflow, request.target_item_id)
            if item:
                for relation_id in relation_ids:
                    _append_unique(item.metadata, "reference_relation_ids", relation_id)
                _append_unique(item.metadata, "explicit_reference_asset_ids", request.asset_id)

    def _record_available_composition_asset(
        self,
        workflow: WorkflowV2,
        request: WorkflowV2FreeNodeAbsorbRequest,
    ) -> None:
        item = (
            self._find_item_any_node(workflow, request.target_item_id)
            if request.target_item_id
            else None
        )
        if item is None:
            node = _node_by_id(workflow, request.target_node_id)
            item = _active_items(node)[0] if node and _active_items(node) else None
        if item is None:
            raise WorkflowV2Error("item_not_found")
        _append_unique(item.metadata, "available_composition_asset_ids", request.asset_id)
        item.metadata.setdefault("timeline_clips", [])

    @contextmanager
    def _defer_events(self) -> Iterator[list[tuple[str, str, dict[str, Any]]]]:
        parent_buffer = getattr(self._event_context, "buffer", None)
        if parent_buffer is not None:
            yield parent_buffer
            return
        buffer: list[tuple[str, str, dict[str, Any]]] = []
        self._event_context.buffer = buffer
        try:
            yield buffer
        finally:
            self._event_context.buffer = None

    def _flush_deferred_events(self, events: list[tuple[str, str, dict[str, Any]]]) -> None:
        for workflow_id, event_type, event_kwargs in events:
            self._runtime_events.append_event(workflow_id, event_type, **event_kwargs)

    def _append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        asset_id: str | None = None,
        version_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowV2Event:
        resolved_execution_id = execution_id or getattr(
            self._execution_context, "execution_id", None
        )
        if resolved_execution_id and (payload is None or "execution_id" not in payload):
            payload = {**(payload or {}), "execution_id": resolved_execution_id}
        event_kwargs = {
            "execution_id": resolved_execution_id,
            "node_id": node_id,
            "item_id": item_id,
            "slot_id": slot_id,
            "asset_id": asset_id,
            "version_id": version_id,
            "payload": payload,
        }
        deferred_events = getattr(self._event_context, "buffer", None)
        if deferred_events is not None:
            deferred_events.append((workflow_id, event_type, event_kwargs))
            return WorkflowV2Event(
                seq=0,
                event_type=event_type,
                workflow_id=workflow_id,
                created_at=utc_now().isoformat(),
                **event_kwargs,
            )
        return self._runtime_events.append_event(
            workflow_id,
            event_type,
            **event_kwargs,
        )

    def _load_events(self, workflow_id: str) -> list[WorkflowV2Event]:
        return self._runtime_events.load_events(workflow_id)

    def _events_cursor(self, workflow_id: str) -> int:
        return self._runtime_events.events_cursor(workflow_id)

    def _write_execution_record(
        self,
        workflow_id: str,
        *,
        mode: str,
        status: str,
        completed_slot_ids: list[str] | None = None,
        failed_slot_ids: list[str] | None = None,
        waiting_slot_ids: list[str] | None = None,
        running_slot_ids: list[str] | None = None,
        slot_transitions: list[dict[str, Any]] | None = None,
        source_execution_id: str | None = None,
    ) -> None:
        self._execution_service.write_record(
            workflow_id,
            mode=mode,
            status=status,
            completed_slot_ids=completed_slot_ids,
            failed_slot_ids=failed_slot_ids,
            waiting_slot_ids=waiting_slot_ids,
            running_slot_ids=running_slot_ids,
            slot_transitions=slot_transitions,
            events_cursor=self._events_cursor(workflow_id),
            source_execution_id=source_execution_id,
        )


def _slot_runtime_from_transition(
    slot: WorkflowSlotV2,
    status: str,
    *,
    execution_id: str,
    updated_at: str,
    last_event_seq: int,
    last_event_type: str,
    payload: dict[str, Any] | None = None,
    asset_id: str | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    runtime: dict[str, Any] = {
        "slot_id": slot.slot_id,
        "node_id": slot.node_id,
        "item_id": slot.item_id,
        "slot_type": slot.slot_type,
        "media_type": slot.media_type,
        "status": status,
        "runtime_status": status,
        "selected_asset_id": slot.selected_asset_id,
        "selected_version_id": slot.selected_version_id,
        "current_working_asset_id": slot.current_working_asset_id,
        "current_working_version_id": slot.current_working_version_id,
        "execution_id": execution_id,
        "updated_at": updated_at,
        "last_event_seq": last_event_seq,
        "last_event_type": last_event_type,
    }
    if slot.selected_asset_id and version_id and slot.selected_asset_id == asset_id:
        runtime["selected_version_id"] = version_id
    if status == "waiting":
        provider_task_id = payload.get("provider_task_id") or slot.metadata.get("provider_task_id")
        remote_task_id = payload.get("remote_task_id") or slot.metadata.get("remote_task_id")
        waiting_reason = payload.get("waiting_reason") or slot.metadata.get("waiting_reason")
        if provider_task_id:
            runtime["provider_task_id"] = provider_task_id
        if remote_task_id:
            runtime["remote_task_id"] = remote_task_id
        if waiting_reason:
            runtime["waiting_reason"] = waiting_reason
    if status == "failed":
        error = slot.metadata.get("error")
        if not isinstance(error, dict):
            error_code = payload.get("error_code") or payload.get("code")
            error_message = (
                payload.get("error_message") or payload.get("message") or payload.get("error")
            )
            if error_code or error_message:
                error = {
                    "code": str(error_code or "provider_generation_failed"),
                    "message": str(error_message or error_code or "Provider generation failed."),
                }
        if isinstance(error, dict):
            runtime["error"] = dict(error)
            for key in ("stage", "shot_id", "slot_id", "violations"):
                if payload.get(key) is not None:
                    runtime["error"][key] = payload[key]
        if slot.metadata.get("recoverable") is not None:
            runtime["recoverable"] = bool(slot.metadata.get("recoverable"))
    return runtime


def _resolve_chat_action_mode(request: WorkflowV2ChatActionRequest) -> str:
    if request.action_mode != "auto":
        return request.action_mode
    message = request.message.lower()
    if any(token in message for token in ("discard", "cancel", "remove working")):
        return "discard_working"
    if any(token in message for token in ("use this", "select", "set as current")):
        return "select_version"
    if any(token in message for token in ("generate", "regenerate", "new version")):
        return "revise_and_generate"
    if any(token in message for token in ("make", "change", "revise", "update")):
        return "revise_prompt"
    return "clarification_required"


def _target_from_locator(
    locator: str,
    fallback: WorkflowV2ChatActionTarget,
) -> WorkflowV2ChatActionTarget:
    if ":" not in locator:
        raise WorkflowV2Error("invalid_locator")
    kind, value = locator.split(":", 1)
    if kind == "slot" and value:
        return fallback.model_copy(update={"target_type": "slot", "slot_id": value})
    if kind == "free_node" and value:
        return fallback.model_copy(update={"target_type": "free_node", "node_id": value})
    if kind == "asset" and value:
        asset_id, _, version_id = value.partition("@")
        if not asset_id:
            raise WorkflowV2Error("invalid_locator")
        return fallback.model_copy(
            update={
                "target_type": "asset",
                "asset_id": asset_id,
                "version_id": version_id or fallback.version_id,
            }
        )
    raise WorkflowV2Error("invalid_locator")


def _planner_warnings(expert_brief_plan: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for warning in getattr(expert_brief_plan, "warnings", []) or []:
        if not isinstance(warning, dict):
            continue
        code = warning.get("code")
        if code not in {
            "expert_brief_planner_fallback_used",
            "specialist_asset_prompt_repair_used",
            "specialist_asset_prompt_fallback_used",
        }:
            continue
        warnings.append(
            {
                "code": code,
                "message": warning.get("message") or "Deterministic expert briefs were used.",
                "stage": warning.get("stage"),
                "failed_stage": warning.get("failed_stage"),
                "original_error_code": warning.get("original_error_code"),
            }
        )
    return warnings


def _normalized_v2_request_view(
    request: WorkflowV2PlanFromPromptRequest,
    *,
    planning_seed: V2FrontDeskPlanningSeed | None = None,
) -> WorkflowV2NormalizedPlanningRequestView:
    return WorkflowV2NormalizedPlanningRequestView(
        prompt=request.prompt,
        product_name=request.product_name,
        visual_style=request.visual_style,
        duration_seconds=request.duration_seconds,
        requested_shot_count=request.requested_shot_count,
        aspect_ratio=request.aspect_ratio,
        output_resolution=request.output_resolution,
        audio_mode=request.audio_mode,
        reference_mode=request.reference_mode,
        input_asset_locators=list(request.input_asset_locators),
        library_entity_ids=list(request.library_entity_ids),
        metadata=sanitize_context_for_llm_text(request.metadata),
        v2_planning_seed=planning_seed,
    )


def _provider_call_summaries(calls: list[dict[str, Any]]) -> list[V2ProviderCallSummary]:
    return [_provider_call_summary(call) for call in calls]


def _provider_call_summary(call: dict[str, Any]) -> V2ProviderCallSummary:
    route = call.get("agent_route") if isinstance(call.get("agent_route"), dict) else {}
    return V2ProviderCallSummary(
        node_id=_optional_str(call.get("node_id")),
        item_id=_optional_str(call.get("item_id")),
        slot_id=_optional_str(call.get("slot_id")),
        slot_type=_optional_str(call.get("slot_type")),
        status=_optional_str(call.get("status")),
        provider=_optional_str(call.get("provider")),
        provider_model=_optional_str(call.get("provider_model")),
        agent_route={
            key: value
            for key, value in sanitize_context_for_llm_text(route).items()
            if key
            in {
                "specialist",
                "owner_node_id",
                "owner_item_id",
                "owner_slot_id",
                "generation_mode",
                "materializer_version",
            }
        },
        materializer_mode=_optional_str(call.get("materializer_mode")),
        asset_id=_optional_str(call.get("asset_id")),
        version_id=_optional_str(call.get("version_id")),
        provider_task_id=_optional_str(call.get("provider_task_id")),
        remote_task_id=_optional_str(call.get("remote_task_id")),
        error_code=_optional_str(call.get("error_code")),
        error_message=_optional_str(call.get("error_message")),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _intent_clarification_suggested_actions(details: dict[str, Any]) -> list[dict[str, Any]]:
    reason = str(details.get("reason") or "")
    if details.get("missing") == ["product_name"]:
        return [
            {
                "action": "provide_product_name",
                "message": "Provide the advertised product or brand before creating the workflow.",
            }
        ]
    if reason == "storyboard_shot_duration_not_supported":
        suggested_min = details.get("suggested_min_shot_count")
        requested_shot_count = details.get("requested_shot_count")
        requested_duration = details.get("requested_duration_seconds")
        max_shot_duration = details.get("max_shot_duration_seconds")
        reduce_duration = (
            requested_shot_count * max_shot_duration
            if isinstance(requested_shot_count, int) and isinstance(max_shot_duration, int)
            else None
        )
        return [
            {
                "action": "use_suggested_shot_count",
                "shot_count": suggested_min,
                "label": f"Use {suggested_min} shots" if suggested_min else "Use more shots",
            },
            {
                "action": "reduce_duration",
                "duration_seconds": reduce_duration,
                "label": f"Make it {reduce_duration} seconds"
                if reduce_duration
                else f"Reduce from {requested_duration} seconds",
            },
        ]
    if reason in {"storyboard_shot_count_not_supported", "video_duration_not_supported"}:
        return [
            {
                "action": "adjust_storyboard_duration",
                "message": "Use a supported duration and storyboard shot count.",
            }
        ]
    if reason == "scene_constraints_conflict":
        return [
            {
                "action": "clarify_scene_count",
                "message": "Clarify how many distinct scenes should be created.",
            }
        ]
    return [
        {
            "action": "clarify_intent",
            "message": "Clarify the workflow creation requirements.",
        }
    ]


def _front_desk_clarification_response(
    front_desk: FrontDeskChatResponse,
    clarification: WorkflowV2PlanningClarificationResponse,
) -> FrontDeskChatResponse:
    missing = clarification.details.get("missing")
    missing_fields = (
        [field for field in missing if isinstance(field, str)] if isinstance(missing, list) else []
    )
    return FrontDeskChatResponse(
        intent="needs_clarification",
        reply=clarification.message,
        missing_fields=missing_fields,
        conversation_mode="director_discussion",
        v2_planning_seed=front_desk.v2_planning_seed,
    )


def _v2_request_from_chat(
    chat_request: FrontDeskChatRequest,
    ad_request: AdWorkflowGenerateRequest,
) -> WorkflowV2PlanFromPromptRequest:
    selected_assets = _dedupe_model_list(
        [*ad_request.selected_assets, *chat_request.selected_assets],
        "asset_id",
    )
    asset_references = _dedupe_model_list(
        [*ad_request.asset_references, *chat_request.asset_references],
        "asset_id",
        fallback_key="entity_id",
    )
    library_entity_ids = list(
        dict.fromkeys([*ad_request.library_entity_ids, *chat_request.library_entity_ids])
    )
    return WorkflowV2PlanFromPromptRequest(
        prompt=chat_request.message,
        product_name=ad_request.product_name,
        visual_style=ad_request.visual_style,
        duration_seconds=ad_request.duration_seconds,
        aspect_ratio=ad_request.aspect_ratio or "16:9",
        output_resolution=ad_request.output_resolution or "720p",
        audio_mode="none"
        if ad_request.skip_audio_agents
        else (chat_request.audio_mode or ad_request.audio_mode),
        selected_assets=selected_assets,
        asset_references=asset_references,
        input_asset_locators=list(chat_request.input_asset_locators),
        library_entity_ids=library_entity_ids,
        reference_mode="best_effort"
        if "best_effort" in {ad_request.reference_mode, chat_request.reference_mode}
        else "strict",
        metadata={
            **chat_request.metadata,
            "source": "v2_plan_from_chat",
            "front_desk_ad_request": ad_request.model_dump(mode="json"),
        },
    )


def _dedupe_model_list(items: list[Any], key: str, fallback_key: str | None = None) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for item in items:
        payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        value = str(payload.get(key) or payload.get(fallback_key or "") or "")
        if value and value in seen:
            continue
        if value:
            seen.add(value)
        deduped.append(item)
    return deduped


def _parse_input_asset_locator(locator: str) -> tuple[str, str]:
    if not locator.startswith("asset:"):
        raise WorkflowV2Error(
            "v2_data_boundary_violation",
            f"V2 input asset locator must use asset: syntax, got {locator!r}.",
        )
    value = locator.removeprefix("asset:")
    if "/" in value or "\\" in value or ".." in value:
        raise WorkflowV2Error(
            "v2_data_boundary_violation",
            f"V2 input asset locator rejected legacy path syntax: {locator!r}.",
        )
    asset_id, separator, version_id = value.partition("@")
    if not asset_id or separator != "@" or not version_id:
        raise WorkflowV2Error("asset_not_found")
    return asset_id, version_id


def _input_asset_descriptor(record: WorkflowAssetVersionV2) -> dict[str, Any]:
    descriptor = {
        "asset_id": record.asset_id,
        "version_id": record.version_id,
        "media_type": record.media_type,
        "semantic_type": record.semantic_type,
        "display_name": record.metadata.get("display_name"),
        "tags": list(record.metadata.get("tags") or []),
    }
    if record.public_url and _safe_input_asset_public_url(record.public_url):
        descriptor["public_url"] = record.public_url
    return descriptor


def _safe_input_asset_public_url(value: str) -> bool:
    value = value.strip()
    return bool(value) and not value.startswith("data:") and ";base64," not in value


def _product_reference_assets_from_request(
    request: WorkflowV2PlanFromPromptRequest,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for selected in request.selected_assets:
        payload = selected.model_dump(mode="json")
        if _is_image_payload(payload):
            payload["role"] = "product_reference"
            payload["semantic_type"] = payload.get("semantic_type") or "product_reference"
            assets.append(payload)
    for reference in request.asset_references:
        payload = reference.model_dump(mode="json")
        asset_ids = payload.get("asset_ids") or (
            [payload["asset_id"]] if payload.get("asset_id") else []
        )
        if not asset_ids and payload.get("entity_id"):
            asset_ids = [payload["entity_id"]]
        for asset_id in asset_ids:
            assets.append(_asset_payload_from_reference(payload, str(asset_id)))
    for entity_id in request.library_entity_ids:
        assets.append(
            {
                "asset_id": str(entity_id),
                "entity_id": str(entity_id),
                "library_entity_id": str(entity_id),
                "media_type": "image",
                "asset_type": "image",
                "filename": f"{entity_id}.bin",
                "display_name": str(entity_id),
                "semantic_type": "product_reference",
                "role": "product_reference",
                "metadata": {"library_entity_id": str(entity_id)},
            }
        )
    return _dedupe_asset_payloads(assets)


def _asset_payload_from_reference(reference: dict[str, Any], asset_id: str) -> dict[str, Any]:
    metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
    return {
        "asset_id": asset_id,
        "entity_id": reference.get("entity_id"),
        "media_type": metadata.get("media_type") or metadata.get("asset_type") or "image",
        "asset_type": metadata.get("asset_type") or metadata.get("media_type") or "image",
        "filename": metadata.get("filename") or reference.get("display_name") or f"{asset_id}.bin",
        "display_name": reference.get("display_name") or metadata.get("display_name") or asset_id,
        "semantic_type": metadata.get("semantic_type") or "product_reference",
        "role": "product_reference",
        "local_path": metadata.get("local_path") or metadata.get("file_path"),
        "public_url": metadata.get("public_url"),
        "mime_type": metadata.get("mime_type") or metadata.get("content_type") or "image/png",
        "metadata": {
            **metadata,
            "reference_source": reference.get("reference_source"),
            "reference_role": reference.get("role") or "product_reference",
        },
    }


def _is_image_payload(payload: dict[str, Any]) -> bool:
    for key in ("media_type", "asset_type", "type", "kind"):
        value = payload.get(key)
        if value == "image":
            return True
    mime_type = str(payload.get("mime_type") or "")
    return mime_type.startswith("image/")


def _dedupe_asset_payloads(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id and asset_id in seen:
            continue
        if asset_id:
            seen.add(asset_id)
        deduped.append(asset)
    return deduped


def _node_by_id(workflow: WorkflowV2, node_id: str) -> WorkflowNodeV2 | None:
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _active_items(node: WorkflowNodeV2) -> list[WorkflowItemV2]:
    return [item for item in node.items if item.lifecycle_state == "active"]


def _slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _first_slot_media_type(item: WorkflowItemV2 | None) -> str | None:
    if item is None or not item.slots:
        return None
    return item.slots[0].media_type


def _patch_detail_prompts(
    shot: WorkflowItemV2,
    payload: dict[str, Any],
) -> list[str]:
    allowed = {
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
        "time_segments",
        "desired_duration_seconds",
        "provider_duration_seconds",
    }
    updated: list[str] = []
    for field_name, value in payload.items():
        if field_name not in allowed or value is None:
            continue
        shot.detail_prompts[field_name] = value
        if field_name in {"desired_duration_seconds", "provider_duration_seconds"}:
            shot.metadata[field_name] = value
        updated.append(field_name)
    return updated


def _primary_scene_reference_item_ids(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
    scene_item_id: str,
) -> list[str]:
    item_by_id = {
        item.item_id: item
        for node in workflow.nodes
        for item in node.items
        if item.lifecycle_state == "active"
    }
    product_ids = [
        item_id
        for item_id in shot.reference_item_ids
        if item_by_id.get(item_id) is not None and item_by_id[item_id].item_type == "product"
    ]
    character_ids = [
        item_id
        for item_id in shot.reference_item_ids
        if item_by_id.get(item_id) is not None and item_by_id[item_id].item_type == "character"
    ]
    return list(dict.fromkeys([*product_ids, *character_ids, scene_item_id]))


def _execution_shot_reference_selections(workflow: WorkflowV2) -> dict[str, dict[str, Any]]:
    selections: dict[str, dict[str, Any]] = {}
    storyboard = _node_by_id(workflow, "storyboard")
    if storyboard is None:
        return selections
    active_scene_ids = {
        item.item_id
        for node in workflow.nodes
        for item in node.items
        if item.lifecycle_state == "active" and item.item_type == "scene"
    }
    for shot in storyboard.items:
        if shot.lifecycle_state != "active" or shot.item_type != "shot":
            continue
        source_script_shot = shot.metadata.get("source_script_shot")
        source_reference_ids = (
            [str(item_id) for item_id in source_script_shot.get("reference_item_ids") or []]
            if isinstance(source_script_shot, dict)
            else []
        )
        semantic_reference_ids = shot.reference_item_ids or source_reference_ids
        primary_scene_item_id = shot.primary_scene_item_id or next(
            (item_id for item_id in semantic_reference_ids if item_id in active_scene_ids),
            None,
        )
        if not primary_scene_item_id:
            continue
        reference_item_ids = [
            item_id for item_id in semantic_reference_ids if item_id not in active_scene_ids
        ]
        reference_item_ids.append(primary_scene_item_id)
        selections[shot.item_id] = {
            "shot_item_id": shot.item_id,
            "primary_scene_item_id": primary_scene_item_id,
            "reference_item_ids": list(dict.fromkeys(reference_item_ids)),
        }
    return selections


def _update_shot_script_metadata(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
    scene_item_id: str,
    reference_item_ids: list[str],
) -> None:
    source_script_shot = shot.metadata.get("source_script_shot")
    if isinstance(source_script_shot, dict):
        source_script_shot.update(
            {
                "scene_id": scene_item_id,
                "scene_ids": [scene_item_id],
                "reference_item_ids": list(reference_item_ids),
            }
        )
    script_plan = workflow.metadata.get("script_plan")
    if not isinstance(script_plan, dict):
        return
    script_shots = script_plan.get("shots")
    if not isinstance(script_shots, list):
        return
    for script_shot in script_shots:
        if not isinstance(script_shot, dict):
            continue
        if str(script_shot.get("shot_id") or "") != (shot.shot_id or shot.item_id):
            continue
        script_shot.update(
            {
                "scene_id": scene_item_id,
                "scene_ids": [scene_item_id],
                "reference_item_ids": list(reference_item_ids),
            }
        )
        break


def _detail_prompt_dirty_fields(shot: WorkflowItemV2) -> list[str]:
    value = shot.metadata.get("detail_prompt_dirty_fields")
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _mark_detail_prompt_dirty_fields(
    shot: WorkflowItemV2,
    fields: list[str],
    *,
    reset: bool,
) -> None:
    existing = [] if reset else _detail_prompt_dirty_fields(shot)
    shot.metadata["detail_prompt_dirty_fields"] = list(dict.fromkeys([*existing, *fields]))
    shot.metadata["detail_prompts_outdated"] = False


def _sync_shot_video_detail_prompt(shot: WorkflowItemV2) -> None:
    video_slot = _slot_by_type(shot, "shot_video_segment")
    if video_slot is None:
        return
    apply_shot_video_prompts(
        video_slot,
        shot.shot_summary_prompt or shot.item_prompt or shot.item_id,
        detail_prompts=shot.detail_prompts,
    )


def _slot_plan_for_item(item: WorkflowItemV2) -> tuple[str, ...]:
    if item.node_id == "product-generation":
        return ("product_main_image", "product_multi_view_grid")
    if item.node_id == "character-generation":
        return ("character_main_image", "character_three_view")
    if item.node_id == "scene-generation":
        return ("scene_main_image", "scene_multi_view_grid")
    if item.node_id == "storyboard":
        return (*shot_cell_slot_types(), "shot_video_segment")
    if item.node_id == "bgm":
        return ("bgm_audio",)
    if item.node_id == "final-composition":
        return ("final_video",)
    return tuple(slot.slot_type for slot in item.slots if slot.required)


def _execution_status(slot_transitions: list[dict[str, Any]]) -> tuple[str, list[str]]:
    waiting_slot_ids = _waiting_slot_ids(slot_transitions)
    if waiting_slot_ids:
        return "waiting", waiting_slot_ids
    return "completed", []


def _waiting_slot_ids(slot_transitions: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            [
                str(transition["slot_id"])
                for transition in slot_transitions
                if transition.get("to_status") == "waiting"
            ]
        )
    )


def _execution_status_from_slots(
    *,
    completed_slot_ids: list[str],
    waiting_slot_ids: list[str],
    failed_slot_ids: list[str],
) -> str:
    if waiting_slot_ids:
        return "waiting"
    if failed_slot_ids and completed_slot_ids:
        return "partial_failed"
    if failed_slot_ids:
        return "failed"
    return "completed"


def _item_ids(workflow: WorkflowV2) -> list[str]:
    return [item.item_id for node in workflow.nodes for item in _active_items(node)]


def _slot_ids(workflow: WorkflowV2) -> list[str]:
    return [
        slot.slot_id
        for node in workflow.nodes
        for item in _active_items(node)
        for slot in item.slots
    ]


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


def _append_unique(payload: dict[str, Any], key: str, value: str) -> None:
    values = [str(item) for item in payload.get(key, []) if str(item)]
    if value not in values:
        values.append(value)
    payload[key] = values


def _remove_value(payload: dict[str, Any], key: str, value: str) -> None:
    payload[key] = [str(item) for item in payload.get(key, []) if str(item) != value]


def _free_role_for_media_type(media_type: str) -> str:
    return {
        "image": "free-image",
        "video": "free-video",
        "audio": "free-audio",
    }.get(media_type, "free-image")


def _provider_task_media_type(task: V2ProviderTask) -> str:
    media_type = str(task.metadata.get("media_type") or "")
    if media_type in {"image", "video", "audio", "text"}:
        return media_type
    return "image"


def _provider_task_response_reused_terminal_result(
    response: V2ProviderTaskPollResponse,
) -> bool:
    provider_result = response.provider_result
    return bool(
        provider_result is not None and provider_result.metadata.get("terminal_task_reused") is True
    )


def _provider_task_timed_out(task: V2ProviderTask) -> bool:
    timeout_at = task.metadata.get("timeout_at")
    if not isinstance(timeout_at, str) or not timeout_at.strip():
        return False
    try:
        deadline = datetime.fromisoformat(timeout_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline <= datetime.now(timezone.utc)


def _expired_remote_reconciliation_eligible(task: V2ProviderTask) -> bool:
    if task.status not in {"submitted", "waiting"} or not task.remote_task_id:
        return False
    reconciliation = task.metadata.get("expired_remote_reconciliation")
    return not (
        isinstance(reconciliation, dict)
        and isinstance(reconciliation.get("started_at"), str)
        and reconciliation["started_at"].strip()
    )


RETRYABLE_PROVIDER_ERROR_CODES = {
    "provider_rate_limited",
    "provider_timeout",
    "provider_temporary_unavailable",
    "provider_connection_reset",
    "provider_5xx",
    "provider_server_error",
}

RETRYABLE_PROVIDER_DOWNLOAD_ERROR_CODES = {
    "bgm_audio_download_failed",
    "provider_download_timeout",
    "provider_download_connection_error",
    "provider_download_http_408",
    "provider_download_http_429",
    "provider_download_http_5xx",
    "provider_download_incomplete",
}


def _is_retryable_provider_result_download(result: V2ProviderResult) -> bool:
    return (
        result.metadata.get("stage") == "provider_result_download"
        and bool(result.metadata.get("download_retryable"))
        and str(result.error_code or "").strip().lower() in RETRYABLE_PROVIDER_DOWNLOAD_ERROR_CODES
    )


def _provider_poll_retryable(
    task: V2ProviderTask,
    result: V2ProviderResult,
    settings: Settings,
) -> bool:
    if result.status != "failed":
        return False
    if _provider_task_timed_out(task):
        return False
    if _is_retryable_provider_result_download(result):
        return task.download_attempt_count + 1 < _provider_download_max_attempts(settings)
    error_code = str(result.error_code or "").strip().lower()
    if error_code not in RETRYABLE_PROVIDER_ERROR_CODES and not error_code.startswith("provider_5"):
        return False
    return task.retry_count + 1 < _provider_task_max_attempts(task, settings)


def _download_result_retry_budget_exhausted(
    task: V2ProviderTask,
    result: V2ProviderResult,
    settings: Settings,
) -> bool:
    return _is_retryable_provider_result_download(
        result
    ) and task.download_attempt_count + 1 >= _provider_download_max_attempts(settings)


def _provider_result_download_exhausted(
    task: V2ProviderTask,
    result: V2ProviderResult,
    settings: Settings,
) -> V2ProviderResult:
    return result.model_copy(
        update={
            "error_code": "provider_result_download_exhausted",
            "error_message": "Provider result download attempts were exhausted.",
            "metadata": {
                **result.metadata,
                "download_attempt": task.download_attempt_count + 1,
                "max_download_attempts": _provider_download_max_attempts(settings),
                "download_retryable": False,
            },
        }
    )


def _historical_result_recovery_should_be_exhausted(
    task: V2ProviderTask,
    result: V2ProviderResult,
) -> bool:
    if result.status != "failed":
        return False
    recovery = task.metadata.get("historical_result_recovery")
    if not isinstance(recovery, dict) or recovery.get("exhausted") is True:
        return False
    return True


def _provider_download_max_attempts(settings: Settings) -> int:
    return max(1, settings.v2_provider_download_max_attempts)


def _provider_retry_delay_seconds(
    task: V2ProviderTask,
    result: V2ProviderResult,
    settings: Settings,
) -> int:
    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    if _is_retryable_provider_result_download(result):
        attempt = task.download_attempt_count + 1
    else:
        attempt = task.retry_count + 1
    return min(60, interval * (2 ** max(0, attempt - 1)))


def _provider_task_max_attempts(task: V2ProviderTask, settings: Settings) -> int:
    media_type = _provider_task_media_type(task)
    if media_type == "video":
        return max(1, settings.provider_max_attempts_video)
    if media_type == "audio":
        return max(1, settings.provider_max_attempts_audio)
    return max(1, settings.provider_max_attempts_image)


def _cooldown_is_active(cooldown: dict[str, Any], now: datetime) -> bool:
    active_until = cooldown.get("active_until")
    if not isinstance(active_until, str) or not active_until.strip():
        return False
    try:
        deadline = datetime.fromisoformat(active_until.replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > now


def _slot_is_stale(slot: WorkflowSlotV2) -> bool:
    return slot.status == "stale" or bool(slot.metadata.get("stale"))


def _free_absorb_allowed(resolved_role: str, target_node_id: str) -> bool:
    allowed = {
        "free-image": {"product-generation", "character-generation", "scene-generation"},
        "free-audio": {"bgm"},
        "free-video": {"final-composition"},
    }
    return target_node_id in allowed.get(resolved_role, set())
