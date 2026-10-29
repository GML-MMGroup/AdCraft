"""Build the same recoverable task before and after scheduler handoff."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.schemas.agent_canvas_runtime import CanvasProviderTaskV2, NodeExecutionLeaseV2

if TYPE_CHECKING:
    from app.services.agent_canvas_node_execution import NodeExecutionContext, NodeExecutionOutcome


def provider_task_checkpoint(
    context: "NodeExecutionContext",
    outcome: "NodeExecutionOutcome",
    lease: NodeExecutionLeaseV2,
    *,
    now: datetime,
) -> CanvasProviderTaskV2:
    if outcome.provider_task_id is None:
        raise ValueError("A provider task checkpoint requires a task identity.")
    descriptor = dict(outcome.result_descriptor or {})
    if context.model_resolution is not None:
        descriptor["model_resolution"] = context.model_resolution.model_dump(mode="json")
    parameters = context.effective_parameters
    if parameters is not None and parameters.parameter_compilation_snapshot_id is not None:
        descriptor.update(
            parameter_compilation_snapshot_id=parameters.parameter_compilation_snapshot_id,
            requested_parameters=parameters.requested,
            effective_parameters=parameters.effective,
        )
    if context.seedance_input_audit is not None:
        descriptor["provider_payload"] = {
            **dict(descriptor.get("provider_payload") or {}),
            "seedance_input_manifest": context.seedance_input_audit.model_dump(mode="json"),
        }
    return CanvasProviderTaskV2(
        task_id=outcome.provider_task_id,
        workflow_id=context.node.workflow_id,
        execution_id=context.execution_id,
        node_id=context.node.node_id,
        submission_intent_id=outcome.submission_intent_id,
        provider=outcome.provider or "configured",
        remote_task_id=outcome.remote_task_id,
        status="submitted",
        lease_generation=lease.generation,
        next_poll_at=now,
        recovery_deadline=now + timedelta(hours=1),
        result_descriptor=descriptor,
    )
