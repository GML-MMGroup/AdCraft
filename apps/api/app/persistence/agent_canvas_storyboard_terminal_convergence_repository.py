"""Atomic repository authority for committed Storyboard terminal convergence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasMaterializationCommitRow,
    AgentCanvasWorkflowRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_materialization_commit import MaterializationOutcomeV1
from app.schemas.agent_canvas_storyboard_terminal_convergence import (
    StoryboardTerminalConvergenceCommandV1,
    StoryboardTerminalConvergenceOutcomeV1,
)
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasStoryboardTerminalConvergenceRepository:
    """Converge mutable parent projections from one immutable receipt."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        self._database = database
        self._events = events

    def reconcile(
        self,
        command: StoryboardTerminalConvergenceCommandV1,
    ) -> StoryboardTerminalConvergenceOutcomeV1:
        convergence_id = _convergence_id(command)
        transition_key = f"storyboard-terminal:{convergence_id}"
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    commit = connection.execute(
                        select(AgentCanvasMaterializationCommitRow).where(
                            AgentCanvasMaterializationCommitRow.materialization_id
                            == command.materialization_id,
                            AgentCanvasMaterializationCommitRow.workflow_id
                            == command.workflow_id,
                            AgentCanvasMaterializationCommitRow.proposal_id
                            == command.proposal_id,
                            AgentCanvasMaterializationCommitRow.action_turn_id
                            == command.parent_turn_id,
                        )
                    ).mappings().one_or_none()
                    if commit is None:
                        raise _stale("storyboard_materialization_receipt_stale")
                    if str(commit["payload_digest"]) != command.materialization_digest:
                        raise _conflict("storyboard_materialization_digest_conflict")
                    committed_outcome = MaterializationOutcomeV1.model_validate_json(
                        str(commit["outcome_json"])
                    )
                    if (
                        committed_outcome.workflow_id != command.workflow_id
                        or committed_outcome.proposal_id != command.proposal_id
                        or committed_outcome.receipt_id != command.materialization_receipt_id
                    ):
                        raise _conflict("storyboard_materialization_receipt_conflict")

                    workflow = connection.execute(
                        select(AgentCanvasWorkflowRow).where(
                            AgentCanvasWorkflowRow.workflow_id == command.workflow_id
                        )
                    ).mappings().one_or_none()
                    proposal = connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == command.proposal_id,
                            AgentCanvasConceptProposalRow.workflow_id == command.workflow_id,
                        )
                    ).mappings().one_or_none()
                    interaction = connection.execute(
                        select(AgentCanvasGuidedInteractionRow).where(
                            AgentCanvasGuidedInteractionRow.interaction_id
                            == command.interaction_id,
                            AgentCanvasGuidedInteractionRow.workflow_id == command.workflow_id,
                        )
                    ).mappings().one_or_none()
                    parent_turn = connection.execute(
                        select(AgentCanvasChatTurnRow).where(
                            AgentCanvasChatTurnRow.turn_id == command.parent_turn_id,
                            AgentCanvasChatTurnRow.workflow_id == command.workflow_id,
                        )
                    ).mappings().one_or_none()
                    session = connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == command.workflow_id
                        )
                    ).mappings().one_or_none()
                    if any(
                        item is None
                        for item in (workflow, proposal, interaction, parent_turn, session)
                    ):
                        raise _stale("storyboard_terminal_authority_stale")
                    assert workflow is not None
                    assert proposal is not None
                    assert interaction is not None
                    assert parent_turn is not None
                    assert session is not None
                    interaction_content = json.loads(str(interaction["content_json"]))
                    if (
                        int(workflow["revision"]) != command.expected_workflow_revision
                        or int(proposal["proposal_revision"])
                        != command.expected_proposal_revision
                        or int(interaction["revision"])
                        != command.expected_interaction_revision
                        or int(session["revision"]) != command.expected_session_revision
                        or str(proposal["proposal_kind"]) != "storyboard"
                        or str(proposal["materialization_id"]) != command.materialization_id
                        or str(proposal["materialization_turn_id"]) != command.parent_turn_id
                        or interaction_content.get("proposal_id") != command.proposal_id
                        or interaction_content.get("stage") != command.stage
                        or interaction_content.get("stage_revision") != command.stage_revision
                    ):
                        raise _stale("storyboard_terminal_revision_stale")
                    if str(session["active_proposal_id"] or "") not in {
                        "",
                        command.proposal_id,
                    }:
                        raise _conflict("storyboard_terminal_current_proposal_conflict")

                    timeline_rows = connection.execute(
                        select(AgentCanvasChatEntryRow).where(
                            AgentCanvasChatEntryRow.workflow_id == command.workflow_id
                        )
                    ).mappings().all()
                    existing_convergence_event = connection.execute(
                        select(WorkflowEventRow).where(
                            WorkflowEventRow.transition_key == transition_key
                        )
                    ).mappings().one_or_none()
                    event_preexisted = existing_convergence_event is not None
                    awaiting_exists = (
                        connection.execute(
                            select(AgentCanvasGuidanceAwaitingRow.awaiting_id).where(
                                AgentCanvasGuidanceAwaitingRow.workflow_id
                                == command.workflow_id,
                                AgentCanvasGuidanceAwaitingRow.interaction_id
                                == command.interaction_id,
                            )
                        ).scalar_one_or_none()
                        is not None
                    )
                    proposal_needs_convergence = (
                        str(proposal["availability"]) != "applied"
                        or str(proposal["materialization_status"]) != "completed"
                        or bool(proposal["materialization_retryable"])
                        or proposal["materialization_error_code"] is not None
                        or proposal["materialization_error_message"] is not None
                    )
                    interaction_needs_convergence = str(interaction["status"]) != "closed"
                    turn_needs_convergence = (
                        str(parent_turn["status"]) != "completed"
                        or bool(parent_turn["retryable"])
                        or str(parent_turn["operation_stage"] or "") != "completed"
                        or parent_turn["operation_failure_json"] is not None
                        or parent_turn["error_code"] is not None
                        or parent_turn["error_message"] is not None
                    )
                    session_needs_convergence = (
                        session["active_proposal_id"] == command.proposal_id
                    )
                    changed = any(
                        (
                            proposal_needs_convergence,
                            interaction_needs_convergence,
                            turn_needs_convergence,
                            session_needs_convergence,
                            awaiting_exists,
                        )
                    )
                    if proposal_needs_convergence:
                        connection.execute(
                            update(AgentCanvasConceptProposalRow)
                            .where(
                                AgentCanvasConceptProposalRow.proposal_id
                                == command.proposal_id,
                                AgentCanvasConceptProposalRow.proposal_revision
                                == command.expected_proposal_revision,
                            )
                            .values(
                                availability="applied",
                                materialization_status="completed",
                                materialization_retryable=False,
                                materialization_error_code=None,
                                materialization_error_message=None,
                                updated_at=now,
                                materialization_updated_at=now,
                            )
                        )
                    if interaction_needs_convergence:
                        connection.execute(
                            update(AgentCanvasGuidedInteractionRow)
                            .where(
                                AgentCanvasGuidedInteractionRow.interaction_id
                                == command.interaction_id,
                                AgentCanvasGuidedInteractionRow.revision
                                == command.expected_interaction_revision,
                            )
                            .values(status="closed", updated_at=now)
                        )
                    if turn_needs_convergence:
                        connection.execute(
                            update(AgentCanvasChatTurnRow)
                            .where(AgentCanvasChatTurnRow.turn_id == command.parent_turn_id)
                            .values(
                                status="completed",
                                retryable=False,
                                operation_stage="completed",
                                operation_failure_json=None,
                                error_code=None,
                                error_message=None,
                                updated_at=now,
                            )
                        )
                    if session_needs_convergence:
                        connection.execute(
                            update(AgentCanvasGuidanceSessionRow)
                            .where(
                                AgentCanvasGuidanceSessionRow.session_id
                                == session["session_id"],
                                AgentCanvasGuidanceSessionRow.revision
                                == command.expected_session_revision,
                            )
                            .values(active_proposal_id=None, updated_at=now)
                        )
                    if awaiting_exists:
                        connection.execute(
                            delete(AgentCanvasGuidanceAwaitingRow).where(
                                AgentCanvasGuidanceAwaitingRow.workflow_id
                                == command.workflow_id,
                                AgentCanvasGuidanceAwaitingRow.interaction_id
                                == command.interaction_id,
                            )
                        )
                    for row in timeline_rows:
                        metadata = json.loads(str(row["metadata_json"]))
                        if metadata.get("turn_id") != command.parent_turn_id:
                            continue
                        terminal_metadata = {
                            key: value
                            for key, value in metadata.items()
                            if key not in {"error_code", "operation_failure"}
                        }
                        terminal_metadata.update(
                            {
                                "status": "completed",
                                "retryable": False,
                            }
                        )
                        if terminal_metadata != metadata:
                            changed = True
                            connection.execute(
                                update(AgentCanvasChatEntryRow)
                                .where(AgentCanvasChatEntryRow.entry_id == row["entry_id"])
                                .values(
                                    metadata_json=json.dumps(
                                        terminal_metadata,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                        sort_keys=True,
                                    )
                                )
                            )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=command.workflow_id,
                            conversation_id=str(parent_turn["conversation_id"]),
                            turn_id=command.parent_turn_id,
                            action_id=command.materialization_id,
                            event_type="storyboard_terminal_state_reconciled",
                            transition_key=transition_key,
                            created_at=now,
                            payload={
                                "convergence_id": convergence_id,
                                "stage": command.stage,
                                "stage_revision": command.stage_revision,
                                "proposal_id": command.proposal_id,
                                "interaction_id": command.interaction_id,
                                "materialization_id": command.materialization_id,
                                "receipt_id": command.materialization_receipt_id,
                                "terminal_cause": "materialization_receipt",
                                "changed": (
                                    bool(
                                        json.loads(
                                            str(existing_convergence_event["payload_json"])
                                        ).get("changed", False)
                                    )
                                    if existing_convergence_event is not None
                                    else changed
                                ),
                            },
                        ),
                    )
                    recorded_changed = (
                        bool(
                            json.loads(str(existing_convergence_event["payload_json"])).get(
                                "changed", False
                            )
                        )
                        if existing_convergence_event is not None
                        else changed
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "storyboard_terminal_convergence_unavailable",
                "Storyboard terminal state could not be reconciled.",
                stage="storyboard_terminal_convergence",
            ) from error

        # The transition event is the replay authority. A second call observes an
        # already-converged projection and therefore reports replay without another write.
        return StoryboardTerminalConvergenceOutcomeV1(
            convergence_id=convergence_id,
            workflow_id=command.workflow_id,
            stage=command.stage,
            stage_revision=command.stage_revision,
            proposal_id=command.proposal_id,
            interaction_id=command.interaction_id,
            parent_turn_id=command.parent_turn_id,
            materialization_id=command.materialization_id,
            materialization_receipt_id=command.materialization_receipt_id,
            resulting_workflow_revision=command.expected_workflow_revision,
            resulting_proposal_revision=command.expected_proposal_revision,
            resulting_interaction_revision=command.expected_interaction_revision,
            resulting_session_revision=command.expected_session_revision,
            changed=recorded_changed,
            replayed=event_preexisted,
        )


def _convergence_id(command: StoryboardTerminalConvergenceCommandV1) -> str:
    identity = ":".join(
        (
            command.workflow_id,
            command.stage,
            str(command.stage_revision),
            command.proposal_id,
            command.interaction_id,
            command.parent_turn_id,
            command.materialization_id,
            command.materialization_receipt_id,
        )
    )
    return "storyboard_convergence_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _stale(code: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        "Storyboard terminal convergence authority is stale.",
        stage="storyboard_terminal_convergence",
    )


def _conflict(code: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        "Storyboard terminal convergence authority conflicts with the receipt.",
        stage="storyboard_terminal_convergence",
    )
