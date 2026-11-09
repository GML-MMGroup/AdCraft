"""Bounded local validation before a Canvas execution is admitted."""

from __future__ import annotations

from app.schemas.agent_canvas import CanvasNodeV2
from app.services.agent_canvas_execution_parameters import AgentCanvasExecutionParameterResolver
from app.services.model_resolution import ModelResolutionService


class AgentCanvasRunPreflight:
    """Reuse runtime parameter and model policy without submitting provider work."""

    def __init__(self, model_resolution: ModelResolutionService) -> None:
        self._model_resolution = model_resolution
        self._parameters = AgentCanvasExecutionParameterResolver()

    def validate(self, node: CanvasNodeV2) -> None:
        prepared, _ = self._parameters.freeze_node(node)
        self._model_resolution.resolve(prepared)
