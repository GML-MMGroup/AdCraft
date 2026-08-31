"""Durable Prompt Preparation dependency barrier for materialization continuations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_conversation import ContinuationDeliveryV2
from app.schemas.agent_canvas_prompt_preparation_dispatch import PromptPreparationDispatchV1
from app.schemas.v2_persistence import V2EventInsert


_WAIT_EVENT_TYPE = "materialization_prompt_preparation_dependency_wait"


class AgentCanvasMaterializationPromptPreparationBarrier:
    """Observe exact durable dispatches without becoming an execution owner."""

    def __init__(
        self,
        *,
        dispatches: AgentCanvasPromptPreparationDispatchRepository,
        continuations: AgentCanvasContinuationOutboxRepository,
        events: EventRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._dispatches = dispatches
        self._continuations = continuations
        self._events = events
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def require_terminal(
        self,
        *,
        workflow_id: str,
        materialization_id: str,
        operations: tuple[tuple[str, str], ...],
    ) -> None:
        """Return only when every exact dispatch is terminal and successful."""

        pending = self._inspect(
            workflow_id=workflow_id,
            operations=operations,
        )
        if not pending:
            return
        normalized = tuple(sorted(pending))
        digest = _operation_set_digest(normalized)
        self._events.append(
            V2EventInsert(
                workflow_id=workflow_id,
                event_type=_WAIT_EVENT_TYPE,
                transition_key=(
                    f"materialization-prompt-preparation-wait:{materialization_id}:{digest}"
                ),
                created_at=self._clock().isoformat(),
                payload={
                    "materialization_id": materialization_id,
                    "node_ids": [node_id for node_id, _operation_id in normalized],
                    "operation_ids": [operation_id for _node_id, operation_id in normalized],
                    "operation_set_digest": digest,
                },
            )
        )
        raise V2PersistenceError(
            "prompt_preparation_pending",
            "Prompt preparation remains owned by its durable dispatch.",
            stage="capability_materialization_publication",
            details={"materialization_id": materialization_id},
        )

    def reconcile_terminal_dispatch(
        self,
        dispatch: PromptPreparationDispatchV1,
    ) -> ContinuationDeliveryV2 | None:
        """Wake the exact current dependency wait after its complete terminal set."""

        if dispatch.status not in {"completed", "failed"}:
            return None
        active = self._continuations.get_active_for_workflow(dispatch.workflow_id)
        if (
            active is None
            or active.status != "retry_wait"
            or active.last_error_code != "prompt_preparation_pending"
            or not active.last_error_message
        ):
            return None
        materialization_id = active.last_error_message
        operations = self._latest_wait_operations(
            workflow_id=dispatch.workflow_id,
            materialization_id=materialization_id,
        )
        if operations is None or (dispatch.node_id, dispatch.operation_id) not in operations:
            return None
        return self.reconcile_dependency_wait(
            workflow_id=dispatch.workflow_id,
            continuation_id=active.continuation_id,
            materialization_id=materialization_id,
        )

    def reconcile_dependency_wait(
        self,
        *,
        workflow_id: str,
        continuation_id: str,
        materialization_id: str,
    ) -> ContinuationDeliveryV2 | None:
        """Close callback-before-defer races through the same durable wait proof."""

        active = self._continuations.get_active_for_workflow(workflow_id)
        if (
            active is None
            or active.continuation_id != continuation_id
            or active.status != "retry_wait"
            or active.last_error_code != "prompt_preparation_pending"
            or active.last_error_message != materialization_id
        ):
            return None
        operations = self._latest_wait_operations(
            workflow_id=workflow_id,
            materialization_id=materialization_id,
        )
        if operations is None:
            return None
        try:
            pending = self._inspect(
                workflow_id=workflow_id,
                operations=operations,
            )
        except V2PersistenceError as error:
            if error.code != "prompt_preparation_failed":
                raise
            pending = ()
        if pending:
            return None
        return self._continuations.wake_prompt_preparation_wait(
            continuation_id,
            materialization_id=materialization_id,
            now=self._clock(),
        )

    def _inspect(
        self,
        *,
        workflow_id: str,
        operations: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        pending: list[tuple[str, str]] = []
        for node_id, operation_id in operations:
            dispatch = self._dispatches.get_by_node_operation(
                workflow_id,
                node_id,
                operation_id,
            )
            if dispatch is None:
                raise V2PersistenceError(
                    "prompt_preparation_dispatch_missing",
                    "Materialization Prompt Preparation has no durable dispatch owner.",
                    stage="capability_materialization_publication",
                    details={"node_id": node_id, "operation_id": operation_id},
                )
            if dispatch.status in {"waiting_user", "queued", "leased"}:
                pending.append((node_id, operation_id))
                continue
            if dispatch.status == "failed":
                raise V2PersistenceError(
                    "prompt_preparation_failed",
                    dispatch.last_error_message or "Prompt preparation failed.",
                    stage="capability_materialization_publication",
                    details={
                        "retryable": False,
                        "preparation_error_code": (
                            dispatch.last_error_code or "prompt_preparation_failed"
                        ),
                    },
                )
            if dispatch.status == "superseded":
                raise V2PersistenceError(
                    "prompt_preparation_dispatch_stale",
                    "Materialization Prompt Preparation dispatch was superseded.",
                    stage="capability_materialization_publication",
                    details={"node_id": node_id, "operation_id": operation_id},
                )
        return tuple(pending)

    def _latest_wait_operations(
        self,
        *,
        workflow_id: str,
        materialization_id: str,
    ) -> tuple[tuple[str, str], ...] | None:
        for event in reversed(self._events.list_after(workflow_id)):
            if (
                event.event_type != _WAIT_EVENT_TYPE
                or event.payload.get("materialization_id") != materialization_id
            ):
                continue
            node_ids = event.payload.get("node_ids")
            operation_ids = event.payload.get("operation_ids")
            if not isinstance(node_ids, list) or not isinstance(operation_ids, list):
                return None
            if len(node_ids) != len(operation_ids):
                return None
            operations = tuple(zip(node_ids, operation_ids, strict=True))
            if not all(
                isinstance(node_id, str)
                and node_id
                and isinstance(operation_id, str)
                and operation_id
                for node_id, operation_id in operations
            ):
                return None
            expected_digest = event.payload.get("operation_set_digest")
            if expected_digest != _operation_set_digest(tuple(sorted(operations))):
                return None
            return operations
        return None


def _operation_set_digest(operations: tuple[tuple[str, str], ...]) -> str:
    encoded = json.dumps(
        operations,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = ("AgentCanvasMaterializationPromptPreparationBarrier",)
