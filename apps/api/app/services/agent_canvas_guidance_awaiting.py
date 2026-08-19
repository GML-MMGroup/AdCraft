"""Reason-specific entry and resume boundary for durable Guidance waits."""

from __future__ import annotations

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingResumeProofV1,
    GuidanceAwaitingV1,
)


class GuidanceAwaitingService:
    """Persist and resume one declared Guidance wait without inferred authority."""

    def __init__(
        self,
        interactions: AgentCanvasGuidedInteractionRepository,
        conversations: AgentCanvasConversationRepository,
    ) -> None:
        if interactions.database is not conversations.database:
            raise ValueError("Guidance awaiting repositories must share one database.")
        self._interactions = interactions

    def inspect(self, workflow_id: str) -> GuidanceAwaitingV1 | None:
        return self._interactions.get_awaiting(workflow_id)

    def enter(
        self,
        awaiting: GuidanceAwaitingV1,
        *,
        expected_session_revision: int,
    ) -> GuidanceAwaitingV1:
        return self._interactions.enter_awaiting(
            awaiting,
            expected_session_revision=expected_session_revision,
        )

    def enter_manual_node_run(
        self,
        awaiting: GuidanceAwaitingV1,
        *,
        expected_session_revision: int,
        next_action_requires_ready_media: bool,
        user_requested_pause: bool,
    ) -> GuidanceAwaitingV1:
        if awaiting.kind != "manual_node_run" or not (
            next_action_requires_ready_media or user_requested_pause
        ):
            raise _error(
                "guidance_awaiting_conflict",
                "Manual Node Run waiting requires a Ready-media dependency or explicit pause.",
            )
        return self.enter(
            awaiting,
            expected_session_revision=expected_session_revision,
        )

    def enter_milestone_idle(
        self,
        awaiting: GuidanceAwaitingV1,
        *,
        expected_session_revision: int,
        requested_scope_completed: bool,
        full_ad_goal: bool,
        user_paused_or_narrowed: bool,
        automatic_progress_owned: bool,
    ) -> GuidanceAwaitingV1:
        legal_idle = (
            awaiting.kind == "milestone_idle"
            and requested_scope_completed
            and not automatic_progress_owned
            and (not full_ad_goal or user_paused_or_narrowed)
        )
        if not legal_idle:
            raise _error(
                "guidance_awaiting_conflict",
                "Milestone idle requires completed scope without automatic progress ownership.",
            )
        return self.enter(
            awaiting,
            expected_session_revision=expected_session_revision,
        )

    def resume(
        self,
        workflow_id: str,
        proof: GuidanceAwaitingResumeProofV1,
    ) -> None:
        self._interactions.resume_awaiting(workflow_id, proof)


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guidance_awaiting_service")
