"""Transactional rebasing for open guided interactions."""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasGuidedInteractionRow
from app.schemas.v2_persistence import V2EventInsert


def rebase_open_guided_interactions_in_transaction(
    connection: Connection,
    events: EventRepository,
    *,
    workflow_id: str,
    session_id: str,
    previous_session_revision: int,
    next_session_revision: int,
    previous_checkpoint_json: str | None,
    next_checkpoint_json: str | None,
    updated_at: str,
) -> None:
    """Rebase open interactions when a session revision keeps its checkpoint."""

    if previous_checkpoint_json != next_checkpoint_json:
        return
    checkpoint_id = None
    if next_checkpoint_json is not None:
        checkpoint_payload = json.loads(next_checkpoint_json)
        if isinstance(checkpoint_payload, dict):
            value = checkpoint_payload.get("checkpoint_id")
            checkpoint_id = str(value) if isinstance(value, str) else None
    rows = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow).where(
                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                AgentCanvasGuidedInteractionRow.session_id == session_id,
                AgentCanvasGuidedInteractionRow.status == "open",
                AgentCanvasGuidedInteractionRow.expected_session_revision
                <= previous_session_revision,
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        if checkpoint_id is not None and str(row["checkpoint_id"]) != checkpoint_id:
            continue
        changed = connection.execute(
            update(AgentCanvasGuidedInteractionRow)
            .where(
                AgentCanvasGuidedInteractionRow.interaction_id == row["interaction_id"],
                AgentCanvasGuidedInteractionRow.status == "open",
                AgentCanvasGuidedInteractionRow.expected_session_revision
                <= previous_session_revision,
            )
            .values(
                expected_session_revision=next_session_revision,
                revision=int(row["revision"]) + 1,
                updated_at=updated_at,
            )
        )
        if changed.rowcount != 1:
            continue
        events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="guided_interaction_updated",
                transition_key=(
                    f"guided-interaction:{row['interaction_id']}:rebased:{next_session_revision}"
                ),
                action_id=str(row["interaction_id"]),
                created_at=updated_at,
                payload={
                    "interaction_id": str(row["interaction_id"]),
                    "session_id": session_id,
                    "previous_session_revision": previous_session_revision,
                    "session_revision": next_session_revision,
                    "previous_interaction_revision": int(row["revision"]),
                    "interaction_revision": int(row["revision"]) + 1,
                    "reason": "checkpoint_preserved_session_revision_bump",
                },
            ),
        )
