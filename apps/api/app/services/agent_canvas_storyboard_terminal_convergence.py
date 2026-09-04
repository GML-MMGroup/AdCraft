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


class AgentCanvasStoryboardTerminalConvergenceService:
    """Converge one accepted Storyboard selection from immutable authority."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._repository = AgentCanvasStoryboardTerminalConvergenceRepository(database, events)

    def reconcile(
        self,
        command: StoryboardTerminalConvergenceCommandV1,
    ) -> StoryboardTerminalConvergenceOutcomeV1:
        return self._repository.reconcile(command)

