"""Dynamic binding-derived scheduler for Agent Canvas."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import (
    AgentCanvasRuntimeRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeErrorV2, CanvasNodeV2
from app.schemas.agent_canvas import ResolvedNodeInputManifestV2
from app.schemas.agent_canvas_ad_media import (
    AdReferenceBundleV2,
    CompiledProviderPromptV2,
)
from app.schemas.agent_canvas_runtime import (
    CanvasExecutionMembershipV2,
    CanvasRunAcceptedV2,
    CanvasRunCancelResponseV2,
    CanvasRunRequestV2,
    CanvasRunSkippedNodeV2,
    CanvasRuntimeSnapshotV2,
    CanvasProviderTaskV2,
    EffectiveMediaParameterSnapshotV2,
    NodeExecutionLeaseV2,
    NodeRuntimeV2,
    ResolvedModelExecutionV1,
)
from app.schemas.agent_canvas_prompt_assertion import (
    safe_provider_prompt_assertion_metadata,
)
from app.schemas.agent_canvas_video_parameters import CompiledVideoParametersV2
from app.schemas.agent_canvas_runtime_authority import CanvasExecutionStartCommandV2
from app.schemas.agent_canvas_runtime_authority import CanvasExecutionResultCommitCommandV2
from app.schemas.agent_canvas_world_setting import (
    WorldSettingContextEnvelopeV2,
    WorldSettingResolvedInputV2,
)
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_node_execution import (
    GeneratedMediaPayload,
    NodeExecutionContext,
    NodeExecutionDispatcher,
    NodeExecutionOutcome,
)
from app.services.agent_canvas_execution_parameters import (
    AgentCanvasExecutionParameterResolver,
)
from app.services.agent_canvas_provider_capabilities import (
    ProviderCapabilityService,
)
from app.services.agent_canvas_execution_state import (
    AgentCanvasExecutionStateMachine,
    safe_execution_error,
)
from app.services.agent_canvas_fenced_lease import NodeLeaseService
from app.services.agent_canvas_execution_result_commit import (
    AgentCanvasExecutionResultCommitService,
)
from app.services.agent_canvas_output_preparation import (
    AgentCanvasOutputPreparationService,
)
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_run_snapshots import AgentCanvasRunIntentSnapshotService
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistry
from app.services.agent_canvas_prompt_assertion_policy import (
    current_source_snapshots_for_evidence,
    prompt_assertion_admission_error,
)
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)
from app.services.agent_canvas_world_setting_context import WorldSettingContextResolverV2
from app.services.agent_canvas_video_parameter_compiler import (
    AgentCanvasVideoParameterCompiler,
)
from app.services.model_resolution import ModelResolutionService


MediaPublisher = Callable[[NodeExecutionContext, GeneratedMediaPayload, str], str]
ScriptReadyPublisher = Callable[[str, str], object]
TextReadyPublisher = Callable[[CanvasNodeV2], object]
MediaReadyPublisher = Callable[[CanvasNodeV2], tuple[str, ...] | None]
MediaContextPreparer = Callable[
    [CanvasNodeV2, WorldSettingContextEnvelopeV2 | None],
    tuple[CompiledProviderPromptV2 | None, AdReferenceBundleV2 | None],
]
TerminalMemberReconciler = Callable[..., bool]
StageTraceWriter = Callable[
    [NodeExecutionContext, str, dict[str, object], str | None, datetime, datetime],
    None,
]
Clock = Callable[[], datetime]
RunEligibilityValidator = Callable[[CanvasNodeV2], None]


class AgentCanvasRunService:
    """Accept run membership without creating canvas nodes."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
        events: EventRepository,
        *,
        run_snapshots: AgentCanvasRunIntentSnapshotService | None = None,
        eligibility_validator: RunEligibilityValidator | None = None,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._events = events
        self._run_snapshots = run_snapshots
        self._eligibility_validator = eligibility_validator
        self._clock = clock

    def start_or_extend(
        self,
        workflow_id: str,
        request: CanvasRunRequestV2,
        *,
        idempotency_key: str,
    ) -> CanvasRunAcceptedV2:
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        requested = (
            tuple(nodes.values())
            if request.scope == "all_drafts"
            else tuple(self._require_node(nodes, node_id) for node_id in request.node_ids)
        )
        requested_node_ids = {node.node_id for node in requested}
        accepted: list[str] = []
        skipped: list[CanvasRunSkippedNodeV2] = []
        for node in requested:
            reason = _skip_reason(node, request)
            if reason is None:
                if request.scope == "selected_nodes":
                    unready_bindings = _unready_required_bindings(
                        workflow,
                        node.node_id,
                        nodes,
                    )
                    unready_bindings = tuple(
                        binding
                        for binding in unready_bindings
                        if binding.source.source_node_id not in requested_node_ids
                    )
                    missing_node_ids = tuple(
                        binding.source.source_node_id for binding in unready_bindings
                    )
                    if missing_node_ids:
                        raise _run_error(
                            "upstream_inputs_not_ready",
                            "Required upstream inputs are not ready.",
                            details={
                                "missing_node_ids": list(missing_node_ids),
                                "target_node_id": node.node_id,
                                "bindings": [
                                    {
                                        "binding_id": binding.binding_id,
                                        "source_node_id": binding.source.source_node_id,
                                        "target_node_id": binding.target_node_id,
                                        "required": binding.required,
                                    }
                                    for binding in unready_bindings
                                ],
                            },
                        )
                try:
                    if self._eligibility_validator is not None:
                        self._eligibility_validator(node)
                except V2PersistenceError as error:
                    if request.scope == "selected_nodes":
                        raise
                    skipped.append(
                        CanvasRunSkippedNodeV2(
                            node_id=node.node_id,
                            reason=error.code,
                        )
                    )
                    continue
                accepted.append(node.node_id)
            elif request.scope == "selected_nodes":
                raise _run_error(reason, _skip_message(reason))
            else:
                skipped.append(CanvasRunSkippedNodeV2(node_id=node.node_id, reason=reason))
        if not accepted:
            return CanvasRunAcceptedV2(
                workflow_id=workflow_id,
                execution_id=f"skipped:{_fingerprint(request)}",
                status="completed",
                accepted_node_ids=(),
                joined_node_ids=(),
                skipped=tuple(skipped),
                waiting_node_ids=(),
                events_cursor=self._events.max_seq(workflow_id),
            )
        now = self._clock()
        snapshot_service = self._run_snapshots or AgentCanvasRunIntentSnapshotService(
            self._workflows,
            self._runtime,
        )
        accepted_nodes = tuple(nodes[node_id] for node_id in accepted)
        admission = self._runtime.start_or_join_execution(
            CanvasExecutionStartCommandV2(
                workflow_id=workflow_id,
                expected_workflow_revision=workflow.revision,
                scope=request.scope,
                idempotency_key=idempotency_key,
                request_digest=_fingerprint(request),
                member_intents=snapshot_service.prepare_member_intents(
                    workflow,
                    accepted_nodes,
                ),
                created_at=now,
            )
        )
        execution = admission.execution
        members = self._runtime.list_members(execution.execution_id)
        cursor = self._events.max_seq(workflow_id)
        return CanvasRunAcceptedV2(
            workflow_id=workflow_id,
            execution_id=execution.execution_id,
            status=execution.status,
            accepted_node_ids=admission.accepted_node_ids,
            joined_node_ids=admission.joined_node_ids,
            skipped=tuple(skipped),
            waiting_node_ids=(),
            events_cursor=cursor,
            run_intent_snapshot_ids={
                member.node_id: member.run_intent_snapshot_id
                for member in members
                if member.run_intent_snapshot_id is not None
            },
        )

    @staticmethod
    def _require_node(nodes: dict[str, CanvasNodeV2], node_id: str) -> CanvasNodeV2:
        node = nodes.get(node_id)
        if node is None:
            raise _run_error("node_not_found", "Canvas node was not found.")
        return node


class DynamicCanvasScheduler:
    """Execute only persisted membership and current required bindings."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
        bindings: AgentCanvasBindingService,
        capabilities: ProviderCapabilityService,
        dispatcher: NodeExecutionDispatcher,
        *,
        model_resolution: ModelResolutionService | None = None,
        media_publisher: MediaPublisher,
        script_ready_publisher: ScriptReadyPublisher | None = None,
        text_ready_publisher: TextReadyPublisher | None = None,
        media_ready_publisher: MediaReadyPublisher | None = None,
        media_context_preparer: MediaContextPreparer | None = None,
        stage_trace_writer: StageTraceWriter | None = None,
        input_compiler: AgentCanvasResolvedInputCompiler | None = None,
        run_snapshots: AgentCanvasRunIntentSnapshotService | None = None,
        execution_parameters: AgentCanvasExecutionParameterResolver | None = None,
        video_parameter_compiler: AgentCanvasVideoParameterCompiler | None = None,
        world_settings: WorldSettingContextResolverV2 | None = None,
        state_machine: AgentCanvasExecutionStateMachine | None = None,
        output_preparer: AgentCanvasOutputPreparationService | None = None,
        result_committer: AgentCanvasExecutionResultCommitService | None = None,
        terminal_member_reconciler: TerminalMemberReconciler | None = None,
        prompt_preparation: NodePromptPreparationService | None = None,
        owner_id: str | None = None,
        image_limit: int = 4,
        video_limit: int = 1,
        audio_limit: int = 1,
        total_limit: int = 5,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._bindings = bindings
        self._capabilities = capabilities
        self._model_resolution = model_resolution
        self._dispatcher = dispatcher
        self._media_publisher = media_publisher
        self._script_ready_publisher = script_ready_publisher
        self._text_ready_publisher = text_ready_publisher
        self._media_ready_publisher = media_ready_publisher
        self._media_context_preparer = media_context_preparer
        self._stage_trace_writer = stage_trace_writer
        self._input_compiler = input_compiler or AgentCanvasResolvedInputCompiler(
            bindings,
            world_settings=world_settings,
        )
        self._run_snapshots = run_snapshots
        self._execution_parameters = execution_parameters or AgentCanvasExecutionParameterResolver()
        self._video_parameter_compiler = video_parameter_compiler
        self._state_machine = state_machine or AgentCanvasExecutionStateMachine()
        self._leases = NodeLeaseService(runtime, clock=clock)
        self._output_preparer = output_preparer
        self._result_committer = result_committer
        self._terminal_member_reconciler = terminal_member_reconciler
        self._prompt_preparation = prompt_preparation or NodePromptPreparationService(workflows)
        self._owner_id = owner_id or f"worker_{uuid4().hex}"
        self._limits = {
            "image": image_limit,
            "video": video_limit,
            "audio": audio_limit,
            "text": total_limit,
            "script": total_limit,
        }
        self._total_limit = total_limit
        self._clock = clock

    def resume(self, execution_id: str) -> None:
        execution = self._runtime.get_execution(execution_id)
        if execution.status not in {"queued", "running", "waiting"}:
            return
        self._runtime.set_execution_status(
            execution_id,
            "running",
            now=self._clock(),
            event_type="execution_started",
        )
        while True:
            current = self._runtime.get_execution(execution_id)
            if current.cancel_requested:
                self._cancel_members(current.workflow_id, execution_id)
                return
            ready_wave = self.compute_ready_wave(execution_id)
            if not ready_wave:
                self._finish_if_quiescent(execution_id)
                return
            leases = []
            now = self._clock()
            for node_id in ready_wave:
                lease = self._runtime.claim_lease(
                    execution_id,
                    node_id,
                    owner_id=self._owner_id,
                    now=now,
                    ttl=timedelta(seconds=60),
                )
                if lease is None:
                    continue
                leases.append(lease)
            with ThreadPoolExecutor(max_workers=max(len(leases), 1)) as executor:
                dependency_barrier_seen = False
                prepared_contexts: list[tuple[NodeExecutionLeaseV2, NodeExecutionContext]] = []
                for lease in leases:
                    try:
                        context = self._prepare_member(
                            current.workflow_id,
                            lease.execution_id,
                            lease.node_id,
                        )
                    except Exception as error:
                        if self._is_dependency_barrier(error):
                            self._defer_dependency_member(current.workflow_id, lease, error)
                            dependency_barrier_seen = True
                            continue
                        self._fail_member(current.workflow_id, lease, error)
                        continue
                    prepared_contexts.append((lease, context))
                prepared = []
                dispatchable_contexts: list[tuple[NodeExecutionLeaseV2, NodeExecutionContext]] = []
                for lease, context in prepared_contexts:
                    try:
                        self._assert_current_dependency_fence(
                            current.workflow_id,
                            lease.execution_id,
                            lease.node_id,
                            context,
                        )
                    except Exception as error:
                        if self._is_dependency_barrier(error):
                            self._defer_dependency_member(current.workflow_id, lease, error)
                            dependency_barrier_seen = True
                            continue
                        self._fail_member(current.workflow_id, lease, error)
                        continue
                    self._runtime.update_member(
                        lease.execution_id,
                        lease.node_id,
                        state="running",
                        phase="running",
                        now=self._clock(),
                    )
                    event_payload: dict[str, object] = {}
                    if context.seedance_input_audit is not None:
                        event_payload["seedance_input_manifest"] = (
                            context.seedance_input_audit.model_dump(mode="json")
                        )
                    if context.optional_input_omissions:
                        event_payload["optional_input_omissions"] = list(
                            context.optional_input_omissions
                        )
                    if context.model_resolution is not None:
                        event_payload["model_resolution"] = context.model_resolution.model_dump(
                            mode="json"
                        )
                    if (
                        context.compiled_prompt is not None
                        and context.compiled_prompt.assertion_evidence is not None
                    ):
                        event_payload["prompt_assertion_evidence"] = (
                            context.compiled_prompt.assertion_evidence.model_dump(mode="json")
                        )
                    self._workflows.set_node_runtime_state(
                        current.workflow_id,
                        lease.node_id,
                        status="working",
                        updated_at=self._clock(),
                        execution_id=lease.execution_id,
                        event_type="node_generation_started",
                        event_payload=event_payload,
                    )
                    dispatchable_contexts.append((lease, context))
                for lease, context in dispatchable_contexts:
                    prepared.append(
                        (
                            lease,
                            context,
                            executor.submit(self._execute_member_guarded, lease, context),
                        )
                    )
                for lease, context, future in prepared:
                    try:
                        self._complete_member(
                            current.workflow_id,
                            lease,
                            context,
                            future.result(),
                        )
                    except Exception as error:
                        self._fail_member(current.workflow_id, lease, error)
                # A dependency barrier is durable state owned by the prompt
                # preparation/reconciliation path.  Do not immediately loop
                # and reclaim the same member while its successor evidence is
                # still queued; the preparation worker (or the next runtime
                # recovery tick) will wake a subsequent scheduler wave.
                if dependency_barrier_seen:
                    self._finish_if_quiescent(execution_id)
                    return

    def compute_ready_wave(self, execution_id: str) -> tuple[str, ...]:
        execution = self._runtime.get_execution(execution_id)
        workflow = self._workflows.get_workflow(execution.workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        members = self._runtime.list_members(execution_id)
        members_by_node = {member.node_id: member for member in members}
        candidates: list[CanvasExecutionMembershipV2] = []
        for member in members:
            if member.state not in {"queued", "waiting"}:
                continue
            required_waiting = tuple(
                dict.fromkeys(
                    (
                        *_frozen_unready_sources(member, nodes, required=True),
                        *_same_wave_dependency_sources(member, members_by_node),
                    )
                )
            )
            preferred_waiting = tuple(
                source_node_id
                for source_node_id in _frozen_unready_sources(member, nodes, required=False)
                if members_by_node.get(source_node_id) is not None
                and members_by_node[source_node_id].state in {"queued", "waiting", "running"}
            )
            waiting = tuple(dict.fromkeys((*required_waiting, *preferred_waiting)))
            if waiting:
                blocked = tuple(
                    source_node_id
                    for source_node_id in required_waiting
                    if (source := nodes.get(source_node_id)) is None or source.status == "failed"
                )
                self._runtime.update_member(
                    execution_id,
                    member.node_id,
                    state="skipped_dependency" if blocked else "waiting",
                    phase="blocked_by_upstream" if blocked else "waiting_for_input",
                    waiting_for_node_ids=waiting,
                    now=self._clock(),
                    event_type=(
                        "execution_member_skipped_dependency"
                        if blocked
                        else (
                            "node_blocked"
                            if required_waiting
                            else "node_waiting_for_preferred_input"
                        )
                    ),
                    event_payload={
                        "waiting_for_node_ids": list(waiting),
                        "blocked_by_node_ids": list(blocked),
                        "preferred_upstream_node_ids": list(preferred_waiting),
                        **({"reason_code": "skipped_dependency"} if blocked else {}),
                    },
                )
                continue
            if _prompt_preparation_pending(node := nodes.get(member.node_id)):
                # Queued/working prompt preparation is a typed durable barrier,
                # not a user-facing manual wait.  Keep the execution member out
                # of the ready wave until the shared preparation worker
                # publishes current evidence.
                waiting_for = _prompt_preparation_waiting_sources(member)
                if not (
                    member.state == "waiting"
                    and member.phase == "blocked_by_upstream"
                    and member.waiting_for_node_ids == waiting_for
                ):
                    self._runtime.update_member(
                        execution_id,
                        member.node_id,
                        state="waiting",
                        phase="blocked_by_upstream",
                        waiting_for_node_ids=waiting_for,
                        now=self._clock(),
                        event_type="execution_member_prompt_preparation_barrier",
                        event_payload={
                            "node_id": member.node_id,
                            "operation_id": node.prompt_preparation.operation_id,
                            "prompt_preparation_status": node.prompt_preparation.status,
                            "waiting_for_node_ids": list(waiting_for),
                        },
                    )
                continue
            candidates.append(member)
        selected: list[str] = []
        used: dict[str, int] = {}
        for member in candidates:
            node_type = nodes[member.node_id].node_type
            if len(selected) >= self._total_limit:
                break
            if used.get(node_type, 0) >= self._limits[node_type]:
                continue
            selected.append(member.node_id)
            used[node_type] = used.get(node_type, 0) + 1
        return tuple(selected)

    def cancel(self, execution_id: str, *, reason: str) -> CanvasRunCancelResponseV2:
        execution = self._runtime.request_cancel(execution_id, now=self._clock())
        cancelled = self._cancel_members(execution.workflow_id, execution_id, reason=reason)
        return CanvasRunCancelResponseV2(
            workflow_id=execution.workflow_id,
            execution_id=execution_id,
            status="cancelled",
            cancelled_node_ids=cancelled,
            events_cursor=self._runtime_event_cursor(execution.workflow_id),
        )

    def _prepare_member(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
    ) -> NodeExecutionContext:
        now = self._clock()
        member = next(
            item for item in self._runtime.list_members(execution_id) if item.node_id == node_id
        )
        observed_node = self._workflows.get_node(workflow_id, node_id)
        observed_revision = observed_node.revision
        frozen_node = member.prompt_metadata.get("frozen_node")
        node = (
            CanvasNodeV2.model_validate(frozen_node)
            if isinstance(frozen_node, dict)
            else self._workflows.get_node(workflow_id, node_id)
        )
        managed_prompt = bool(
            node.prompt_preparation.role_variant
            or node.prompt_preparation.recipe_id
            or node.metadata.get("prompt_recipe_id")
        )
        if managed_prompt and node.prompt_preparation.status == "failed":
            preparation_error = node.prompt_preparation.error
            if preparation_error is None:
                raise V2PersistenceError(
                    "prompt_preparation_failed",
                    "Node prompt preparation failed without a typed error.",
                    stage="agent_canvas_scheduler",
                    details={"retryable": False, "reason": "prompt_preparation_failed"},
                )
            raise V2PersistenceError(
                preparation_error.code,
                preparation_error.message,
                stage="agent_canvas_scheduler",
                details={
                    "retryable": preparation_error.retryable,
                    "reason": "prompt_preparation_failed",
                },
            )
        if managed_prompt and node.prompt_preparation.status != "ready":
            member_snapshot = next(
                item for item in self._runtime.list_members(execution_id) if item.node_id == node_id
            ).run_intent_snapshot
            raise V2PersistenceError(
                "execution_dependency_barrier_pending",
                "Current Node prompt evidence is not ready for execution.",
                stage="agent_canvas_scheduler",
                details={
                    "retryable": True,
                    "reason": "prompt_preparation_pending",
                    "source_node_ids": [
                        binding.source_id
                        for binding in (
                            member_snapshot.binding_snapshots if member_snapshot else ()
                        )
                        if binding.source_kind == "node_output"
                    ],
                },
            )
        node, derived_normalizations = self._execution_parameters.freeze_node(node)
        stored_manifest = member.resolved_input_manifest or member.prompt_metadata.get(
            "resolved_input_manifest"
        )
        manifest = (
            ResolvedNodeInputManifestV2.model_validate(stored_manifest)
            if isinstance(stored_manifest, dict)
            else (
                self._run_snapshots.resolve_inputs(
                    execution_id,
                    node_id,
                    compiler=self._input_compiler,
                )
                if self._run_snapshots is not None and member.run_intent_snapshot is not None
                else self._input_compiler.compile(
                    workflow_id=workflow_id,
                    target_node_id=node_id,
                    execution_id=execution_id,
                    node_run_id=f"node_run_{execution_id}_{node_id}",
                    run_intent_snapshot_id=member.run_intent_snapshot_id,
                    binding_snapshots=(
                        member.run_intent_snapshot.binding_snapshots
                        if member.run_intent_snapshot is not None
                        else None
                    ),
                )
            )
        )
        # Capturing a run input snapshot records its ID on the live Node
        # without advancing the authoring revision.  Carry only that
        # execution-owned projection into the immutable run snapshot; any
        # real authoring revision change remains fenced below.
        current_after_inputs = self._workflows.get_node(workflow_id, node_id)
        if current_after_inputs.revision == observed_revision:
            node = node.model_copy(
                update={
                    "prompt_context_snapshot_id": current_after_inputs.prompt_context_snapshot_id
                }
            )
        self._assert_current_dependency_fence(
            workflow_id,
            execution_id,
            node_id,
            NodeExecutionContext(
                execution_id=execution_id,
                node=node,
                inputs=(),
                input_manifest=manifest,
                authoring_revision_observed=observed_revision,
            ),
        )
        inputs = self._input_compiler.materialize_inputs(manifest)
        if len(manifest.world_setting_inputs) > 1:
            raise V2PersistenceError(
                "world_setting_binding_ambiguous",
                "A target Node cannot resolve more than one World Setting Binding.",
                stage="agent_canvas_scheduler",
            )
        world_setting = (
            manifest.world_setting_inputs[0].context if manifest.world_setting_inputs else None
        )
        model_id = None
        provider_id = None
        resolution = None
        compiled_prompt = None
        reference_bundle = None
        effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None
        parameter_compilation_snapshot = None
        prompt_metadata: dict[str, object] = dict(member.prompt_metadata)
        execution_parameter_normalizations = prompt_metadata.get(
            "execution_parameter_normalizations"
        )
        normalization_labels = (
            tuple(str(item) for item in execution_parameter_normalizations)
            if isinstance(execution_parameter_normalizations, list)
            else derived_normalizations
        )
        prompt_metadata["resolved_input_manifest"] = manifest.model_dump(mode="json")
        if world_setting is not None:
            prompt_metadata["world_setting_context"] = {
                "source_node_id": world_setting.source_node_id,
                "source_node_revision": world_setting.source_node_revision,
                "source_content_digest": world_setting.source_content_digest,
                "source_core_digest": world_setting.source_core_digest,
                "target_audience": world_setting.target_audience,
                "compiler_id": world_setting.compiler_id,
                "compiler_digest": world_setting.compiler_digest,
                "context_digest": world_setting.context_digest,
            }
        runtime_omissions = tuple(
            item.model_dump(mode="json") for item in manifest.omitted_optional_inputs
        )
        stored_resolution = prompt_metadata.get("model_resolution")
        if isinstance(stored_resolution, dict):
            resolution = ResolvedModelExecutionV1.model_validate(stored_resolution)
        elif self._model_resolution is not None and node.node_type != "editing":
            resolution = self._model_resolution.resolve(node)
            prompt_metadata["model_resolution"] = resolution.model_dump(mode="json")
        if resolution is not None:
            model_id = resolution.provider_model_id
            provider_id = resolution.provider_id
        if node.node_type in {"image", "video", "audio"}:
            selected_node = (
                node.model_copy(
                    update={
                        "model_selection_mode": "explicit",
                        "model_ref": resolution.model_ref,
                    }
                )
                if resolution is not None
                else node
            )
            capability = self._capabilities.resolve(selected_node, inputs)
            if node.node_type == "video" and self._video_parameter_compiler is not None:
                if member.parameter_compilation_snapshot_id is not None:
                    parameter_compilation_snapshot = (
                        self._runtime.get_parameter_compilation_snapshot(
                            member.parameter_compilation_snapshot_id
                        )
                    )
                    node = node.model_copy(
                        update={
                            "parameters": parameter_compilation_snapshot.requested_parameters,
                            "parameter_provenance": (
                                parameter_compilation_snapshot.parameter_provenance
                            ),
                        }
                    )
                else:
                    compiled = self._video_parameter_compiler.compile(
                        node=node,
                        selected_model_ref=(
                            resolution.model_ref if resolution is not None else capability.model_id
                        ),
                        capability=capability,
                        direct_text_inputs=manifest.text_inputs,
                        execution_id=execution_id,
                        member_id=member.member_id,
                        model_defaults=capability.default_parameters,
                        now=now,
                    )
                    parameter_compilation_snapshot = (
                        self._runtime.get_parameter_compilation_snapshot(
                            compiled.parameter_compilation_snapshot_id or ""
                        )
                    )
                    current_node = self._workflows.get_node(workflow_id, node_id)
                    if not _parameter_compilation_revision_is_current(
                        node,
                        current_node,
                        compiled,
                    ):
                        raise V2PersistenceError(
                            "execution_dependency_barrier_pending",
                            "Execution admission is waiting for the current dependency wave.",
                            stage="agent_canvas_scheduler",
                            details={
                                "retryable": True,
                                "reason": "target_node_revision_changed",
                                "reasons": ["target_node_revision_changed"],
                                "source_node_ids": [],
                            },
                        )
                    node = current_node.model_copy(
                        update={
                            "parameters": compiled.requested_parameters,
                            "parameter_provenance": compiled.parameter_provenance,
                        }
                    )
                    observed_revision = current_node.revision
                effective_parameters = EffectiveMediaParameterSnapshotV2(
                    requested=parameter_compilation_snapshot.requested_parameters,
                    effective=parameter_compilation_snapshot.effective_parameters,
                    normalizations=parameter_compilation_snapshot.normalizations,
                    parameter_compilation_snapshot_id=(parameter_compilation_snapshot.snapshot_id),
                    provider=capability.provider,
                    model_id=capability.model_id,
                    capability_revision=capability.capability_revision,
                )
                prompt_metadata["parameter_compilation_snapshot_id"] = (
                    parameter_compilation_snapshot.snapshot_id
                )
            else:
                effective_parameters = self._capabilities.effective_parameters(
                    node,
                    capability,
                    normalizations=normalization_labels,
                )
            prompt_metadata["effective_parameters"] = effective_parameters.model_dump(mode="json")
            if resolution is None:
                model_id = capability.model_id
                provider_id = capability.provider
            if self._media_context_preparer is not None:
                compiled_prompt, reference_bundle = self._media_context_preparer(
                    node,
                    world_setting,
                )
                if compiled_prompt is not None:
                    prompt_metadata.update(
                        {
                            "compiled_provider_prompt": compiled_prompt.model_dump(mode="json"),
                            "prompt_registry_ref": compiled_prompt.prompt_registry_ref,
                            "prompt_registry_digest": compiled_prompt.prompt_registry_digest,
                            "render_context_digest": compiled_prompt.render_context_digest,
                            "prompt_digest": compiled_prompt.prompt_digest,
                            "reference_bundle_digest": (compiled_prompt.reference_bundle_digest),
                        }
                    )
                    if compiled_prompt.assertion_evidence is not None:
                        prompt_metadata.update(
                            safe_provider_prompt_assertion_metadata(
                                compiled_prompt.assertion_evidence
                            )
                        )
                    if node.creative_role == "character":
                        prompt_metadata.update(
                            {
                                "character_asset_kind": node.structured_content.get(
                                    "character_asset_kind"
                                ),
                                "reference_rendering_mode": node.structured_content.get(
                                    "reference_rendering_mode"
                                ),
                                "negative_boundary_digest": hashlib.sha256(
                                    compiled_prompt.negative_prompt.encode("utf-8")
                                ).hexdigest(),
                            }
                        )
        context = NodeExecutionContext(
            execution_id=execution_id,
            node=node,
            inputs=inputs,
            authoring_revision_observed=observed_revision,
            model_id=model_id,
            provider_id=provider_id,
            model_resolution=resolution,
            compiled_prompt=compiled_prompt,
            reference_bundle=reference_bundle,
            effective_parameters=effective_parameters,
            input_manifest=manifest,
            optional_input_omissions=tuple(
                {
                    "binding_id": item.binding_id,
                    "source_node_id": item.source_node_id or "",
                    "reason": item.reason_code,
                }
                for item in manifest.omitted_optional_inputs
            ),
            world_setting=world_setting,
        )
        trace_started_at = self._clock()
        try:
            prepared = self._dispatcher.prepare(context)
        except Exception as error:
            self._trace_stage(
                context,
                "provider_compilation",
                status="failed",
                error=error,
                started_at=trace_started_at,
            )
            raise
        self._trace_stage(
            prepared,
            "provider_compilation",
            status="completed",
            started_at=trace_started_at,
        )
        transport_by_binding = {
            item.binding_id: item.provider_input_type
            for item in prepared.delivered_references
            if item.binding_id is not None
        }
        if transport_by_binding:
            prompt_metadata["provider_input_delivery"] = [
                {
                    "binding_id": item.binding_id,
                    "asset_id": item.asset_id,
                    "provider_input_type": item.provider_input_type,
                    "checksum": item.checksum,
                }
                for item in prepared.delivered_references
            ]
        if prepared.optional_input_omissions:
            prompt_metadata["optional_input_omissions"] = list(prepared.optional_input_omissions)
        if effective_parameters is not None and (
            effective_parameters.normalizations or parameter_compilation_snapshot is not None
        ):
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="running",
                now=now,
                prompt_metadata=prompt_metadata,
                resolved_input_manifest=manifest.model_dump(mode="json"),
                resolved_input_manifest_id=manifest.manifest_id,
                resolved_input_manifest_digest=manifest.manifest_digest,
                effective_parameters=effective_parameters,
                parameter_compilation_snapshot=parameter_compilation_snapshot,
                omitted_optional_inputs=runtime_omissions,
                event_type="media_parameters_normalized",
                event_payload={
                    "requested": effective_parameters.requested,
                    "effective": effective_parameters.effective,
                    "normalizations": [
                        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                        for item in effective_parameters.normalizations
                    ],
                    "parameter_compilation_snapshot_id": (
                        effective_parameters.parameter_compilation_snapshot_id
                    ),
                },
            )
        if stored_manifest is None:
            public_manifest = _public_input_manifest(manifest)
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="running",
                now=now,
                prompt_metadata=prompt_metadata,
                resolved_input_manifest=manifest.model_dump(mode="json"),
                resolved_input_manifest_id=manifest.manifest_id,
                resolved_input_manifest_digest=manifest.manifest_digest,
                effective_parameters=effective_parameters,
                parameter_compilation_snapshot=parameter_compilation_snapshot,
                omitted_optional_inputs=runtime_omissions,
                event_type="provider_inputs_resolved",
                event_payload={
                    "execution_id": execution_id,
                    "node_run_id": manifest.node_run_id,
                    "node_id": node_id,
                    "input_manifest_id": manifest.manifest_id,
                    "input_manifest": public_manifest,
                    "text_inputs": [
                        {
                            "binding_id": item.binding_id,
                            "source_node_id": item.source_node_id,
                            "snapshot_id": item.snapshot_id,
                            "input_role": item.input_role,
                            "display_order": item.display_order,
                        }
                        for item in manifest.text_inputs
                    ],
                    "world_setting_inputs": [
                        _public_world_setting_input(item) for item in manifest.world_setting_inputs
                    ],
                    "media_inputs": [
                        {
                            "binding_id": item.binding_id,
                            "source_node_id": item.source_node_id,
                            "asset_id": item.asset_id,
                            "media_type": item.media_type,
                            "input_role": item.input_role,
                            "display_order": item.display_order,
                            "checksum": item.checksum,
                            "transport_type": transport_by_binding.get(item.binding_id),
                        }
                        for item in manifest.media_inputs
                    ],
                    "omitted_optional_inputs": [
                        item.model_dump(mode="json") for item in manifest.omitted_optional_inputs
                    ],
                    "refresh": ["workflow_nodes", "runtime"],
                },
            )
            for omission in manifest.omitted_optional_inputs:
                self._runtime.update_member(
                    execution_id,
                    node_id,
                    state="running",
                    phase="running",
                    now=now,
                    omitted_optional_inputs=runtime_omissions,
                    event_type="provider_input_omitted",
                    event_payload=omission.model_dump(mode="json"),
                )
        if prepared.seedance_input_audit is not None:
            prompt_metadata["seedance_input_manifest"] = prepared.seedance_input_audit.model_dump(
                mode="json"
            )
            if prepared.optional_input_omissions:
                prompt_metadata["optional_input_omissions"] = list(
                    prepared.optional_input_omissions
                )
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="running",
                now=now,
                prompt_metadata=prompt_metadata,
                resolved_input_manifest=manifest.model_dump(mode="json"),
                resolved_input_manifest_id=manifest.manifest_id,
                resolved_input_manifest_digest=manifest.manifest_digest,
                effective_parameters=effective_parameters,
                parameter_compilation_snapshot=parameter_compilation_snapshot,
                omitted_optional_inputs=runtime_omissions,
            )
        elif prompt_metadata:
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="running",
                now=now,
                prompt_metadata=prompt_metadata,
                effective_parameters=effective_parameters,
                parameter_compilation_snapshot=parameter_compilation_snapshot,
                omitted_optional_inputs=runtime_omissions,
            )
        return prepared

    @staticmethod
    def _is_dependency_barrier(error: Exception) -> bool:
        return getattr(error, "code", None) == "execution_dependency_barrier_pending"

    def _defer_dependency_member(
        self,
        workflow_id: str,
        lease: NodeExecutionLeaseV2,
        error: Exception,
    ) -> None:
        """Return a stale member to a durable dependency barrier.

        This path deliberately never enters provider preparation/submission and
        never creates a manual-node wait.  The next scheduler wave refreshes
        the member intent after the shared prompt-ready authority publishes
        current evidence.
        """

        now = self._clock()
        details = dict(getattr(error, "details", {}))
        source_node_ids = tuple(
            str(item)
            for item in details.get("source_node_ids", ())
            if isinstance(item, str) and item
        )
        updated = self._runtime.update_member(
            lease.execution_id,
            lease.node_id,
            state="waiting",
            phase="blocked_by_upstream",
            waiting_for_node_ids=source_node_ids,
            now=now,
            error=None,
            event_type="execution_member_dependency_barrier",
            event_payload={
                "node_id": lease.node_id,
                "source_node_ids": list(source_node_ids),
                "reason": details.get("reason", "dependency_snapshot_changed"),
                "lease_generation": lease.generation,
            },
            expected_lease_generation=lease.generation,
        )
        try:
            if updated and self._run_snapshots is not None:
                refreshed_node = None
                if "prompt_evidence_digest_stale" in details.get("reasons", ()):
                    node = self._workflows.get_node(workflow_id, lease.node_id)
                    operation_id = node.prompt_preparation.operation_id
                    if operation_id is None:
                        raise V2PersistenceError(
                            "node_prompt_preparation_conflict",
                            "Stale prompt evidence has no preparation operation identity.",
                            stage="agent_canvas_scheduler",
                        )
                    # Only a ready projection can be recompiled in place.  A
                    # source publication may already have queued its successor;
                    # in that case the durable dispatch worker owns the next
                    # preparation wave.
                    if node.prompt_preparation.status == "ready":
                        refreshed_node = self._prompt_preparation.refresh_dependency_evidence(
                            workflow_id,
                            lease.node_id,
                            operation_id=operation_id,
                        )
                self._run_snapshots.refresh_member_intent(
                    lease.execution_id,
                    lease.node_id,
                    now=now,
                )
                if refreshed_node is not None:
                    self._runtime.update_member(
                        lease.execution_id,
                        lease.node_id,
                        state="waiting",
                        phase="blocked_by_upstream",
                        waiting_for_node_ids=source_node_ids,
                        now=now,
                        event_type="execution_member_dependency_barrier_reprepared",
                        event_payload={
                            "node_id": lease.node_id,
                            "node_revision": refreshed_node.revision,
                            "prompt_evidence_digest": (
                                refreshed_node.prompt_preparation.assertion_evidence.evidence_digest
                                if refreshed_node.prompt_preparation.assertion_evidence is not None
                                else None
                            ),
                        },
                        expected_lease_generation=lease.generation,
                    )
        except Exception as reconciliation_error:  # noqa: BLE001 - persist typed wait.
            error_code = getattr(
                reconciliation_error,
                "code",
                "execution_dependency_barrier_reconciliation_failed",
            )
            self._runtime.update_member(
                lease.execution_id,
                lease.node_id,
                state="waiting",
                phase="blocked_by_upstream",
                waiting_for_node_ids=source_node_ids,
                now=self._clock(),
                error=CanvasNodeErrorV2(
                    code=str(error_code)[:160],
                    message="Dependency barrier reconciliation is retryable.",
                    retryable=True,
                ),
                event_type="execution_member_dependency_barrier_retryable",
                event_payload={
                    "node_id": lease.node_id,
                    "source_node_ids": list(source_node_ids),
                    "error_code": str(error_code)[:160],
                },
                expected_lease_generation=lease.generation,
            )
        finally:
            # Reconciliation must never strand the execution lease, even when
            # a snapshot refresh or prompt successor write fails.
            self._runtime.complete_lease(lease, now=self._clock())

    def _assert_current_dependency_fence(
        self,
        workflow_id: str,
        execution_id: str,
        node_id: str,
        context: NodeExecutionContext,
    ) -> None:
        """Validate immutable admission inputs against the latest workflow.

        The check runs after prompt compilation and immediately before the
        dispatcher is allowed to prepare/submit provider work.  Any changed
        source revision, AssetVersion, occurrence mapping, or prompt evidence
        becomes a typed barrier instead of a provider task.
        """

        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        reasons: list[str] = []
        source_node_ids: set[str] = set()
        current_node = nodes.get(node_id)
        observed_revision = context.authoring_revision_observed or context.node.revision
        frozen_target_revision = context.authoring_revision_observed is not None and (
            context.authoring_revision_observed != context.node.revision
        )
        if current_node is None:
            reasons.append("target_node_missing")
        elif current_node.revision != observed_revision:
            reasons.append("target_node_revision_changed")
        elif not frozen_target_revision and (
            current_node.prompt_preparation.operation_id
            != context.node.prompt_preparation.operation_id
        ):
            reasons.append("target_prompt_operation_changed")
        elif not frozen_target_revision and (
            current_node.prompt_preparation.prompt_digest
            != context.node.prompt_preparation.prompt_digest
            or current_node.prompt_preparation.binding_digest
            != context.node.prompt_preparation.binding_digest
            or current_node.prompt_preparation.recipe_digest
            != context.node.prompt_preparation.recipe_digest
            or current_node.prompt_preparation.style_projection_digest
            != context.node.prompt_preparation.style_projection_digest
            or current_node.prompt_preparation.brief_digest
            != context.node.prompt_preparation.brief_digest
            or current_node.prompt_preparation.context_snapshot_id
            != context.node.prompt_preparation.context_snapshot_id
        ):
            reasons.append("target_prompt_evidence_changed")
        elif not frozen_target_revision and (
            current_node.prompt_preparation.occurrence_id
            != context.node.prompt_preparation.occurrence_id
            or current_node.prompt_preparation.character_phase
            != context.node.prompt_preparation.character_phase
            or current_node.metadata.get("occurrence_id")
            != context.node.metadata.get("occurrence_id")
            or current_node.metadata.get("character_phase")
            != context.node.metadata.get("character_phase")
        ):
            reasons.append("target_occurrence_mapping_changed")
        else:
            current_evidence = current_node.prompt_preparation.assertion_evidence
            frozen_evidence = context.node.prompt_preparation.assertion_evidence
            current_evidence_digest = (
                current_evidence.evidence_digest if current_evidence is not None else None
            )
            frozen_evidence_digest = (
                frozen_evidence.evidence_digest if frozen_evidence is not None else None
            )
            if current_evidence_digest != frozen_evidence_digest:
                reasons.append("target_prompt_evidence_changed")

        manifest = context.input_manifest
        if manifest is not None:
            inputs = (*manifest.text_inputs, *manifest.media_inputs, *manifest.world_setting_inputs)
            for item in inputs:
                source_id = getattr(item, "source_node_id", None)
                if not source_id:
                    continue
                source_node_ids.add(source_id)
                source = nodes.get(source_id)
                expected_revision = getattr(item, "source_node_revision", None)
                if source is None or (
                    expected_revision is not None and source.revision != expected_revision
                ):
                    reasons.append("source_node_revision_changed")
                if source is not None:
                    metadata = getattr(item, "binding_metadata", {})
                    if metadata.get("explicit_occurrence_mapping") is True and metadata.get(
                        "occurrence_id"
                    ) != source.metadata.get("occurrence_id"):
                        reasons.append("occurrence_mapping_changed")
                    if source.output_asset_id and hasattr(item, "asset_id"):
                        if item.asset_id != source.output_asset_id:
                            reasons.append("source_asset_changed")
                        current_asset = next(
                            (
                                asset
                                for asset in workflow.assets
                                if asset.asset_id == source.output_asset_id
                            ),
                            None,
                        )
                        if (
                            current_asset is not None
                            and getattr(item, "asset_version_id", None) is not None
                            and current_asset.version_id != item.asset_version_id
                        ):
                            reasons.append("source_asset_version_changed")

        if current_node is not None and (
            current_node.prompt_preparation.role_variant
            or current_node.prompt_preparation.recipe_id
            or current_node.metadata.get("prompt_recipe_id")
        ):
            evidence = current_node.prompt_preparation.assertion_evidence
            if evidence is None:
                reasons.append("prompt_evidence_missing")
            else:
                try:
                    current_sources = current_source_snapshots_for_evidence(
                        evidence,
                        workflow,
                    )
                except V2PersistenceError:
                    reasons.append("prompt_evidence_sources_unavailable")
                else:
                    if any(
                        expected.source_node_revision != current.source_node_revision
                        or (expected.asset_id is not None and expected.asset_id != current.asset_id)
                        or (
                            expected.asset_version_id is not None
                            and expected.asset_version_id != current.asset_version_id
                        )
                        for expected, current in zip(
                            evidence.source_snapshots,
                            current_sources,
                            strict=True,
                        )
                    ):
                        reasons.append("prompt_evidence_digest_stale")

        if reasons:
            raise V2PersistenceError(
                "execution_dependency_barrier_pending",
                "Execution admission is waiting for the current dependency wave.",
                stage="agent_canvas_scheduler",
                details={
                    "retryable": True,
                    "reason": reasons[0],
                    "reasons": sorted(set(reasons)),
                    "source_node_ids": sorted(source_node_ids),
                },
            )

    def _execute_member(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        started_at = self._clock()
        try:
            outcome = self._dispatcher.execute(context)
        except Exception as error:
            self._trace_stage(
                context,
                "provider_call",
                status="failed",
                error=error,
                started_at=started_at,
            )
            raise
        self._trace_stage(
            context,
            "provider_call",
            status=("waiting" if outcome.provider_task_id is not None else "completed"),
            started_at=started_at,
        )
        return outcome

    def _execute_member_guarded(
        self,
        lease: NodeExecutionLeaseV2,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        return self._leases.guard(lease).run(lambda: self._execute_member(context))

    def _complete_member(
        self,
        workflow_id: str,
        lease: NodeExecutionLeaseV2,
        context: NodeExecutionContext,
        outcome: NodeExecutionOutcome,
    ) -> None:
        now = self._clock()
        self._leases.assert_current(lease)
        execution_id = lease.execution_id
        node_id = lease.node_id
        if outcome.provider_task_id is not None:
            self._runtime.put_provider_task(
                CanvasProviderTaskV2(
                    task_id=outcome.provider_task_id,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node_id,
                    submission_intent_id=outcome.submission_intent_id,
                    provider=outcome.provider or "configured",
                    remote_task_id=outcome.remote_task_id,
                    status="submitted",
                    lease_generation=lease.generation,
                    next_poll_at=now,
                    recovery_deadline=now + timedelta(hours=1),
                    result_descriptor={
                        **(outcome.result_descriptor or {}),
                        **(
                            {
                                "parameter_compilation_snapshot_id": (
                                    context.effective_parameters.parameter_compilation_snapshot_id
                                ),
                                "requested_parameters": (context.effective_parameters.requested),
                                "effective_parameters": (context.effective_parameters.effective),
                            }
                            if context.effective_parameters is not None
                            and context.effective_parameters.parameter_compilation_snapshot_id
                            else {}
                        ),
                        **(
                            {"model_resolution": context.model_resolution.model_dump(mode="json")}
                            if context.model_resolution is not None
                            else {}
                        ),
                    },
                ),
                now=now,
            )
            member = next(
                item for item in self._runtime.list_members(execution_id) if item.node_id == node_id
            )
            if not self._state_machine.transition_member(
                self._runtime,
                member,
                state="running",
                phase="waiting_provider",
                provider_task_id=outcome.provider_task_id,
                now=now,
                event_type="provider_task_submitted",
                event_payload={
                    "provider_task_id": outcome.provider_task_id,
                    "remote_task_id": outcome.remote_task_id,
                    "model_resolution": (
                        context.model_resolution.model_dump(mode="json")
                        if context.model_resolution is not None
                        else None
                    ),
                    "parameter_compilation_snapshot_id": (
                        context.effective_parameters.parameter_compilation_snapshot_id
                        if context.effective_parameters is not None
                        else None
                    ),
                },
                expected_lease_generation=lease.generation,
            ):
                self._runtime.complete_lease(lease, now=now)
                return
            self._runtime.complete_lease(lease, now=now)
            return
        if self._output_preparer is not None and self._result_committer is not None:
            fingerprint = _execution_fingerprint(context)
            prepared = self._output_preparer.prepare(
                context,
                outcome,
                fingerprint=fingerprint,
            )
            member = next(
                item for item in self._runtime.list_members(execution_id) if item.node_id == node_id
            )
            self._result_committer.commit(
                CanvasExecutionResultCommitCommandV2(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    member_id=member.member_id,
                    node_id=node_id,
                    lease_owner_id=lease.owner_id,
                    lease_generation=lease.generation,
                    logical_result_key=prepared.logical_result_key,
                    payload_digest=prepared.payload_digest,
                    provider_task_id=outcome.provider_task_id,
                    outcome="succeeded",
                    prepared_result=prepared,
                    committed_at=now,
                )
            )
            return
        asset_id = None
        if outcome.media is not None:
            fingerprint = _execution_fingerprint(context)
            publication_started_at = self._clock()
            try:
                asset_id = self._media_publisher(context, outcome.media, fingerprint)
            except Exception as error:
                self._trace_stage(
                    context,
                    "publication",
                    status="failed",
                    error=error,
                    started_at=publication_started_at,
                )
                raise
            self._trace_stage(
                context,
                "publication",
                status="completed",
                started_at=publication_started_at,
                extra={"asset_id": asset_id},
            )
        member = next(
            item for item in self._runtime.list_members(execution_id) if item.node_id == node_id
        )
        if not self._state_machine.transition_member(
            self._runtime,
            member,
            state="succeeded",
            phase=None,
            now=now,
            expected_lease_generation=lease.generation,
        ):
            self._runtime.complete_lease(lease, now=now)
            return
        published_node = self._workflows.publish_node_output(
            workflow_id,
            node_id,
            execution_id=execution_id,
            updated_at=now,
            output_asset_id=asset_id,
            structured_content=outcome.structured_content,
        )
        if context.node.node_type == "script" and self._script_ready_publisher is not None:
            self._script_ready_publisher(workflow_id, node_id)
        if context.node.node_type == "text" and self._text_ready_publisher is not None:
            self._text_ready_publisher(published_node)
        if (
            context.node.node_type in {"image", "video", "audio"}
            and self._media_ready_publisher is not None
        ):
            self._media_ready_publisher(published_node)
        self._runtime.complete_lease(lease, now=now)

    def _trace_stage(
        self,
        context: NodeExecutionContext,
        stage: str,
        *,
        status: str,
        started_at: datetime,
        error: Exception | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        if self._stage_trace_writer is None:
            return
        output: dict[str, object] = {
            "status": status,
            "workflow_id": context.node.workflow_id,
            "execution_id": context.execution_id,
            "node_id": context.node.node_id,
            "node_run_id": (
                context.input_manifest.node_run_id
                if context.input_manifest is not None
                else f"node_run_{context.execution_id}_{context.node.node_id}"
            ),
            **(extra or {}),
        }
        if context.world_setting is not None:
            output["world_setting_context"] = {
                "source_node_id": context.world_setting.source_node_id,
                "source_node_revision": context.world_setting.source_node_revision,
                "source_content_digest": context.world_setting.source_content_digest,
                "source_core_digest": context.world_setting.source_core_digest,
                "target_audience": context.world_setting.target_audience,
                "compiler_id": context.world_setting.compiler_id,
                "compiler_digest": context.world_setting.compiler_digest,
                "context_digest": context.world_setting.context_digest,
            }
        finished_at = self._clock()
        try:
            self._stage_trace_writer(
                context,
                stage,
                output,
                str(error)[:1_024] if error is not None else None,
                started_at,
                finished_at,
            )
        except Exception:
            return

    def _fail_member(
        self,
        workflow_id: str,
        lease: NodeExecutionLeaseV2,
        error: Exception,
    ) -> None:
        now = self._clock()
        detail = safe_execution_error(error, default_code="node_execution_failed")
        member = next(
            item
            for item in self._runtime.list_members(lease.execution_id)
            if item.node_id == lease.node_id
        )
        if self._result_committer is not None:
            failure_key = f"{lease.execution_id}:{lease.node_id}:{lease.generation}:failed"
            failure_digest = hashlib.sha256(detail.model_dump_json().encode()).hexdigest()
            try:
                self._result_committer.commit(
                    CanvasExecutionResultCommitCommandV2(
                        workflow_id=workflow_id,
                        execution_id=lease.execution_id,
                        member_id=member.member_id,
                        node_id=lease.node_id,
                        lease_owner_id=lease.owner_id,
                        lease_generation=lease.generation,
                        logical_result_key=failure_key,
                        payload_digest=failure_digest,
                        provider_task_id=member.provider_task_id,
                        outcome="failed",
                        error=detail,
                        committed_at=now,
                    )
                )
            except V2PersistenceError as commit_error:
                if commit_error.code != "stale_execution_lease":
                    raise
            self._reconcile_terminal_member(
                workflow_id,
                member,
                detail,
            )
            return
        if member.state == "succeeded" or not self._state_machine.transition_member(
            self._runtime,
            member,
            state="failed",
            phase=None,
            now=now,
            error=detail,
            expected_lease_generation=lease.generation,
        ):
            self._runtime.complete_lease(lease, now=now)
            return
        self._reconcile_terminal_member(workflow_id, member, detail)
        self._workflows.set_node_runtime_state(
            workflow_id,
            lease.node_id,
            status="failed",
            updated_at=now,
            error=detail,
            execution_id=lease.execution_id,
            event_type="node_failed",
            event_payload={
                "code": detail.code,
                "stage": getattr(error, "stage", None),
                "details": getattr(error, "details", {}),
            },
        )
        self._runtime.complete_lease(lease, now=now)

    def _reconcile_terminal_member(
        self,
        workflow_id: str,
        member: CanvasExecutionMembershipV2,
        error: CanvasNodeErrorV2,
    ) -> None:
        if self._terminal_member_reconciler is None:
            return
        self._terminal_member_reconciler(
            workflow_id=workflow_id,
            execution_id=member.execution_id,
            member_id=member.member_id,
            node_id=member.node_id,
            error_code=error.code,
            retryable=error.retryable,
        )

    def _finish_if_quiescent(self, execution_id: str) -> None:
        self._state_machine.reconcile(
            self._runtime,
            execution_id,
            now=self._clock(),
        )

    def _cancel_members(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        reason: str = "user_cancelled",
    ) -> tuple[str, ...]:
        cancelled = []
        now = self._clock()
        for task in self._runtime.list_provider_tasks(
            execution_id=execution_id,
            statuses=("submitted", "waiting", "recovering"),
        ):
            self._runtime.put_provider_task(
                task.model_copy(
                    update={
                        "status": "cancelled",
                        "next_poll_at": None,
                        "error": CanvasNodeErrorV2(
                            code="provider_task_cancelled",
                            message=reason,
                            retryable=True,
                        ),
                    }
                ),
                now=now,
            )
        for member in self._runtime.list_members(execution_id):
            if member.state in {
                "succeeded",
                "failed",
                "blocked",
                "skipped_dependency",
                "cancelled",
            }:
                continue
            cancelled.append(member.node_id)
            self._runtime.update_member(
                execution_id,
                member.node_id,
                state="cancelled",
                phase=None,
                now=now,
                event_type="node_run_cancelled",
                event_payload={"reason": reason},
            )
            self._workflows.set_node_runtime_state(
                workflow_id,
                member.node_id,
                status="draft",
                updated_at=now,
                execution_id=execution_id,
                event_type="node_cancelled",
                event_payload={"reason": reason},
            )
        self._runtime.set_execution_status(
            execution_id,
            "cancelled",
            now=now,
            event_type="execution_cancelled",
            payload={"reason": reason},
        )
        return tuple(cancelled)

    def _runtime_event_cursor(self, workflow_id: str) -> int:
        return self._runtime.event_cursor(workflow_id)


class CanvasRuntimeSnapshotService:
    """Build runtime state from canonical nodes and durable execution members."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
        events: EventRepository,
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._events = events

    def get(self, workflow_id: str) -> CanvasRuntimeSnapshotV2:
        workflow = self._workflows.get_workflow(workflow_id)
        active = self._runtime.get_active_execution(workflow_id)
        members = {
            item.node_id: item
            for item in (
                self._runtime.list_members(active.execution_id)
                if active
                else self._runtime.list_latest_members_for_workflow(workflow_id)
            )
        }
        runtime = {
            node.node_id: NodeRuntimeV2(
                node_id=node.node_id,
                visible_status=node.status,
                phase=members[node.node_id].phase if node.node_id in members else None,
                execution_id=(
                    members[node.node_id].execution_id if node.node_id in members else None
                ),
                provider_task_id=(
                    members[node.node_id].provider_task_id if node.node_id in members else None
                ),
                run_intent_snapshot_id=(
                    members[node.node_id].run_intent_snapshot_id
                    if node.node_id in members
                    else None
                ),
                parameter_compilation_snapshot_id=(
                    members[node.node_id].parameter_compilation_snapshot_id
                    if node.node_id in members
                    else None
                ),
                input_manifest_id=(
                    (
                        members[node.node_id].resolved_input_manifest_id
                        or _input_manifest_id(members[node.node_id])
                    )
                    if node.node_id in members
                    else None
                ),
                effective_parameters=(
                    members[node.node_id].effective_parameters.effective
                    if node.node_id in members
                    and members[node.node_id].effective_parameters is not None
                    else {}
                ),
                normalizations=(
                    members[node.node_id].effective_parameters.normalizations
                    if node.node_id in members
                    and members[node.node_id].effective_parameters is not None
                    else ()
                ),
                omitted_optional_inputs=(
                    members[node.node_id].omitted_optional_inputs if node.node_id in members else ()
                ),
                waiting_reason=(
                    members[node.node_id].phase
                    if node.node_id in members
                    and members[node.node_id].phase == "waiting_for_input"
                    else None
                ),
                missing_required_source_node_ids=(
                    members[node.node_id].waiting_for_node_ids
                    if node.node_id in members
                    and members[node.node_id].phase == "waiting_for_input"
                    else ()
                ),
                waiting_for_node_ids=(
                    members[node.node_id].waiting_for_node_ids if node.node_id in members else ()
                ),
                blocked_by_node_ids=(
                    members[node.node_id].waiting_for_node_ids
                    if node.node_id in members
                    and members[node.node_id].state in {"blocked", "skipped_dependency"}
                    else ()
                ),
                attempt_no=members[node.node_id].attempt_no if node.node_id in members else 0,
                updated_at=node.updated_at,
                error=node.error,
            )
            for node in workflow.nodes
        }
        return CanvasRuntimeSnapshotV2(
            workflow_id=workflow_id,
            active_execution_id=active.execution_id if active else None,
            execution_status=active.status if active else None,
            node_runtime=runtime,
            queued_node_ids=_ids(runtime, phase="queued"),
            working_node_ids=tuple(
                node_id for node_id, item in runtime.items() if item.visible_status == "working"
            ),
            waiting_node_ids=_ids(runtime, phase="waiting_for_input"),
            ready_node_ids=tuple(
                node_id for node_id, item in runtime.items() if item.visible_status == "ready"
            ),
            failed_node_ids=tuple(
                node_id for node_id, item in runtime.items() if item.visible_status == "failed"
            ),
            events_cursor=self._events.max_seq(workflow_id),
        )


def _skip_reason(node: CanvasNodeV2, request: CanvasRunRequestV2) -> str | None:
    if getattr(node, "execution_mode", "generative") == "source_only":
        return "source_only_node_not_runnable"
    if node.node_type == "editing":
        return "node_not_runnable"
    if node.status == "ready":
        return "node_already_ready"
    if node.status == "working":
        return "node_already_working"
    if node.status == "failed" and not request.retry_failed:
        return "failed_node_retry_required"
    if node.prompt_preparation.status != "ready":
        return "node_prompt_preparation_incomplete"
    assertion_error = prompt_assertion_admission_error(node)
    if assertion_error is not None:
        return assertion_error
    if not _prompt_recipe_is_current(node):
        return "node_prompt_assertion_contract_invalid"
    return None


def _skip_message(reason: str) -> str:
    return {
        "source_only_node_not_runnable": "Source-only nodes cannot be run.",
        "node_not_runnable": "Node type cannot be run.",
        "node_already_ready": "Ready nodes are not rerun in place.",
        "node_already_working": "Working nodes are already executing.",
        "failed_node_retry_required": "Failed nodes require explicit retry.",
        "node_prompt_preparation_incomplete": "Node prompt preparation is not ready.",
        "node_prompt_assertion_evidence_missing": "Current prompt assertion evidence is required.",
        "node_prompt_assertion_contract_invalid": "Prompt assertion evidence does not match current authority.",
    }[reason]


def _prompt_recipe_is_current(node: CanvasNodeV2) -> bool:
    preparation = node.prompt_preparation
    if preparation.role_variant is None:
        return True
    try:
        recipe = RolePromptRecipeRegistry().resolve(preparation.role_variant)
        AgentCanvasRoleReferencePolicyService().for_prompt_variant(preparation.role_variant)
    except V2PersistenceError:
        return False
    return (
        preparation.recipe_id == recipe.recipe_id
        and preparation.recipe_version == recipe.recipe_version
        and preparation.recipe_digest == recipe.recipe_digest
    )


def _public_world_setting_input(
    item: WorldSettingResolvedInputV2,
) -> dict[str, object]:
    return {
        "binding_id": item.binding_id,
        "source_node_id": item.source_node_id,
        "source_node_revision": item.source_node_revision,
        "source_content_digest": item.source_content_digest,
        "source_core_digest": item.source_core_digest,
        "required": item.required,
        "display_order": item.display_order,
        "target_audience": item.target_audience,
        "compiler_id": item.compiler_id,
        "compiler_digest": item.compiler_digest,
        "context_digest": item.context_digest,
    }


def _public_input_manifest(manifest: ResolvedNodeInputManifestV2) -> dict[str, object]:
    payload = manifest.model_dump(mode="json")
    payload["world_setting_inputs"] = [
        _public_world_setting_input(item) for item in manifest.world_setting_inputs
    ]
    return payload


def _required_sources_not_ready(workflow, target_node_id, nodes) -> tuple[str, ...]:
    return tuple(
        binding.source.source_node_id
        for binding in _unready_required_bindings(workflow, target_node_id, nodes)
    )


def _frozen_unready_sources(
    member: CanvasExecutionMembershipV2,
    nodes: dict[str, CanvasNodeV2],
    *,
    required: bool,
) -> tuple[str, ...]:
    snapshot = member.run_intent_snapshot
    if snapshot is None:
        return ()
    return tuple(
        binding.source_id
        for binding in snapshot.binding_snapshots
        if binding.required is required
        and binding.source_kind == "node_output"
        and not _node_output_source_is_ready(
            source=nodes.get(binding.source_id),
            input_role=binding.input_role,
        )
    )


def _same_wave_dependency_sources(
    member: CanvasExecutionMembershipV2,
    members_by_node: dict[str, CanvasExecutionMembershipV2],
) -> tuple[str, ...]:
    """Fence a downstream member behind unfinished source members.

    A source Node may still be ``ready`` from an earlier publication while its
    current execution member is queued or running a newer revision.  Treating
    that source as ready here would place both members in one dispatch wave and
    let the downstream provider observe the old prompt evidence.
    """

    snapshot = member.run_intent_snapshot
    if snapshot is None:
        return ()
    return tuple(
        binding.source_id
        for binding in snapshot.binding_snapshots
        if binding.source_kind == "node_output"
        and (source_member := members_by_node.get(binding.source_id)) is not None
        and source_member.state in {"queued", "waiting", "running"}
    )


def _unready_required_bindings(workflow, target_node_id, nodes):
    waiting = []
    for binding in workflow.bindings:
        if (
            binding.target_node_id != target_node_id
            or not binding.required
            or not binding.enabled
            or binding.source.kind != "node_output"
        ):
            continue
        source = nodes.get(binding.source.source_node_id)
        if not _node_output_source_is_ready(
            source=source,
            input_role=binding.input_role,
        ):
            waiting.append(binding)
    return tuple(waiting)


def _node_output_source_is_ready(
    *,
    source: CanvasNodeV2 | None,
    input_role: str,
) -> bool:
    if source is None:
        return False
    if source.status == "ready":
        return True
    return (
        input_role == "text_context"
        and source.node_type in {"text", "script"}
        and source.status == "draft"
        and bool(source.structured_content)
    )


def _prompt_preparation_pending(node: CanvasNodeV2 | None) -> bool:
    """Return whether a managed Draft is waiting on durable prompt work."""

    if node is None or node.node_type not in {"text", "script", "image", "video", "audio"}:
        return False
    preparation = node.prompt_preparation
    managed = bool(
        preparation.role_variant
        or preparation.recipe_id
        or node.metadata.get("prompt_recipe_id")
    )
    return managed and preparation.status in {"queued", "working"}


def _prompt_preparation_waiting_sources(
    member: CanvasExecutionMembershipV2,
) -> tuple[str, ...]:
    """Expose only dependency node IDs for a prompt-preparation barrier."""

    snapshot = member.run_intent_snapshot
    if snapshot is None:
        return ()
    return tuple(
        dict.fromkeys(
            binding.source_id
            for binding in snapshot.binding_snapshots
            if binding.source_kind == "node_output" and binding.source_id
        )
    )


def _parameter_compilation_revision_is_current(
    original: CanvasNodeV2,
    current: CanvasNodeV2,
    compiled: CompiledVideoParametersV2,
) -> bool:
    """Allow only the compiler's own derived-parameter revision bump."""

    if current.revision not in {original.revision, original.revision + 1}:
        return False
    for field in (
        "node_id",
        "workflow_id",
        "node_type",
        "creative_role",
        "role_contract_version",
        "title",
        "status",
        "execution_mode",
        "summary_prompt",
        "generation_prompt",
        "structured_content",
        "model_selection_mode",
        "model_ref",
        "metadata",
        "prompt_context_snapshot_id",
        "output_asset_id",
        "position",
        "error",
        "prompt_preparation",
        "variation_draft",
    ):
        if getattr(current, field) != getattr(original, field):
            return False
    if current.revision == original.revision:
        return (
            current.parameters == original.parameters
            and current.parameter_provenance == original.parameter_provenance
        )
    return (
        current.parameters == compiled.authoring_parameters
        and current.parameter_provenance == compiled.parameter_provenance
    )


def _fingerprint(request: CanvasRunRequestV2) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


def _execution_fingerprint(context: NodeExecutionContext) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "model_ref": (
                    context.model_resolution.model_ref
                    if context.model_resolution is not None
                    else None
                ),
                "inputs": [str(item) for item in context.inputs],
                "prompt_digest": (
                    context.compiled_prompt.prompt_digest
                    if context.compiled_prompt is not None
                    else None
                ),
                "reference_bundle_digest": (
                    context.reference_bundle.bundle_digest
                    if context.reference_bundle is not None
                    else None
                ),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _ids(
    runtime: dict[str, NodeRuntimeV2],
    *,
    phase: str,
) -> tuple[str, ...]:
    return tuple(node_id for node_id, item in runtime.items() if item.phase == phase)


def _input_manifest_id(member: CanvasExecutionMembershipV2) -> str | None:
    manifest = member.prompt_metadata.get("resolved_input_manifest")
    if not isinstance(manifest, dict):
        return None
    value = manifest.get("manifest_id")
    return value if isinstance(value, str) and value else None


def _run_error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_runtime",
        details=details,
    )
