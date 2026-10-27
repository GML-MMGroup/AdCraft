"""Transaction-local recovery of exactly owned Storyboard journey authority."""

from __future__ import annotations

import json
from typing import Mapping

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasGuidanceSessionRow,
    AgentCanvasMaterializationCommitRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import parse_production_journey


def recovery_conflict() -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_journey_recovery_conflict",
        "Storyboard journey recovery authority changed or belongs to another operation.",
        stage="storyboard_journey_recovery",
    )


def release_suppressed_reservation_in_transaction(
    connection: Connection,
    events: EventRepository,
    *,
    envelope: CapabilityCommandEnvelopeV2,
    timestamp: str,
) -> bool:
    session = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.session_id == envelope.session_id,
                AgentCanvasGuidanceSessionRow.workflow_id == envelope.workflow_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if session is None:
        return False
    journey = parse_production_journey(str(session["journey_state_json"]))
    action = journey.active_action
    if (
        envelope.capability_id != "storyboard_design"
        or action is None
        or action.action_kind != "invoke_capability:storyboard_design"
        or not (
            action.turn_id == envelope.capability_turn_id
            or (
                action.turn_id == envelope.source_turn_id
                and action.action_id == f"journey-action:{envelope.source_turn_id}"
            )
        )
    ):
        return False
    _replace_journey(
        connection,
        events,
        session=session,
        journey=journey.model_copy(update={"active_action": None}),
        timestamp=timestamp,
        event_type="journey_action_released",
        payload={
            "action_id": action.action_id,
            "turn_id": action.turn_id,
            "reason": "storyboard_duplicate_proposal_suppressed",
            "suppressed_turn_id": envelope.capability_turn_id,
        },
    )
    return True


def recover_failed_materialization_stage_in_transaction(
    connection: Connection,
    events: EventRepository,
    *,
    continuation: Mapping[str, object],
    timestamp: str,
) -> None:
    """Restore only a committed materialization's own current-stage failure."""

    session = (
        connection.execute(
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == continuation["workflow_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    if session is None:
        return
    journey = parse_production_journey(str(session["journey_state_json"]))
    if journey.stage != "storyboard_grids" or journey.stage_status != "failed":
        return
    turn_id = str(continuation["continuation_turn_id"])
    committed = (
        connection.execute(
            select(AgentCanvasMaterializationCommitRow).where(
                AgentCanvasMaterializationCommitRow.workflow_id == continuation["workflow_id"],
                AgentCanvasMaterializationCommitRow.action_turn_id == turn_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    failures = tuple(
        item
        for item in journey.transition_evidence
        if item.stage == journey.stage
        and item.stage_revision == journey.stage_revision
        and item.evidence_kind == "stage_failed"
    )
    if committed is None or journey.active_action is not None or not failures:
        raise recovery_conflict()
    materialization_id = str(committed["materialization_id"])
    for failure in failures:
        if failure.source_id != materialization_id or not failure.evidence_id.startswith(
            f"post-commit-storyboard-failure:{turn_id}:"
        ):
            raise recovery_conflict()
        raw_event = connection.execute(
            select(WorkflowEventRow.payload_json).where(
                WorkflowEventRow.workflow_id == continuation["workflow_id"],
                WorkflowEventRow.event_type == "journey_stage_failed",
                WorkflowEventRow.transition_key == failure.evidence_id,
            )
        ).scalar_one_or_none()
        proof = json.loads(str(raw_event)) if raw_event is not None else {}
        if (
            proof.get("materialization_id") != materialization_id
            or proof.get("stage") != journey.stage
            or proof.get("stage_revision") != journey.stage_revision
            or failure.evidence_id
            != f"post-commit-storyboard-failure:{turn_id}:{proof.get('error_code')}"
        ):
            raise recovery_conflict()
    _replace_journey(
        connection,
        events,
        session=session,
        journey=journey.model_copy(update={"stage_status": "working"}),
        timestamp=timestamp,
        event_type="journey_stage_started",
        payload={
            "reason": "failed_materialization_reopened",
            "continuation_id": str(continuation["continuation_id"]),
            "materialization_id": materialization_id,
            "turn_id": turn_id,
            "failure_evidence_ids": [item.evidence_id for item in failures],
        },
    )


def _replace_journey(
    connection: Connection,
    events: EventRepository,
    *,
    session: Mapping[str, object],
    journey: GuidedProductionJourneyV2,
    timestamp: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    revision = int(session["revision"])
    changed = connection.execute(
        update(AgentCanvasGuidanceSessionRow)
        .where(
            AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
            AgentCanvasGuidanceSessionRow.revision == revision,
        )
        .values(
            journey_state_json=journey.model_dump_json(),
            revision=revision + 1,
            updated_at=timestamp,
        )
    )
    if changed.rowcount != 1:
        raise recovery_conflict()
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=str(session["workflow_id"]),
            event_type=event_type,
            transition_key=f"journey:{session['session_id']}:{event_type}:{revision + 1}",
            created_at=timestamp,
            payload={
                "session_id": str(session["session_id"]),
                "session_revision": revision + 1,
                "stage": journey.stage,
                "stage_revision": journey.stage_revision,
                **payload,
            },
        ),
    )
