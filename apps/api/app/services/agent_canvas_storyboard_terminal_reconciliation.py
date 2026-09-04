"""Dry-run-first historical reconciliation for one Storyboard stage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatEntryRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasMaterializationCommitRow,
    AgentCanvasWorkflowRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_materialization_commit import MaterializationOutcomeV1
from app.schemas.agent_canvas_storyboard_terminal_reconciliation import (
    StoryboardTerminalReconciliationPlanV1,
    StoryboardTerminalReconciliationReceiptV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import parse_production_journey


class AgentCanvasStoryboardTerminalReconciliationService:
    """Plan and apply one exact historical Storyboard projection correction."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Storyboard reconciliation and events must share one database.")
        self._database = database
        self._events = events

    def dry_run(self, *, workflow_id: str) -> StoryboardTerminalReconciliationPlanV1:
        with self._database.engine.connect() as connection:
            return self._plan_in_transaction(connection, workflow_id=workflow_id)

    def apply(
        self,
        *,
        workflow_id: str,
        expected_plan_digest: str,
    ) -> StoryboardTerminalReconciliationReceiptV1:
        if not expected_plan_digest.startswith("sha256:"):
            raise _stale("Storyboard reconciliation plan digest is invalid.")
        transition_key = f"storyboard-terminal-reconciliation:{expected_plan_digest}"
        try:
            with self._database.engine.connect() as connection:
                replay = _event_receipt(connection, transition_key)
                if replay is not None:
                    return replay.model_copy(update={"replayed": True})
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _event_receipt(connection, transition_key)
                    if replay is not None:
                        connection.commit()
                        return replay.model_copy(update={"replayed": True})
                    plan = self._plan_in_transaction(connection, workflow_id=workflow_id)
                    if plan.plan_digest != expected_plan_digest:
                        raise _stale(
                            "Storyboard reconciliation authority changed after dry-run."
                        )
                    timestamp = datetime.now(timezone.utc).isoformat()
                    self._apply_plan_in_transaction(connection, plan=plan, timestamp=timestamp)
                    receipt = StoryboardTerminalReconciliationReceiptV1(
                        reconciliation_id=(
                            "storyboard_reconciliation_"
                            + expected_plan_digest.removeprefix("sha256:")[:32]
                        ),
                        workflow_id=workflow_id,
                        plan_digest=expected_plan_digest,
                        canonical_proposal_id=plan.canonical_proposal_id,
                        superseded_proposal_ids=plan.duplicate_proposal_ids,
                        cleared_interaction_ids=plan.duplicate_interaction_ids,
                        changed=True,
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            event_type="storyboard_terminal_reconciliation_applied",
                            transition_key=transition_key,
                            created_at=timestamp,
                            payload=receipt.model_dump(mode="json"),
                        ),
                    )
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "storyboard_terminal_reconciliation_unavailable",
                "Storyboard terminal reconciliation could not be completed.",
                stage="storyboard_terminal_reconciliation",
            ) from error

    def _plan_in_transaction(
        self,
        connection: Connection,
        *,
        workflow_id: str,
    ) -> StoryboardTerminalReconciliationPlanV1:
        workflow = _one(
            connection,
            select(AgentCanvasWorkflowRow).where(
                AgentCanvasWorkflowRow.workflow_id == workflow_id
            ),
            "Storyboard reconciliation Workflow was not found.",
        )
        session = _one(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
            ),
            "Storyboard reconciliation Guidance Session was not found.",
        )
        journey = parse_production_journey(str(session["journey_state_json"]))
        proposal_rows = (
            connection.execute(
                select(AgentCanvasConceptProposalRow).where(
                    AgentCanvasConceptProposalRow.workflow_id == workflow_id,
                    AgentCanvasConceptProposalRow.proposal_kind == "storyboard",
                )
            )
            .mappings()
            .all()
        )
        interaction_rows = (
            connection.execute(
                select(AgentCanvasGuidedInteractionRow).where(
                    AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                    AgentCanvasGuidedInteractionRow.session_id == session["session_id"],
                    AgentCanvasGuidedInteractionRow.kind == "concept_choice",
                )
            )
            .mappings()
            .all()
        )
        interactions_by_proposal: dict[str, list[RowMapping]] = {}
        for interaction in interaction_rows:
            content = _json_object(interaction["content_json"])
            if (
                content.get("stage") != journey.stage
                or content.get("stage_revision") != journey.stage_revision
            ):
                continue
            proposal_id = str(content.get("proposal_id") or "")
            if proposal_id:
                interactions_by_proposal.setdefault(proposal_id, []).append(interaction)

        committed: list[tuple[RowMapping, RowMapping, RowMapping]] = []
        duplicates: list[tuple[RowMapping, RowMapping]] = []
        for proposal in proposal_rows:
            proposal_id = str(proposal["proposal_id"])
            interactions = interactions_by_proposal.get(proposal_id, [])
            if len(interactions) > 1:
                raise _conflict("Storyboard Proposal has ambiguous interaction lineage.")
            if not interactions:
                continue
            commit = (
                connection.execute(
                    select(AgentCanvasMaterializationCommitRow).where(
                        AgentCanvasMaterializationCommitRow.workflow_id == workflow_id,
                        AgentCanvasMaterializationCommitRow.proposal_id == proposal_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if commit is not None:
                if (
                    str(proposal["materialization_id"]) != commit["materialization_id"]
                    or str(proposal["materialization_turn_id"]) != commit["action_turn_id"]
                    or str(proposal["materialization_status"]) != "completed"
                ):
                    raise _conflict(
                        "Committed Storyboard Proposal does not match its immutable receipt."
                    )
                committed.append((proposal, interactions[0], commit))
            elif str(proposal["availability"]) != "superseded":
                duplicates.append((proposal, interactions[0]))
        if len(committed) != 1:
            raise _conflict(
                "Storyboard reconciliation requires exactly one committed stage authority."
            )
        if not duplicates:
            raise _conflict("Storyboard reconciliation found no later duplicate Proposal.")
        canonical, canonical_interaction, commit = committed[0]
        outcome = MaterializationOutcomeV1.model_validate_json(str(commit["outcome_json"]))
        if outcome.receipt_id is None:
            raise _conflict("Committed Storyboard receipt identity is missing.")
        duplicates.sort(key=lambda item: str(item[0]["proposal_id"]))
        payload = {
            "workflow_id": workflow_id,
            "source_evidence_workflow_id": "adwf_v2_894b22168ba29393",
            "expected_workflow_revision": int(workflow["revision"]),
            "session_id": str(session["session_id"]),
            "expected_session_revision": int(session["revision"]),
            "stage": journey.stage,
            "stage_revision": journey.stage_revision,
            "canonical_proposal_id": str(canonical["proposal_id"]),
            "canonical_interaction_id": str(canonical_interaction["interaction_id"]),
            "canonical_parent_turn_id": str(commit["action_turn_id"]),
            "canonical_materialization_id": str(commit["materialization_id"]),
            "canonical_receipt_id": outcome.receipt_id,
            "canonical_materialization_digest": str(commit["payload_digest"]),
            "duplicate_proposal_ids": tuple(str(item[0]["proposal_id"]) for item in duplicates),
            "duplicate_proposal_revisions": tuple(
                int(item[0]["proposal_revision"]) for item in duplicates
            ),
            "duplicate_interaction_ids": tuple(
                str(item[1]["interaction_id"]) for item in duplicates
            ),
            "duplicate_interaction_revisions": tuple(
                int(item[1]["revision"]) for item in duplicates
            ),
        }
        return StoryboardTerminalReconciliationPlanV1.model_validate(
            {**payload, "plan_digest": f"sha256:{_digest(payload)}"}
        )

    def _apply_plan_in_transaction(
        self,
        connection: Connection,
        *,
        plan: StoryboardTerminalReconciliationPlanV1,
        timestamp: str,
    ) -> None:
        for proposal_id, proposal_revision in zip(
            plan.duplicate_proposal_ids,
            plan.duplicate_proposal_revisions,
            strict=True,
        ):
            committed = connection.execute(
                select(AgentCanvasMaterializationCommitRow.materialization_id).where(
                    AgentCanvasMaterializationCommitRow.workflow_id == plan.workflow_id,
                    AgentCanvasMaterializationCommitRow.proposal_id == proposal_id,
                )
            ).scalar_one_or_none()
            if committed is not None:
                raise _conflict("A duplicate Proposal acquired committed authority before apply.")
            changed = connection.execute(
                update(AgentCanvasConceptProposalRow)
                .where(
                    AgentCanvasConceptProposalRow.workflow_id == plan.workflow_id,
                    AgentCanvasConceptProposalRow.proposal_id == proposal_id,
                    AgentCanvasConceptProposalRow.proposal_revision == proposal_revision,
                    AgentCanvasConceptProposalRow.availability != "superseded",
                )
                .values(availability="superseded", updated_at=timestamp)
            )
            if changed.rowcount != 1:
                raise _stale("Duplicate Storyboard Proposal changed before apply.")
        for interaction_id, interaction_revision in zip(
            plan.duplicate_interaction_ids,
            plan.duplicate_interaction_revisions,
            strict=True,
        ):
            changed = connection.execute(
                update(AgentCanvasGuidedInteractionRow)
                .where(
                    AgentCanvasGuidedInteractionRow.workflow_id == plan.workflow_id,
                    AgentCanvasGuidedInteractionRow.interaction_id == interaction_id,
                    AgentCanvasGuidedInteractionRow.revision == interaction_revision,
                    AgentCanvasGuidedInteractionRow.status != "superseded",
                )
                .values(status="superseded", updated_at=timestamp)
            )
            if changed.rowcount != 1:
                raise _stale("Duplicate Storyboard interaction changed before apply.")
        connection.execute(
            delete(AgentCanvasGuidanceAwaitingRow).where(
                AgentCanvasGuidanceAwaitingRow.workflow_id == plan.workflow_id,
                AgentCanvasGuidanceAwaitingRow.interaction_id.in_(
                    plan.duplicate_interaction_ids
                ),
            )
        )
        session = _one(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.session_id == plan.session_id,
                AgentCanvasGuidanceSessionRow.workflow_id == plan.workflow_id,
            ),
            "Storyboard reconciliation Guidance Session was not found.",
        )
        if session["active_proposal_id"] in plan.duplicate_proposal_ids:
            changed = connection.execute(
                update(AgentCanvasGuidanceSessionRow)
                .where(
                    AgentCanvasGuidanceSessionRow.session_id == plan.session_id,
                    AgentCanvasGuidanceSessionRow.revision
                    == plan.expected_session_revision,
                )
                .values(
                    active_proposal_id=None,
                    revision=plan.expected_session_revision + 1,
                    updated_at=timestamp,
                )
            )
            if changed.rowcount != 1:
                raise _stale("Guidance Session changed before reconciliation apply.")
        timeline_rows = (
            connection.execute(
                select(AgentCanvasChatEntryRow).where(
                    AgentCanvasChatEntryRow.workflow_id == plan.workflow_id
                )
            )
            .mappings()
            .all()
        )
        for row in timeline_rows:
            metadata = _json_object(row["metadata_json"])
            if metadata.get("proposal_id") not in plan.duplicate_proposal_ids:
                continue
            replacement = {
                key: value
                for key, value in metadata.items()
                if key != "actionable_failure"
            }
            replacement.update({"availability": "superseded", "retryable": False})
            if replacement != metadata:
                connection.execute(
                    update(AgentCanvasChatEntryRow)
                    .where(AgentCanvasChatEntryRow.entry_id == row["entry_id"])
                    .values(metadata_json=_json(replacement))
                )


def _event_receipt(
    connection: Connection,
    transition_key: str,
) -> StoryboardTerminalReconciliationReceiptV1 | None:
    value = connection.execute(
        select(WorkflowEventRow.payload_json).where(
            WorkflowEventRow.transition_key == transition_key
        )
    ).scalar_one_or_none()
    if value is None:
        return None
    payload = _json_object(value)
    payload.pop("_agent_canvas_event_envelope", None)
    return StoryboardTerminalReconciliationReceiptV1.model_validate(payload)


def _one(connection: Connection, statement, message: str) -> RowMapping:
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise _stale(message)
    return row


def _json_object(value: object) -> dict[str, object]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise _conflict("Storyboard reconciliation metadata is invalid.")
    return decoded


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _stale(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_terminal_reconciliation_stale",
        message,
        stage="storyboard_terminal_reconciliation",
    )


def _conflict(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_terminal_reconciliation_conflict",
        message,
        stage="storyboard_terminal_reconciliation",
    )
