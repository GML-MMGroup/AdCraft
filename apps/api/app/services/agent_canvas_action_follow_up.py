"""Render optional agent follow-up messages for persisted action receipts."""

from __future__ import annotations

from app.schemas.agent_canvas_conversation import AgentActionReceiptV2


def render_action_follow_up(
    receipt: AgentActionReceiptV2,
    *,
    has_unresolved_planning: bool,
) -> str | None:
    """Keep machine-readable receipts distinct from conversational follow-ups."""

    if receipt.status not in {"applied", "applied_with_run_error"}:
        return None
    if not has_unresolved_planning:
        return None
    if receipt.created_node_ids:
        return "A new Draft was added to the canvas."
    if receipt.summary == "The concept options were revised.":
        return "Updated concept options are ready for review."
    return None
