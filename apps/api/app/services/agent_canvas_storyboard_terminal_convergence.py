"""Service boundary for committed Storyboard terminal convergence."""

from __future__ import annotations

from app.persistence.agent_canvas_storyboard_terminal_convergence_repository import (
    AgentCanvasStoryboardTerminalConvergenceRepository,
)
from app.persistence.database import V2Database
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_storyboard_terminal_convergence import (
    StoryboardTerminalConvergenceCommandV1,
    StoryboardTerminalConvergenceOutcomeV1,
)
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationOutcomeV1,
    MaterializationPlanV1,
)


class AgentCanvasStoryboardTerminalConvergenceService:
    """Converge one accepted Storyboard selection from immutable authority."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._repository = AgentCanvasStoryboardTerminalConvergenceRepository(database, events)

    def reconcile(
        self,
        command: StoryboardTerminalConvergenceCommandV1,
    ) -> StoryboardTerminalConvergenceOutcomeV1:
        return self._repository.reconcile(command)

    def reconcile_commit(
        self,
        plan: MaterializationPlanV1,
        outcome: MaterializationOutcomeV1,
    ) -> StoryboardTerminalConvergenceOutcomeV1 | None:
        command = self._repository.command_for_commit(
            plan,
            outcome,
            terminal_cause="commit",
        )
        return self.reconcile(command) if command is not None else None
