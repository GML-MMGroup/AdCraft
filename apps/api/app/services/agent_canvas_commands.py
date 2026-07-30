"""Deterministic Agent Canvas command submission and application."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    AgentCommandSubmissionV2,
)
from app.schemas.agent_runtime import (
    AgentCommandPlanCreateV2,
    AgentCommandPlanV2,
    AgentCommandTransactionResultV2,
    AgentPrepareCompositionOperationV2,
    AgentPrepareCompositionResultV2,
)
from app.services.agent_canvas_composition_preparation import (
    AgentCanvasCompositionPreparationService,
)
from app.services.agent_canvas_command_replan import AgentCommandReplanService


RunNodes = Callable[[str, tuple[str, ...], str], tuple[str, ...]]


class AgentCanvasCommandService:
    """Apply immutable plans and enqueue provider work only after commit."""

    def __init__(
        self,
        repository: AgentCanvasCommandRepository,
        *,
        run_nodes: RunNodes | None = None,
        replan: AgentCommandReplanService | None = None,
        composition_preparation: AgentCanvasCompositionPreparationService | None = None,
    ) -> None:
        self._repository = repository
        self._run_nodes = run_nodes
        self._replan = replan
        self._composition_preparation = composition_preparation

    def submit(
        self,
        *,
        plan: AgentCommandPlanCreateV2,
        idempotency_key: str,
    ) -> AgentCommandSubmissionV2:
        persisted, _ = self._repository.create_or_get_plan(
            plan,
            idempotency_key=idempotency_key,
        )
        if persisted.status == "applied":
            return AgentCommandSubmissionV2(
                plan=persisted,
                receipt=self._repository.get_receipt_for_plan(persisted.plan_id),
            )
        if persisted.confirmation_required:
            return AgentCommandSubmissionV2(plan=persisted)
        receipt = self.apply(
            plan_id=persisted.plan_id,
            expected_revision=persisted.base_workflow_revision,
        )
        return AgentCommandSubmissionV2(
            plan=self._repository.get_plan(persisted.plan_id),
            receipt=receipt,
        )

    def get_plan(self, plan_id: str) -> AgentCommandPlanV2:
        return self._repository.get_plan(plan_id)

    def recover_applying_plans(self) -> tuple[AgentActionReceiptV2, ...]:
        receipts: list[AgentActionReceiptV2] = []
        for plan in self._repository.list_plans_by_status("applying"):
            try:
                receipt = self.apply(
                    plan_id=plan.plan_id,
                    expected_revision=plan.base_workflow_revision,
                )
            except Exception as error:
                receipt = self._repository.fail_applying_plan(
                    plan.plan_id,
                    error_code=str(getattr(error, "code", "agent_command_recovery_failed")),
                    error_message=str(error),
                )
            receipts.append(receipt)
        return tuple(receipts)

    def confirm(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgentActionReceiptV2:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        try:
            plan = self._repository.begin_confirmed_plan(
                plan_id,
                expected_revision=expected_revision,
            )
        except V2PersistenceError as error:
            if error.code != "workflow_revision_conflict" or self._replan is None:
                raise
            original = self._repository.get_plan(plan_id)
            current = self._replan.current_workflow(original.workflow_id)
            result = self._replan.replan_once(
                original_plan=original,
                current_workflow=current,
                confirmation_granted=True,
            )
            if not result.confirmation_transferred:
                invalidated = _error(
                    "agent_command_confirmation_invalidated",
                    "Agent command targets changed and require renewed confirmation.",
                )
                invalidated.details = {"replacement_plan_id": result.replacement_plan.plan_id}
                raise invalidated
            plan = result.replacement_plan
            expected_revision = current.revision
        return self.apply(
            plan_id=plan.plan_id,
            expected_revision=expected_revision,
        )

    def act(
        self,
        *,
        plan_id: str,
        action: Literal["confirm", "reject"],
        expected_revision: int,
        idempotency_key: str,
    ) -> AgentActionReceiptV2:
        if action == "confirm":
            return self.confirm(
                plan_id=plan_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )
        return self.reject(
            plan_id=plan_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def reject(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgentActionReceiptV2:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        existing = self._repository.get_receipt_for_plan(plan_id, required=False)
        if existing is not None:
            return existing
        plan = self._repository.reject_plan(
            plan_id,
            expected_revision=expected_revision,
        )
        return self._repository.store_receipt(
            AgentActionReceiptV2(
                receipt_id=f"receipt_{uuid4().hex}",
                workflow_id=plan.workflow_id,
                plan_id=plan.plan_id,
                status="rejected",
                summary="Rejected the requested canvas changes.",
                workflow_revision=expected_revision,
            )
        )

    def apply(
        self,
        *,
        plan_id: str,
        expected_revision: int,
    ) -> AgentActionReceiptV2:
        plan = self._repository.get_plan(plan_id)
        existing = self._repository.get_receipt_for_plan(plan_id, required=False)
        if plan.status == "applied" and existing is not None:
            return existing
        if plan.status == "pending_confirmation":
            raise _error(
                "agent_command_confirmation_required",
                "Agent command plan requires confirmation.",
            )
        if plan.status != "applying":
            raise _error(
                "agent_command_plan_already_resolved",
                "Agent command plan is already resolved.",
            )

        composition_result: AgentPrepareCompositionResultV2 | None = None
        if len(plan.operations) == 1 and isinstance(
            plan.operations[0], AgentPrepareCompositionOperationV2
        ):
            if self._composition_preparation is None:
                raise _error(
                    "agent_command_operation_not_supported",
                    "Composition preparation is not configured.",
                )
            operation = plan.operations[0]
            composition_result = self._composition_preparation.prepare(
                workflow_id=plan.workflow_id,
                operation=operation,
                expected_revision=expected_revision,
                idempotency_key=f"agent-command:{plan.plan_id}:{operation.operation_id}",
            )
            result = self._repository.complete_composition_plan(
                plan,
                operation,
                composition_result,
            )
        else:
            result = self._repository.apply_plan_transaction(
                plan,
                expected_revision=expected_revision,
            )
        queued_execution_ids: tuple[str, ...] = ()
        run_errors: tuple[str, ...] = ()
        if result.post_commit_run_node_ids and self._run_nodes is not None:
            try:
                queued_execution_ids = self._run_nodes(
                    plan.workflow_id,
                    result.post_commit_run_node_ids,
                    f"agent-command:{plan.plan_id}",
                )
            except Exception as error:
                run_errors = (str(getattr(error, "code", "run_queue_failed")),)

        receipt = _receipt_for(
            plan_id=plan.plan_id,
            result=result,
            queued_execution_ids=queued_execution_ids,
            run_errors=run_errors,
            placement_hints=_placement_hints(plan, result),
            composition_preparation=composition_result,
        )
        return self._repository.store_receipt(receipt)


def _receipt_for(
    *,
    plan_id: str,
    result: AgentCommandTransactionResultV2,
    queued_execution_ids: tuple[str, ...],
    run_errors: tuple[str, ...],
    placement_hints: tuple[AgentPlacementHintV2, ...],
    composition_preparation: AgentPrepareCompositionResultV2 | None = None,
) -> AgentActionReceiptV2:
    status = "applied_with_run_error" if run_errors else "applied"
    summary = "Applied the requested canvas changes."
    if result.created_node_ids:
        summary = f"Created {len(result.created_node_ids)} canvas node(s)."
    return AgentActionReceiptV2(
        receipt_id=f"receipt_{uuid4().hex}",
        workflow_id=result.workflow_id,
        plan_id=plan_id,
        status=status,
        summary=summary,
        created_node_ids=result.created_node_ids,
        updated_node_ids=result.updated_node_ids,
        deleted_node_ids=result.deleted_node_ids,
        created_binding_ids=result.created_binding_ids,
        deleted_binding_ids=result.deleted_binding_ids,
        queued_execution_ids=queued_execution_ids,
        run_queue_errors=run_errors,
        operation_results=result.operation_results,
        workflow_revision=result.workflow_revision,
        placement_hints=placement_hints,
        composition_preparation=composition_preparation,
    )


def _placement_hints(
    plan,
    result: AgentCommandTransactionResultV2,
) -> tuple[AgentPlacementHintV2, ...]:
    by_operation = {item.operation_id: item for item in result.operation_results if item.node_id}
    hints: list[AgentPlacementHintV2] = []
    for operation in plan.operations:
        placement_hint = getattr(operation, "placement_hint", None)
        operation_result = by_operation.get(operation.operation_id)
        if placement_hint is None or operation_result is None:
            continue
        hints.append(placement_hint)
    return tuple(hints)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_command_service")
