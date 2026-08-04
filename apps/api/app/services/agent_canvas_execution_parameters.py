"""Normalize provider-neutral execution parameters for frozen Canvas attempts."""

from __future__ import annotations

from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_ad_media import BgmContentV2
from app.services.agent_canvas_ad_media import AdMediaRoleRegistry


@dataclass(frozen=True, slots=True)
class ResolvedExecutionParameters:
    """Provider-neutral parameters derived once for an immutable execution."""

    parameters: dict[str, object]
    normalizations: tuple[str, ...] = ()


class AgentCanvasExecutionParameterResolver:
    """Derive BGM execution controls without mutating canonical authoring state."""

    def __init__(self, registry: AdMediaRoleRegistry | None = None) -> None:
        self._registry = registry or AdMediaRoleRegistry()

    def resolve(self, node: CanvasNodeV2) -> ResolvedExecutionParameters:
        parameters = dict(node.parameters)
        if node.node_type != "audio" or node.semantic_role != "bgm":
            return ResolvedExecutionParameters(parameters=parameters)

        content = self._registry.validate_structured_content(
            node.semantic_role,
            node.structured_content,
        )
        if not isinstance(content, BgmContentV2):
            raise _error("invalid_role_content", "BGM structured content is invalid.")

        if "duration_seconds" in parameters:
            parameters["duration_seconds"] = _positive_integer_duration(
                parameters["duration_seconds"]
            )
            return ResolvedExecutionParameters(parameters=parameters)

        parameters["duration_seconds"] = _positive_integer_duration(
            node.structured_content.get("duration_seconds", content.duration_seconds)
        )
        return ResolvedExecutionParameters(
            parameters=parameters,
            normalizations=("bgm_duration_derived_from_structured_content",),
        )

    def freeze_node(self, node: CanvasNodeV2) -> tuple[CanvasNodeV2, tuple[str, ...]]:
        """Return a copied node suitable for one immutable run attempt."""

        resolved = self.resolve(node)
        return node.model_copy(update={"parameters": resolved.parameters}), resolved.normalizations


def _positive_integer_duration(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(
            "model_parameter_unsupported",
            "BGM duration_seconds must be a positive integer.",
        )
    duration = int(value)
    if duration <= 0 or duration != value:
        raise _error(
            "model_parameter_unsupported",
            "BGM duration_seconds must be a positive integer.",
        )
    return duration


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_execution_parameters",
    )
