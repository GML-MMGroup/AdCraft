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
    NodeExecutionLeaseV2,
    NodeRuntimeV2,
)
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_node_execution import (
    GeneratedMediaPayload,
    NodeExecutionContext,
    NodeExecutionDispatcher,
    NodeExecutionOutcome,
)
from app.services.agent_canvas_provider_capabilities import (
    ProviderCapabilityService,
)


MediaPublisher = Callable[[NodeExecutionContext, GeneratedMediaPayload, str], str]
ScriptReadyPublisher = Callable[[str, str], object]
MediaContextPreparer = Callable[
    [CanvasNodeV2],
    tuple[CompiledProviderPromptV2 | None, AdReferenceBundleV2 | None],
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
        eligibility_validator: RunEligibilityValidator | None = None,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._events = events
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
                    missing_node_ids = _required_sources_not_ready(workflow, node.node_id, nodes)
                    if missing_node_ids:
                        raise _run_error(
                            "upstream_inputs_not_ready",
                            "Required upstream inputs are not ready.",
                            details={"missing_node_ids": list(missing_node_ids)},
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
        media_publisher: MediaPublisher,
        script_ready_publisher: ScriptReadyPublisher | None = None,
        media_context_preparer: MediaContextPreparer | None = None,
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
        self._dispatcher = dispatcher
        self._media_publisher = media_publisher
        self._script_ready_publisher = script_ready_publisher
        self._media_context_preparer = media_context_preparer
        self._owner_id = owner_id or f"worker_{uuid4().hex}"
        self._limits = {
            "image": image_limit,
            "video": video_limit,
            "audio": audio_limit,
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
                        event_type="node_run_started",
                    )
                    self._workflows.set_node_runtime_state(
                        current.workflow_id,
                        lease.node_id,
                        status="working",
                        updated_at=self._clock(),
                        execution_id=lease.execution_id,
                        event_type="provider_execution_started",
                    )
                for lease, context in prepared_contexts:
                    prepared.append(
                        (
                            lease,
                            context,
                            executor.submit(self._dispatcher.execute, context),
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
        candidates: list[CanvasExecutionMembershipV2] = []
        for member in self._runtime.list_members(execution_id):
            if member.state not in {"queued", "waiting"}:
                continue
            waiting = _required_sources_not_ready(workflow, member.node_id, nodes)
            if waiting:
                blocked = tuple(
                    source_node_id
                    for source_node_id in waiting
                    if (source := nodes.get(source_node_id)) is None or source.status == "failed"
                )
                self._runtime.update_member(
                    execution_id,
                    member.node_id,
                    state="blocked" if blocked else "waiting",
                    phase="waiting_for_input",
                    waiting_for_node_ids=waiting,
                    now=self._clock(),
                    event_type="node_blocked" if blocked else "node_waiting_for_input",
                    event_payload={
                        "waiting_for_node_ids": list(waiting),
                        "blocked_by_node_ids": list(blocked),
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
        node = self._workflows.get_node(workflow_id, node_id)
        input_resolution = self._bindings.resolve_run_input_resolution(workflow_id, node_id)
        inputs = input_resolution.inputs
        model_id = None
        provider_id = None
        compiled_prompt = None
        reference_bundle = None
        prompt_metadata: dict[str, object] = {}
        if node.node_type in {"image", "video", "audio"}:
            capability = self._capabilities.resolve(node, inputs)
            model_id = capability.model_id
            provider_id = capability.provider
            if self._media_context_preparer is not None:
                compiled_prompt, reference_bundle = self._media_context_preparer(node)
                if compiled_prompt is not None:
                    prompt_metadata.update(
                        {
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
            compiled_prompt=compiled_prompt,
            reference_bundle=reference_bundle,
            optional_input_omissions=input_resolution.optional_omissions,
        )
        prepared = self._dispatcher.prepare(context)
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
                phase="preparing_provider",
                now=now,
                prompt_metadata=prompt_metadata,
                event_type="provider_inputs_resolved",
                event_payload={
                    "seedance_input_manifest": prepared.seedance_input_audit.model_dump(
                        mode="json"
                    ),
                    "optional_input_omissions": list(prepared.optional_input_omissions),
                },
            )
        elif prompt_metadata:
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="preparing_provider",
                now=now,
                prompt_metadata=prompt_metadata,
            )
        return prepared

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
                    result_descriptor=outcome.result_descriptor or {},
                ),
                now=now,
            )
            self._runtime.update_member(
                execution_id,
                node_id,
                state="running",
                phase="waiting_provider",
                provider_task_id=outcome.provider_task_id,
                now=now,
                event_type="provider_task_submitted",
                event_payload={
                    "provider_task_id": outcome.provider_task_id,
                    "remote_task_id": outcome.remote_task_id,
                },
            )
            return
        asset_id = None
        if outcome.media is not None:
            fingerprint = _execution_fingerprint(context)
            asset_id = self._media_publisher(context, outcome.media, fingerprint)
        self._workflows.publish_node_output(
            workflow_id,
            node_id,
            execution_id=execution_id,
            updated_at=now,
            output_asset_id=asset_id,
            structured_content=outcome.structured_content,
        )
        if context.node.node_type == "script" and self._script_ready_publisher is not None:
            self._script_ready_publisher(workflow_id, node_id)
        self._runtime.update_member(
            execution_id,
            node_id,
            state="succeeded",
            phase=None,
            now=now,
        )
        self._runtime.complete_lease(lease, now=now)

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
            retryable=False,
        )
        self._workflows.set_node_runtime_state(
            workflow_id,
            lease.node_id,
            status="failed",
            updated_at=now,
            error=detail,
            execution_id=lease.execution_id,
            event_type="node_failed",
            event_payload={"code": detail.code},
        )
        self._runtime.update_member(
            lease.execution_id,
            lease.node_id,
            state="failed",
            phase=None,
            now=now,
            error=detail,
        )
        self._runtime.complete_lease(lease, now=now)

    def _finish_if_quiescent(self, execution_id: str) -> None:
        members = self._runtime.list_members(execution_id)
        if any(
            member.state == "running"
            and member.phase in {"waiting_provider", "recovering", "publishing"}
            for member in members
        ):
            self._runtime.set_execution_status(
                execution_id,
                "waiting",
                now=self._clock(),
                event_type="execution_waiting",
            )
            return
        succeeded = sum(member.state == "succeeded" for member in members)
        failed_or_waiting = sum(
            member.state in {"failed", "waiting", "blocked", "queued"} for member in members
        )
        if not failed_or_waiting:
            status = "completed"
            event_type = "execution_completed"
        elif succeeded:
            status = "partial_completed"
            event_type = "execution_partial_completed"
        else:
            status = "failed"
            event_type = "execution_failed"
        self._runtime.set_execution_status(
            execution_id,
            status,
            now=self._clock(),
            event_type=event_type,
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
        members = (
            {item.node_id: item for item in self._runtime.list_members(active.execution_id)}
            if active
            else {}
        )
        runtime = {
            node.node_id: NodeRuntimeV2(
                node_id=node.node_id,
                visible_status=node.status,
                phase=members[node.node_id].phase if node.node_id in members else None,
                execution_id=active.execution_id if node.node_id in members and active else None,
                provider_task_id=(
                    members[node.node_id].provider_task_id if node.node_id in members else None
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
    if node.node_type in {"text", "editing"}:
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
    waiting = []
    for binding in workflow.bindings:
        if (
            binding.target_node_id != target_node_id
            or not binding.required
            or binding.source.kind != "node"
        ):
            continue
        source = nodes.get(binding.source.node_id)
        if source is None or source.status != "ready":
            waiting.append(binding.source.node_id)
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
                "model_id": context.model_id,
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
