"""Deterministic recovery audit for promised Guidance progress."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.services.agent_canvas_next_action_dispatch import NextActionDispatchService
from app.services.agent_canvas_production_journey import GuidedProductionJourneyPolicyService
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.v2_persistence import V2EventInsert


@dataclass(frozen=True)
class GuidanceOrphanRecoveryResult:
    status: Literal["legal_wait", "owned", "recovered"]
    continuation_ids: tuple[str, ...] = ()


class GuidanceOrphanRecoveryService:
    """Recover durable continuations and idle authoring behind independent media waits."""

    def __init__(
        self,
        interactions: AgentCanvasGuidedInteractionRepository,
        continuations: AgentCanvasContinuationOutboxRepository,
        events: EventRepository,
    ) -> None:
        if not (
            interactions.database is continuations.database
            and interactions.database is events.database
        ):
            raise ValueError("Guidance recovery repositories must share one database.")
        self._interactions = interactions
        self._continuations = continuations
        self._events = events
        self._conversations = AgentCanvasConversationRepository(interactions.database, events)
        self._next_action_dispatch = NextActionDispatchService(interactions.database, events)

    def recover_promised_progress(
        self,
        workflow_id: str,
        *,
        drain_continuation: Callable[[str], object],
    ) -> GuidanceOrphanRecoveryResult:
        awaiting = self._interactions.get_awaiting(workflow_id)
        if awaiting is not None and awaiting.kind not in {"manual_node_run", "media_review"}:
            return GuidanceOrphanRecoveryResult(status="legal_wait")

        session = (
            self._conversations.get_guidance_session(workflow_id) if awaiting is not None else None
        )
        # Freeze the source before checking ownership. A concurrent refresh that
        # observes a newly queued Next Action must also observe its delivery.
        source = self._conversations.get_latest_turn(workflow_id) if session is not None else None
        deliveries = self._continuations.list_nonterminal_for_workflow(workflow_id)
        if session is not None and not deliveries:
            journey = session.journey
            if (
                session.status != "active"
                or journey.active_action is not None
                or journey.suspended_action is not None
                or journey.stage_status != "ready"
                or GuidedProductionJourneyPolicyService().evaluate(journey).action
                not in {"invoke_capability", "invoke_internal_checkpoint"}
            ):
                return GuidanceOrphanRecoveryResult(status="legal_wait")
            if source is None:
                return GuidanceOrphanRecoveryResult(status="legal_wait")
            self._next_action_dispatch.dispatch(
                source,
                session_id=session.session_id,
                expected_session_revision=session.revision,
                objective=session.goal.summary,
            )
            deliveries = self._continuations.list_nonterminal_for_workflow(workflow_id)
        recoverable = tuple(
            delivery for delivery in deliveries if delivery.status in {"queued", "retry_wait"}
        )
        if recoverable:
            recovered_ids: list[str] = []
            for delivery in recoverable:
                drain_continuation(delivery.continuation_id)
                recovered_ids.append(delivery.continuation_id)
                self._events.append(
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guidance_orphan_recovered",
                        transition_key=(f"guidance-orphan:{delivery.continuation_id}:recovered"),
                        action_id=delivery.continuation_turn_id,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        payload={
                            "continuation_id": delivery.continuation_id,
                            "continuation_turn_id": delivery.continuation_turn_id,
                            "recovery_kind": "existing_continuation_dispatch",
                        },
                    )
                )
            return GuidanceOrphanRecoveryResult(
                status="recovered",
                continuation_ids=tuple(recovered_ids),
            )
        if deliveries:
            return GuidanceOrphanRecoveryResult(
                status="owned",
                continuation_ids=tuple(item.continuation_id for item in deliveries),
            )
        raise V2PersistenceError(
            "guidance_orphaned_stall",
            "Guidance progress has no current durable recovery owner.",
            stage="guidance_orphan_recovery_service",
            details={"workflow_id": workflow_id},
        )
