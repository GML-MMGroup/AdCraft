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
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.v2_persistence import V2EventInsert


@dataclass(frozen=True)
class GuidanceOrphanRecoveryResult:
    status: Literal["legal_wait", "owned", "recovered"]
    continuation_ids: tuple[str, ...] = ()


class GuidanceOrphanRecoveryService:
    """Recover only persisted continuation work with an existing durable identity."""

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

    def recover_promised_progress(
        self,
        workflow_id: str,
        *,
        drain_continuation: Callable[[str], object],
    ) -> GuidanceOrphanRecoveryResult:
        awaiting = self._interactions.get_awaiting(workflow_id)
        if awaiting is not None:
            return GuidanceOrphanRecoveryResult(status="legal_wait")

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
