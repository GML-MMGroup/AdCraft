"""Atomic SQLite authority snapshots for deterministic Guidance Advance."""

from __future__ import annotations

import hashlib
import json

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection, RowMapping

from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasConversationRow,
    AgentCanvasDecisionBundleRow,
    AgentCanvasExecutionResultCommitRow,
    AgentCanvasExecutionRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
    AgentCanvasPostReadyEffectRow,
    AgentCanvasWorkflowRow,
)
from app.schemas.agent_canvas_guidance import (
    GuidanceAdvanceAuthoritySnapshotV1,
    GuidanceAdvancePreconditionV1,
    GuidedActionExecutionLeafV1,
)
from app.schemas.agent_canvas_guided_checkpoint import GuidedCheckpointOriginV1


GUIDANCE_ADVANCE_PRECONDITION_FIELDS = (
    "schema_version",
    "workflow_id",
    "workflow_revision",
    "session_id",
    "session_revision",
    "session_status",
    "journey_stage",
    "journey_stage_status",
    "journey_stage_revision",
    "source_id",
    "requirement_revision_id",
    "requirement_digest",
    "active_action_digest",
    "owner_state_digest",
    "authority_digest",
)

GUIDANCE_ADVANCE_STALE_COMPONENTS = (
    "active_action",
    "journey",
    "owner_state",
    "requirements",
    "session",
    "workflow",
)

_NONTERMINAL_CONTINUATION_STATUSES = {"queued", "leased", "retry_wait"}


class GuidanceAdvanceAuthoritySnapshotRepository:
    """Read all Guidance command authority through a caller-owned transaction."""

    def __init__(self, requirements: AgentCanvasRequirementRepository) -> None:
        self._requirements = requirements

    def read_in_transaction(
        self,
        connection: Connection,
        workflow_id: str,
    ) -> GuidanceAdvanceAuthoritySnapshotV1:
        workflow = (
            connection.execute(
                select(AgentCanvasWorkflowRow).where(
                    AgentCanvasWorkflowRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if workflow is None:
            raise V2PersistenceError(
                "workflow_not_found",
                "Workflow was not found.",
                stage="guidance_authority_snapshot",
            )

        conversation_id = connection.execute(
            select(AgentCanvasConversationRow.conversation_id).where(
                AgentCanvasConversationRow.workflow_id == workflow_id
            )
        ).scalar_one_or_none()
        session_row = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        requirements = self._requirements.get_current_in_transaction(connection, workflow_id)
        session = None
        if session_row is not None:
            from app.persistence.agent_canvas_conversation_repository import (
                guidance_session_from_row,
            )

            session = guidance_session_from_row(connection, session_row)

        proposal_ids = tuple(
            str(value)
            for value in connection.execute(
                select(AgentCanvasConceptProposalRow.proposal_id)
                .where(
                    AgentCanvasConceptProposalRow.workflow_id == workflow_id,
                    AgentCanvasConceptProposalRow.availability == "open",
                )
                .order_by(
                    AgentCanvasConceptProposalRow.created_at.asc(),
                    AgentCanvasConceptProposalRow.proposal_id.asc(),
                )
            ).scalars()
        )
        bundle_ids = (
            tuple(
                str(value)
                for value in connection.execute(
                    select(AgentCanvasDecisionBundleRow.bundle_id)
                    .where(
                        AgentCanvasDecisionBundleRow.conversation_id == str(conversation_id),
                        AgentCanvasDecisionBundleRow.status == "open",
                    )
                    .order_by(
                        AgentCanvasDecisionBundleRow.created_at.asc(),
                        AgentCanvasDecisionBundleRow.bundle_id.asc(),
                    )
                ).scalars()
            )
            if conversation_id is not None
            else ()
        )
        continuation_rows = (
            connection.execute(
                select(AgentCanvasContinuationOutboxRow)
                .where(AgentCanvasContinuationOutboxRow.workflow_id == workflow_id)
                .order_by(
                    AgentCanvasContinuationOutboxRow.created_at.asc(),
                    AgentCanvasContinuationOutboxRow.continuation_id.asc(),
                )
            )
            .mappings()
            .all()
        )
        active_continuations = tuple(
            row
            for row in continuation_rows
            if str(row["status"]) in _NONTERMINAL_CONTINUATION_STATUSES
        )
        execution_leaf = (
            _execution_leaf(connection, workflow_id, session, continuation_rows)
            if session is not None
            else None
        )
        post_ready_owner = (
            _post_ready_owner(connection, workflow_id, session) if session is not None else None
        )
        owner_state: dict[str, JsonValue] = {
            "conversation_id": str(conversation_id) if conversation_id is not None else None,
            "session_active_proposal_id": (
                session.active_proposal_id if session is not None else None
            ),
            "open_proposal_ids": list(proposal_ids),
            "open_decision_bundle_ids": list(bundle_ids),
            "active_continuations": [
                {
                    "continuation_id": str(row["continuation_id"]),
                    "continuation_turn_id": str(row["continuation_turn_id"]),
                    "source_turn_id": str(row["source_turn_id"]),
                    "status": str(row["status"]),
                }
                for row in active_continuations
            ],
            "execution_leaf": (
                execution_leaf.model_dump(mode="json") if execution_leaf is not None else None
            ),
            "post_ready": post_ready_owner,
        }
        active_action = (
            session.journey.active_action.model_dump(mode="json")
            if session is not None and session.journey.active_action is not None
            else None
        )
        active_action_digest = canonical_guidance_digest(active_action)
        owner_state_digest = canonical_guidance_digest(owner_state)
        source_id = (
            session.journey.active_action.action_id
            if session is not None and session.journey.active_action is not None
            else (
                f"stage:{session.journey.stage}:{session.journey.stage_revision}"
                if session is not None
                else None
            )
        )
        eligible = bool(
            session is not None
            and session.status == "active"
            and session.journey.stage != "completed"
            and not proposal_ids
            and session.active_proposal_id is None
            and not bundle_ids
            and not active_continuations
            and not _leaf_blocks_advance(execution_leaf)
            and post_ready_owner is None
        )
        authority_payload: dict[str, JsonValue] = {
            "schema_version": "1",
            "workflow_id": workflow_id,
            "workflow_revision": int(workflow["revision"]),
            "session_id": session.session_id if session is not None else None,
            "session_revision": session.revision if session is not None else None,
            "session_status": session.status if session is not None else None,
            "journey_stage": session.journey.stage if session is not None else None,
            "journey_stage_status": (session.journey.stage_status if session is not None else None),
            "journey_stage_revision": (
                session.journey.stage_revision if session is not None else None
            ),
            "source_id": source_id,
            "requirement_revision_id": requirements.revision_id,
            "requirement_digest": requirements.digest,
            "active_action_digest": active_action_digest,
            "owner_state_digest": owner_state_digest,
            "owner_state": owner_state,
        }
        authority_digest = f"sha256:{canonical_guidance_digest(authority_payload)}"
        precondition = (
            GuidanceAdvancePreconditionV1(
                **{key: value for key, value in authority_payload.items() if key != "owner_state"},
                authority_digest=authority_digest,
            )
            if eligible
            else None
        )
        return GuidanceAdvanceAuthoritySnapshotV1(
            workflow_id=workflow_id,
            workflow_revision=int(workflow["revision"]),
            session=session,
            requirements=requirements,
            conversation_id=(str(conversation_id) if conversation_id is not None else None),
            open_proposal_id=proposal_ids[0] if proposal_ids else None,
            open_decision_bundle_id=bundle_ids[0] if bundle_ids else None,
            active_continuation_id=(
                str(active_continuations[0]["continuation_id"]) if active_continuations else None
            ),
            execution_leaf=execution_leaf,
            post_ready_owner=post_ready_owner,
            source_id=source_id,
            active_action_digest=active_action_digest,
            owner_state_digest=owner_state_digest,
            authority_digest=authority_digest,
            eligible=eligible,
            precondition=precondition,
        )


def canonical_guidance_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_guidance_digest(value: object) -> str:
    return hashlib.sha256(canonical_guidance_json(value).encode("utf-8")).hexdigest()


def stale_guidance_components(
    submitted: GuidanceAdvancePreconditionV1,
    current: GuidanceAdvanceAuthoritySnapshotV1,
) -> tuple[str, ...]:
    current_precondition = current.precondition
    if current_precondition is None:
        return ("owner_state",)
    stale: set[str] = set()
    if (
        submitted.workflow_id != current_precondition.workflow_id
        or submitted.workflow_revision != current_precondition.workflow_revision
    ):
        stale.add("workflow")
    if (
        submitted.session_id != current_precondition.session_id
        or submitted.session_revision != current_precondition.session_revision
        or submitted.session_status != current_precondition.session_status
    ):
        stale.add("session")
    if (
        submitted.journey_stage != current_precondition.journey_stage
        or submitted.journey_stage_status != current_precondition.journey_stage_status
        or submitted.journey_stage_revision != current_precondition.journey_stage_revision
    ):
        stale.add("journey")
    if (
        submitted.requirement_revision_id != current_precondition.requirement_revision_id
        or submitted.requirement_digest != current_precondition.requirement_digest
    ):
        stale.add("requirements")
    if submitted.active_action_digest != current_precondition.active_action_digest:
        stale.add("active_action")
    if submitted.source_id != current_precondition.source_id:
        if str(submitted.source_id).startswith("stage:") and str(
            current_precondition.source_id
        ).startswith("stage:"):
            stale.add("journey")
        else:
            stale.add("active_action")
    if submitted.owner_state_digest != current_precondition.owner_state_digest:
        stale.add("owner_state")
    if submitted.authority_digest != current_precondition.authority_digest and not stale:
        stale.add("owner_state")
    return tuple(sorted(stale))


def require_guidance_advance_eligible(
    snapshot: GuidanceAdvanceAuthoritySnapshotV1,
) -> None:
    """Preserve precise owner errors before applying stale-precondition CAS."""

    session = snapshot.session
    if session is None or session.status != "active" or session.journey.stage == "completed":
        raise V2PersistenceError(
            "guidance_advance_not_available",
            "Guidance is not available in the current session state.",
            stage="guidance_advance_service",
        )
    if snapshot.open_proposal_id is not None or session.active_proposal_id is not None:
        raise V2PersistenceError(
            "guidance_advance_not_available",
            "An open Proposal currently owns the next user action.",
            stage="guidance_advance_service",
        )
    if snapshot.open_decision_bundle_id is not None:
        raise V2PersistenceError(
            "guidance_advance_not_available",
            "An open Decision Bundle currently owns the next user action.",
            stage="guidance_advance_service",
        )
    if snapshot.active_continuation_id is not None:
        raise V2PersistenceError(
            "active_continuation_conflict",
            "Another continuation already owns this workflow.",
            stage="guidance_advance_service",
        )
    leaf = snapshot.execution_leaf
    if leaf is not None and (
        leaf.leaf_status in {"queued", "running"}
        or leaf.continuation_status in _NONTERMINAL_CONTINUATION_STATUSES
    ):
        raise V2PersistenceError(
            "guidance_advance_not_available",
            "Current journey work is already active.",
            stage="guidance_advance_service",
        )
    if leaf is not None and leaf.leaf_status == "failed":
        raise V2PersistenceError(
            "guidance_advance_blocked_by_failed_turn",
            "Current guided work must be resolved before continuing.",
            stage="guidance_advance_service",
            details={
                "turn_id": leaf.leaf_turn_id,
                "error_code": leaf.error_code or "agent_operation_failed",
                "retryable": leaf.retryable,
            },
        )
    post_ready = _snapshot_post_ready_owner(snapshot)
    if post_ready is None:
        return
    details = {
        "checkpoint_id": post_ready.get("checkpoint_id"),
        "execution_id": post_ready.get("execution_id"),
        "journey_stage": post_ready.get("stage"),
        "stage_revision": post_ready.get("stage_revision"),
        "status": post_ready.get("status"),
        "retryable": post_ready.get("status") == "pending",
    }
    if post_ready.get("status") == "pending":
        raise V2PersistenceError(
            "guidance_post_ready_pending",
            "Guided post-Ready progression is still pending.",
            stage="guidance_authority_snapshot",
            details={**details, "retry_after_seconds": 1},
        )
    if post_ready.get("status") == "failed":
        raise V2PersistenceError(
            "post_ready_progression_failed",
            "Guided post-Ready progression failed.",
            stage="guidance_authority_snapshot",
            details={
                **details,
                "error_code": post_ready.get("error_code") or "post_ready_effect_failed",
            },
        )
    raise V2PersistenceError(
        "post_ready_checkpoint_unavailable",
        "Guided post-Ready checkpoint lineage is unavailable.",
        stage="guidance_authority_snapshot",
        details=details,
    )


def guidance_advance_stale_error(
    submitted: GuidanceAdvancePreconditionV1,
    current: GuidanceAdvanceAuthoritySnapshotV1,
    *,
    stage: str,
) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_advance_stale",
        "Guidance Advance no longer matches current authoring state.",
        stage=stage,
        details={
            "refresh_required": True,
            "stale_components": list(stale_guidance_components(submitted, current)),
        },
    )


def _execution_leaf(
    connection: Connection,
    workflow_id: str,
    session,
    continuation_rows: list[RowMapping],
) -> GuidedActionExecutionLeafV1 | None:
    action = session.journey.active_action
    if action is None or not action.turn_id:
        return None
    current = _require_turn(connection, action.turn_id, workflow_id)
    incoming = next(
        (
            row
            for row in continuation_rows
            if str(row["continuation_turn_id"]) == str(current["turn_id"])
        ),
        None,
    )
    root_turn_id = str(current["turn_id"])
    visited: set[str] = set()
    for _ in range(32):
        current_id = str(current["turn_id"])
        if current_id in visited:
            raise _lineage_error("Guided action execution lineage contains a cycle.")
        visited.add(current_id)
        delivery_children = [
            row for row in continuation_rows if str(row["source_turn_id"]) == current_id
        ]
        retry_children = (
            connection.execute(
                select(AgentCanvasChatTurnRow).where(
                    AgentCanvasChatTurnRow.retry_of_turn_id == current_id
                )
            )
            .mappings()
            .all()
        )
        child_ids = {str(row["continuation_turn_id"]) for row in delivery_children} | {
            str(row["turn_id"]) for row in retry_children
        }
        if not child_ids:
            break
        if len(child_ids) != 1:
            raise _lineage_error("Guided action execution lineage is ambiguous.")
        child_id = next(iter(child_ids))
        current = _require_turn(connection, child_id, workflow_id)
        matching = [
            row for row in delivery_children if str(row["continuation_turn_id"]) == child_id
        ]
        if len(matching) != 1:
            raise _lineage_error("Typed retry lineage is missing its Continuation.")
        incoming = matching[0]
    else:
        raise _lineage_error("Guided action execution lineage exceeds its bound.")
    return GuidedActionExecutionLeafV1(
        workflow_id=workflow_id,
        logical_action_id=action.action_id,
        root_turn_id=root_turn_id,
        leaf_turn_id=str(current["turn_id"]),
        leaf_turn_kind=str(current["turn_kind"]),
        leaf_status=str(current["status"]),
        continuation_id=(str(incoming["continuation_id"]) if incoming is not None else None),
        continuation_status=(str(incoming["status"]) if incoming is not None else None),
        operation=(str(incoming["operation"]) if incoming is not None else None),
        retry_attempt_no=int(current["retry_attempt_no"]),
        error_code=(str(current["error_code"]) if current["error_code"] else None),
        retryable=bool(current["retryable"]),
    )


def _post_ready_owner(
    connection: Connection,
    workflow_id: str,
    session,
) -> dict[str, JsonValue] | None:
    if session.journey.stage != "storyboard_grids":
        return None
    rows = (
        connection.execute(
            select(AgentCanvasNodeRow)
            .where(AgentCanvasNodeRow.workflow_id == workflow_id)
            .order_by(AgentCanvasNodeRow.node_id.asc())
        )
        .mappings()
        .all()
    )
    for row in rows:
        metadata = json.loads(str(row["metadata_json"]))
        raw_origin = metadata.get("guided_checkpoint")
        if raw_origin is None:
            continue
        try:
            origin = GuidedCheckpointOriginV1.model_validate(raw_origin)
        except ValidationError:
            if str(row["creative_role"]) == "storyboard_sequence" and str(row["status"]) == "ready":
                return {
                    "checkpoint_id": None,
                    "node_id": str(row["node_id"]),
                    "stage": "storyboard_grids",
                    "stage_revision": session.journey.stage_revision,
                    "execution_id": None,
                    "status": "unavailable",
                }
            continue
        if (
            origin.guidance_session_id != session.session_id
            or origin.stage_revision != session.journey.stage_revision
        ):
            continue
        base = {
            "checkpoint_id": origin.checkpoint_id,
            "node_id": str(row["node_id"]),
            "stage": origin.stage,
            "stage_revision": origin.stage_revision,
        }
        if str(row["status"]) in {"draft", "working"}:
            return {**base, "execution_id": None, "status": "pending"}
        if str(row["status"]) != "ready":
            continue
        commit = (
            connection.execute(
                select(AgentCanvasExecutionResultCommitRow)
                .where(
                    AgentCanvasExecutionResultCommitRow.workflow_id == workflow_id,
                    AgentCanvasExecutionResultCommitRow.node_id == str(row["node_id"]),
                    AgentCanvasExecutionResultCommitRow.outcome == "succeeded",
                )
                .order_by(
                    AgentCanvasExecutionResultCommitRow.committed_at.desc(),
                    AgentCanvasExecutionResultCommitRow.commit_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if commit is None:
            return {**base, "execution_id": None, "status": "unavailable"}
        execution_id = str(commit["execution_id"])
        execution_status = connection.execute(
            select(AgentCanvasExecutionRow.status).where(
                AgentCanvasExecutionRow.execution_id == execution_id
            )
        ).scalar_one_or_none()
        if execution_status is None:
            return {**base, "execution_id": execution_id, "status": "unavailable"}
        effects = (
            connection.execute(
                select(
                    AgentCanvasPostReadyEffectRow.status, AgentCanvasPostReadyEffectRow.error_json
                )
                .where(AgentCanvasPostReadyEffectRow.source_commit_id == str(commit["commit_id"]))
                .order_by(AgentCanvasPostReadyEffectRow.effect_id.asc())
            )
            .mappings()
            .all()
        )
        if execution_status in {"queued", "running", "waiting"} or any(
            str(effect["status"]) in {"queued", "running"} for effect in effects
        ):
            return {**base, "execution_id": execution_id, "status": "pending"}
        failed_effect = next(
            (effect for effect in effects if str(effect["status"]) == "failed"),
            None,
        )
        if execution_status in {"failed", "cancelled"} or failed_effect is not None:
            error_code = None
            if failed_effect is not None and failed_effect["error_json"]:
                error_code = json.loads(str(failed_effect["error_json"])).get("code")
            return {
                **base,
                "execution_id": execution_id,
                "status": "failed",
                "error_code": error_code or f"execution_{execution_status}",
            }
    return None


def _snapshot_post_ready_owner(
    snapshot: GuidanceAdvanceAuthoritySnapshotV1,
) -> dict[str, JsonValue] | None:
    return snapshot.post_ready_owner


def _require_turn(connection: Connection, turn_id: str, workflow_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(AgentCanvasChatTurnRow).where(AgentCanvasChatTurnRow.turn_id == turn_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None or str(row["workflow_id"]) != workflow_id:
        raise _lineage_error("Guided action execution lineage crosses a Workflow.")
    return row


def _leaf_blocks_advance(leaf: GuidedActionExecutionLeafV1 | None) -> bool:
    return bool(
        leaf is not None
        and (
            leaf.leaf_status in {"queued", "running", "failed"}
            or leaf.continuation_status in _NONTERMINAL_CONTINUATION_STATUSES
        )
    )


def _lineage_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_action_lineage_invalid",
        message,
        stage="guidance_authority_snapshot",
    )
