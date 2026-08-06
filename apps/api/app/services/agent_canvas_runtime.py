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
from app.schemas.agent_canvas_world_setting import WorldSettingProjectionContextV1
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
from app.services.agent_canvas_execution_state import AgentCanvasExecutionStateMachine
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_run_snapshots import AgentCanvasRunIntentSnapshotService
from app.services.agent_canvas_world_setting_projection import WorldSettingProjectionService
from app.services.agent_canvas_video_parameter_compiler import (
    AgentCanvasVideoParameterCompiler,
)
from app.services.model_resolution import ModelResolutionService


MediaPublisher = Callable[[NodeExecutionContext, GeneratedMediaPayload, str], str]
ScriptReadyPublisher = Callable[[str, str], object]
TextReadyPublisher = Callable[[CanvasNodeV2], object]
MediaContextPreparer = Callable[
    [CanvasNodeV2, WorldSettingProjectionContextV1 | None],
    tuple[CompiledProviderPromptV2 | None, AdReferenceBundleV2 | None],
]
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
        now = self._clock()
        active = self._runtime.get_active_execution(workflow_id)
        if active is None:
            execution = self._runtime.create_execution(
                workflow_id=workflow_id,
                scope=request.scope,
                node_ids=tuple(accepted),
                idempotency_key=idempotency_key,
                request_fingerprint=_fingerprint(request),
                now=now,
            )
            joined: tuple[str, ...] = ()
        else:
            execution = active
            joined = self._runtime.add_members(
                active.execution_id,
                tuple(accepted),
                now=now,
            )
            accepted = [
                node_id
                for node_id in accepted
                if node_id
                not in {
                    member.node_id for member in self._runtime.list_members(active.execution_id)
                }
                or node_id in joined
            ]
        if self._run_snapshots is not None:
            freeze_node_ids = tuple(accepted) if active is None else joined
            self._run_snapshots.freeze_members(
                execution.execution_id,
                now=now,
                node_ids=freeze_node_ids,
            )
        members = self._runtime.list_members(execution.execution_id)
        cursor = self._events.max_seq(workflow_id)
        return CanvasRunAcceptedV2(
            workflow_id=workflow_id,
            execution_id=execution.execution_id,
            status=execution.status,
            accepted_node_ids=tuple(accepted) if active is None else (),
            joined_node_ids=joined,
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
        media_context_preparer: MediaContextPreparer | None = None,
        stage_trace_writer: StageTraceWriter | None = None,
        input_compiler: AgentCanvasResolvedInputCompiler | None = None,
        run_snapshots: AgentCanvasRunIntentSnapshotService | None = None,
        execution_parameters: AgentCanvasExecutionParameterResolver | None = None,
        video_parameter_compiler: AgentCanvasVideoParameterCompiler | None = None,
        world_settings: WorldSettingProjectionService | None = None,
        state_machine: AgentCanvasExecutionStateMachine | None = None,
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
        self._media_context_preparer = media_context_preparer
        self._stage_trace_writer = stage_trace_writer
        self._world_settings = world_settings
        self._input_compiler = input_compiler or AgentCanvasResolvedInputCompiler(
            bindings,
            world_settings=world_settings,
        )
        self._run_snapshots = run_snapshots
        self._execution_parameters = execution_parameters or AgentCanvasExecutionParameterResolver()
        self._video_parameter_compiler = video_parameter_compiler
        self._state_machine = state_machine or AgentCanvasExecutionStateMachine()
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
                prepared_contexts: list[tuple[NodeExecutionLeaseV2, NodeExecutionContext]] = []
                for lease in leases:
                    try:
                        context = self._prepare_member(
                            current.workflow_id,
                            lease.execution_id,
                            lease.node_id,
                        )
                    except Exception as error:
                        self._fail_member(current.workflow_id, lease, error)
                        continue
                    prepared_contexts.append((lease, context))
                prepared = []
                for lease, context in prepared_contexts:
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
                    self._workflows.set_node_runtime_state(
                        current.workflow_id,
                        lease.node_id,
                        status="working",
                        updated_at=self._clock(),
                        execution_id=lease.execution_id,
                        event_type="node_generation_started",
                        event_payload=event_payload,
                    )
                for lease, context in prepared_contexts:
                    prepared.append(
                        (
                            lease,
                            context,
                            executor.submit(self._execute_member, context),
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
            required_waiting = _frozen_unready_sources(member, nodes, required=True)
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
                    state="blocked" if blocked else "waiting",
                    phase="blocked_by_upstream" if blocked else "waiting_for_input",
                    waiting_for_node_ids=waiting,
                    now=self._clock(),
                    event_type=(
                        "node_blocked" if required_waiting else "node_waiting_for_preferred_input"
                    ),
                    event_payload={
                        "waiting_for_node_ids": list(waiting),
                        "blocked_by_node_ids": list(blocked),
                        "preferred_upstream_node_ids": list(preferred_waiting),
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
        frozen_node = member.prompt_metadata.get("frozen_node")
        node = (
            CanvasNodeV2.model_validate(frozen_node)
            if isinstance(frozen_node, dict)
            else self._workflows.get_node(workflow_id, node_id)
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
        inputs = self._input_compiler.materialize_inputs(manifest)
        if len(manifest.world_setting_inputs) > 1:
            raise V2PersistenceError(
                "world_setting_binding_ambiguous",
                "A target Node cannot resolve more than one World Setting Binding.",
                stage="agent_canvas_scheduler",
            )
        world_setting = None
        if manifest.world_setting_inputs:
            if self._world_settings is None:
                raise V2PersistenceError(
                    "world_setting_projection_unavailable",
                    "World Setting projection resolution is unavailable.",
                    stage="agent_canvas_scheduler",
                    details={"retryable": True},
                )
            world_setting = self._world_settings.materialize(manifest.world_setting_inputs[0])
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
            prompt_metadata["world_setting_projection"] = {
                "source_node_id": world_setting.source_node_id,
                "source_node_revision": world_setting.source_node_revision,
                "projection_snapshot_id": world_setting.projection_snapshot_id,
                "projection_digest": world_setting.projection_digest,
                "projection_mode": world_setting.projection_mode,
                "warning_code": world_setting.warning_code,
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
                    node = node.model_copy(
                        update={
                            "parameters": compiled.requested_parameters,
                            "parameter_provenance": compiled.parameter_provenance,
                        }
                    )
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
        context = NodeExecutionContext(
            execution_id=execution_id,
            node=node,
            inputs=inputs,
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
        if effective_parameters is not None and effective_parameters.normalizations:
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
                    "input_manifest": manifest.model_dump(mode="json"),
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
                        item.model_dump(mode="json") for item in manifest.world_setting_inputs
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

    def _complete_member(
        self,
        workflow_id: str,
        lease: NodeExecutionLeaseV2,
        context: NodeExecutionContext,
        outcome: NodeExecutionOutcome,
    ) -> None:
        now = self._clock()
        execution_id = lease.execution_id
        node_id = lease.node_id
        if outcome.provider_task_id is not None:
            self._runtime.put_provider_task(
                CanvasProviderTaskV2(
                    task_id=outcome.provider_task_id,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node_id,
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
            output["world_setting_projection"] = {
                "source_node_id": context.world_setting.source_node_id,
                "source_node_revision": context.world_setting.source_node_revision,
                "projection_snapshot_id": context.world_setting.projection_snapshot_id,
                "projection_digest": context.world_setting.projection_digest,
                "projection_mode": context.world_setting.projection_mode,
                "warning_code": context.world_setting.warning_code,
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
        detail = CanvasNodeErrorV2(
            code=getattr(error, "code", "node_execution_failed"),
            message=str(error),
            retryable=bool(getattr(error, "details", {}).get("retryable", False)),
        )
        member = next(
            item
            for item in self._runtime.list_members(lease.execution_id)
            if item.node_id == lease.node_id
        )
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
            if member.state in {"succeeded", "failed", "blocked", "cancelled"}:
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
                    if node.node_id in members and members[node.node_id].state == "blocked"
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
    if node.node_type == "editing":
        return "node_not_runnable"
    if node.status == "ready":
        return "node_already_ready"
    if node.status == "working":
        return "node_already_working"
    if node.status == "failed" and not request.retry_failed:
        return "failed_node_retry_required"
    return None


def _skip_message(reason: str) -> str:
    return {
        "node_not_runnable": "Node type cannot be run.",
        "node_already_ready": "Ready nodes are not rerun in place.",
        "node_already_working": "Working nodes are already executing.",
        "failed_node_retry_required": "Failed nodes require explicit retry.",
    }[reason]


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
        and ((source := nodes.get(binding.source_id)) is None or source.status != "ready")
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
        if source is None or source.status != "ready":
            waiting.append(binding)
    return tuple(waiting)


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
