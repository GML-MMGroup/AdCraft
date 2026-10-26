"""Separate user-created canvas nodes from Agent-journey nodes."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.agent_canvas import (
    USER_AUTHORING_ORIGIN,
    USER_AUTHORING_ORIGIN_KEY,
    CanvasNodeV2,
)


def is_user_authored(node: CanvasNodeV2) -> bool:
    """Return whether the user created this node directly on the canvas."""

    return node.metadata.get(USER_AUTHORING_ORIGIN_KEY) == USER_AUTHORING_ORIGIN


def agent_journey_nodes(nodes: Iterable[CanvasNodeV2]) -> tuple[CanvasNodeV2, ...]:
    """Nodes an Agent journey may observe; user-created nodes stay invisible to it."""

    return tuple(node for node in nodes if not is_user_authored(node))
