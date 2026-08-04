"""Central state derivation for durable Agent Canvas executions."""

from __future__ import annotations

from datetime import datetime

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import CanvasExecutionMembershipV2


class AgentCanvasExecutionStateMachine:
    """Derive execution state from durable member state without phase shortcuts."""

    def derive_execution(
        self,
        members: tuple[CanvasExecutionMembershipV2, ...],
    ) -> str:
        if any(
            member.state == "waiting"
            or (
                member.state == "running"
                and member.phase in {"waiting_provider", "recovering", "publishing"}
            )
            for member in members
        ):
            return "waiting"
        if any(member.state in {"queued", "running"} for member in members):
            return "running"
        if not members:
            return "completed"
        succeeded = sum(member.state == "succeeded" for member in members)
        if succeeded == len(members):
            return "completed"
        if succeeded:
            return "partial_completed"
        if all(member.state == "cancelled" for member in members):
            return "cancelled"
        return "failed"

    def transition_member(
        self,
        runtime: AgentCanvasRuntimeRepository,
        member: CanvasExecutionMembershipV2,
        *,
        state: str,
        phase: str | None,
        now: datetime,
        provider_task_id: str | None = None,
        error: CanvasNodeErrorV2 | None = None,
        event_type: str | None = None,
        event_payload: dict[str, object] | None = None,
        expected_lease_generation: int | None = None,
    ) -> bool:
        """Apply a member transition only while its durable identity is current."""

        return runtime.update_member(
            member.execution_id,
            member.node_id,
            state=state,
            phase=phase,
            provider_task_id=(
                provider_task_id if provider_task_id is not None else member.provider_task_id
            ),
            now=now,
            error=error,
            event_type=event_type,
            event_payload=event_payload,
            expected_state=member.state,
            expected_phase=member.phase,
            expected_lease_generation=expected_lease_generation,
            expected_provider_task_id=member.provider_task_id,
            validate_expected_phase=True,
            validate_expected_provider_task_id=True,
        )

    def reconcile(
        self,
        runtime: AgentCanvasRuntimeRepository,
        execution_id: str,
        *,
        now: datetime,
        workflows: AgentCanvasWorkflowRepository | None = None,
    ) -> str:
        """Persist a truthful execution state when member transitions settle."""

        execution = runtime.get_execution(execution_id)
        members = runtime.list_members(execution_id)
        if workflows is not None:
            for member in members:
                node = workflows.get_node(member.workflow_id, member.node_id)
                if (
                    member.state == "succeeded"
                    or node.status != "ready"
                    or not node.output_asset_id
                ):
                    continue
                self.transition_member(
                    runtime,
                    member,
                    state="succeeded",
                    phase=None,
                    now=now,
                )
            members = runtime.list_members(execution_id)
        derived = self.derive_execution(members)
        if execution.status != derived:
            event_type = {
                "completed": "execution_completed",
                "partial_completed": "execution_partial_completed",
                "failed": "execution_failed",
            }.get(derived, "execution_reconciled")
            runtime.set_execution_status(
                execution_id,
                derived,
                now=now,
                event_type=event_type,
                payload={"before_status": execution.status, "after_status": derived},
            )
        return derived
