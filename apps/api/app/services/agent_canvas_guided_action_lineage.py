"""Causal execution-leaf resolution for one guided journey action."""

from __future__ import annotations

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    CapabilityCommandEnvelopeV2,
    NextActionEnvelopeV1,
)
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_guidance import GuidedActionExecutionLeafV1


class GuidedActionExecutionLeafResolver:
    """Resolve persisted typed delivery and retry descendants without timeline order."""

    def __init__(
        self,
        conversations: AgentCanvasConversationRepository,
        continuations: AgentCanvasContinuationOutboxRepository,
        envelopes: AgentCanvasOperationEnvelopeRepository,
    ) -> None:
        self._conversations = conversations
        self._continuations = continuations
        self._envelopes = envelopes

    def resolve(
        self,
        workflow_id: str,
        session: GuidedSessionStateV2,
    ) -> GuidedActionExecutionLeafV1 | None:
        action = session.journey.active_action
        if action is None or not action.turn_id:
            return None
        root = self._conversations.get_turn(action.turn_id)
        self._require_workflow(root.workflow_id, workflow_id)
        deliveries = self._continuations.list_for_workflow(workflow_id)
        current = root
        incoming = next(
            (item for item in deliveries if item.continuation_turn_id == current.turn_id),
            None,
        )
        visited: set[str] = set()
        for _ in range(32):
            if current.turn_id in visited:
                raise _lineage_error("Guided action execution lineage contains a cycle.")
            visited.add(current.turn_id)
            delivery_children = [
                item for item in deliveries if item.source_turn_id == current.turn_id
            ]
            retry_children = list(self._conversations.list_retry_children(current.turn_id))
            child_turn_ids = {item.continuation_turn_id for item in delivery_children} | {
                item.turn_id for item in retry_children
            }
            if not child_turn_ids:
                break
            if len(child_turn_ids) != 1:
                raise _lineage_error("Guided action execution lineage is ambiguous.")
            child_id = next(iter(child_turn_ids))
            child = self._conversations.get_turn(child_id)
            self._require_workflow(child.workflow_id, workflow_id)
            matching = [item for item in delivery_children if item.continuation_turn_id == child_id]
            if len(matching) != 1:
                raise _lineage_error("Typed retry lineage is missing its Continuation.")
            incoming = matching[0]
            self._validate_envelope(incoming, workflow_id, child_id)
            current = child
        else:
            raise _lineage_error("Guided action execution lineage exceeds its bound.")
        if incoming is not None:
            self._validate_envelope(incoming, workflow_id, current.turn_id)
        return GuidedActionExecutionLeafV1(
            workflow_id=workflow_id,
            logical_action_id=action.action_id,
            root_turn_id=root.turn_id,
            leaf_turn_id=current.turn_id,
            leaf_turn_kind=current.turn_kind,
            leaf_status=current.status,
            continuation_id=(incoming.continuation_id if incoming is not None else None),
            continuation_status=(incoming.status if incoming is not None else None),
            operation=(incoming.operation if incoming is not None else None),
            retry_attempt_no=current.retry_attempt_no,
            error_code=current.error_code,
            retryable=current.retryable,
        )

    def _validate_envelope(self, delivery, workflow_id: str, turn_id: str) -> None:
        if delivery.operation not in {"next_action", "capability_command"}:
            raise _lineage_error("Guided action lineage references an unsupported operation.")
        try:
            envelope = self._envelopes.get(delivery.envelope_id)
        except V2PersistenceError as error:
            raise _lineage_error("Typed operation envelope is missing or invalid.") from error
        expected_turn_id = (
            envelope.capability_turn_id
            if isinstance(envelope, CapabilityCommandEnvelopeV2)
            else envelope.next_action_turn_id
            if isinstance(envelope, NextActionEnvelopeV1)
            else None
        )
        expected_operation = (
            "capability_command"
            if isinstance(envelope, CapabilityCommandEnvelopeV2)
            else "next_action"
            if isinstance(envelope, NextActionEnvelopeV1)
            else None
        )
        if (
            envelope.workflow_id != workflow_id
            or expected_turn_id != turn_id
            or expected_operation != delivery.operation
        ):
            raise _lineage_error("Typed operation envelope does not match its Continuation.")

    @staticmethod
    def _require_workflow(actual: str, expected: str) -> None:
        if actual != expected:
            raise _lineage_error("Guided action execution lineage crosses a Workflow.")


def _lineage_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_action_lineage_invalid",
        message,
        stage="guided_action_execution_lineage",
    )
