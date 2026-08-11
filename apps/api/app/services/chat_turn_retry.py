"""Idempotent retry orchestration for failed Agent Canvas chat turns."""

from __future__ import annotations

from collections.abc import Callable

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import (
    ChatTurnAcceptedV2,
    ChatTurnRetryRequestV1,
)


class ChatTurnRetryService:
    """Validate a frozen failed-turn snapshot and enqueue one child attempt."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        *,
        asset_resolver: Callable[[str], object] | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._asset_resolver = asset_resolver

    def retry(
        self,
        workflow_id: str,
        turn_id: str,
        request: ChatTurnRetryRequestV1,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        source = self._conversations.get_turn(turn_id)
        if source.workflow_id != workflow_id:
            raise _error("chat_turn_not_found", "Chat turn was not found.")

        replay = self._conversations.get_turn_by_idempotency_key(idempotency_key)
        if replay is not None:
            if replay.retry_of_turn_id != source.turn_id:
                raise _error("idempotency_conflict", "Idempotency key was reused.")
            return self._conversations.create_retry_turn(
                source,
                idempotency_key=idempotency_key,
                retry_snapshot=self._conversations.get_retry_snapshot(source.turn_id),
            )

        if source.status != "failed":
            raise _error("chat_turn_not_failed", "Only a failed chat turn can be retried.")
        if not source.retryable:
            raise _error(
                "chat_turn_not_retryable",
                "This chat turn failure is not retryable.",
            )

        workflow = self._workflows.get_workflow(workflow_id)
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        snapshot = self._conversations.get_retry_snapshot(source.turn_id)
        current_session_revision = session.revision if session is not None else 0
        if (
            request.expected_workflow_revision != workflow.revision
            or request.expected_session_revision != current_session_revision
            or snapshot.get("workflow_revision") != workflow.revision
            or snapshot.get("session_revision") != current_session_revision
        ):
            raise _stale_error()

        journey = session.journey if session is not None else None
        if journey is not None and (
            snapshot.get("journey_stage") != journey.stage
            or snapshot.get("journey_stage_revision") != journey.stage_revision
        ):
            raise _stale_error()

        current_nodes = {node.node_id: node.revision for node in workflow.nodes}
        node_revisions = snapshot.get("node_revisions")
        if not isinstance(node_revisions, dict) or any(
            current_nodes.get(str(node_id)) != revision
            for node_id, revision in node_revisions.items()
        ):
            raise _stale_error()

        asset_ids = snapshot.get("asset_ids")
        if not isinstance(asset_ids, list):
            raise _stale_error()
        if self._asset_resolver is not None:
            try:
                for asset_id in asset_ids:
                    self._asset_resolver(str(asset_id))
            except V2PersistenceError as error:
                raise _stale_error() from error

        return self._conversations.create_retry_turn(
            source,
            idempotency_key=idempotency_key,
            retry_snapshot=snapshot,
        )


def _stale_error() -> V2PersistenceError:
    return _error(
        "chat_turn_retry_stale",
        "The failed chat turn snapshot no longer matches current authoring state.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="chat_turn_retry_service")
