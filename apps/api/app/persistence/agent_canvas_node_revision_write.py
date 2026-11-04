"""Adapt stored Node rows to the shared revision policy within writer transactions."""

from __future__ import annotations

from collections.abc import Mapping
from app.services.agent_canvas_node_revision_authority import (
    PromptRevisionIntent,
    reconcile_node_prompt_revision,
)


def node_revision_values(
    row: Mapping[str, object],
    values: Mapping[str, object],
    *,
    intent: PromptRevisionIntent = "carry",
) -> dict[str, object]:
    """Validate a SQL successor against the locked preimage; return one atomic write.

    The caller retains its own CAS, event/outbox and rollback transaction. Only
    projection/review metadata is synchronized, never immutable execution data.
    """
    # The canonical row codec also uses dispatch repositories; defer this import
    # so those repositories can share the same codec without a module cycle.
    from app.persistence.agent_canvas_repository import _node_from_row, _node_values

    current = _node_from_row(row)
    candidate = _node_from_row({**row, **values})
    successor = reconcile_node_prompt_revision(current, candidate, intent=intent)
    return {**values, "metadata_json": _node_values(successor)["metadata_json"]}
