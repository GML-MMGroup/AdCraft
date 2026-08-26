"""SQLite authority for typed Product source-only materialization."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _advance_workflow_revision,
    _idempotency_conflict_error,
    _load_idempotency,
    _node_values,
    _require_workflow_revision,
    _store_idempotency,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasGuidedProductHandoffRow,
    AgentCanvasChatTurnRow,
    AgentCanvasNodeRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_conversation import ContinuationCommitV2
from app.schemas.agent_canvas_guided_product import (
    GuidedProductInputCommitReceiptV1,
    GuidedProductInputCommitRequestV1,
    GuidedProductInputCommitResponseV1,
    GuidedProductAssetVersionRefV1,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
    GuidedProductSourceQuestionV1,
    GuidedProductSourceSubmitV1,
)
from app.schemas.agent_canvas_production_journey import (
    GuidedProductionJourneyV2,
    JourneyActionProjectionV2,
    JourneyEvidenceV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    parse_production_journey,
)


class AgentCanvasGuidedProductRepository:
    """Commit source-only Product Nodes and receipts in one SQLite transaction."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        events: EventRepository,
    ) -> None:
        self._workflows = workflows
        self._events = events

    def create_pending_handoff(
        self,
        *,
        workflow_id: str,
        session_id: str,
        input_kind: str,
        asset_versions: tuple[GuidedProductAssetVersionRefV1, ...],
        idempotency_key: str,
    ) -> str:
        """Persist one explicit Product handoff without creating a Canvas Node."""

        payload = {
            "workflow_id": workflow_id,
            "session_id": session_id,
            "input_kind": input_kind,
            "asset_versions": [item.model_dump(mode="json") for item in asset_versions],
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        handoff_id = f"handoff_product_{digest[:32]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._workflows.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(AgentCanvasGuidedProductHandoffRow).where(
                            AgentCanvasGuidedProductHandoffRow.handoff_id == handoff_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if str(existing["request_digest"]) != digest:
                        raise V2PersistenceError(
                            "idempotency_conflict",
                            "Product handoff identity was reused with different content.",
                            stage="guided_product_handoff",
                        )
                    connection.commit()
                    return handoff_id
                session = connection.execute(
                    select(AgentCanvasGuidanceSessionRow.session_id).where(
                        AgentCanvasGuidanceSessionRow.session_id == session_id,
                        AgentCanvasGuidanceSessionRow.workflow_id == workflow_id,
                    )
                ).scalar_one_or_none()
                if session is None:
                    raise V2PersistenceError(
                        "guided_interaction_not_found",
                        "Guidance session was not found.",
                        stage="guided_product_handoff",
                    )
                connection.execute(
                    insert(AgentCanvasGuidedProductHandoffRow).values(
                        handoff_id=handoff_id,
                        workflow_id=workflow_id,
                        session_id=session_id,
                        input_kind=input_kind,
                        asset_versions_json=json.dumps(
                            payload["asset_versions"], separators=(",", ":")
                        ),
                        request_digest=digest,
                        status="pending",
                        created_at=now,
                        updated_at=now,
                        consumed_at=None,
                    )
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guided_product_source_pending",
                        transition_key=f"guided-product-handoff:{handoff_id}:pending",
                        created_at=now,
                        payload={
                            "handoff_id": handoff_id,
                            "session_id": session_id,
                            "input_kind": input_kind,
                            "asset_versions": payload["asset_versions"],
                            "request_digest": digest,
                        },
                    ),
                )
                connection.commit()
                return handoff_id
            except BaseException:
                connection.rollback()
                raise

    def get_pending_handoff(self, workflow_id: str, handoff_id: str) -> dict[str, object] | None:
        with self._workflows.database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasGuidedProductHandoffRow).where(
                        AgentCanvasGuidedProductHandoffRow.workflow_id == workflow_id,
                        AgentCanvasGuidedProductHandoffRow.handoff_id == handoff_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return dict(row)

    def record_pending_submission(
        self,
        *,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedProductSourceSubmitV1,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        """Record an early handoff without closing the Product interaction or running it."""

        request_digest_value = sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        with self._workflows.database.engine.connect() as connection:
            existing = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionSubmissionRow).where(
                        AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if existing is not None:
            if str(existing["request_digest"]) != request_digest_value:
                raise V2PersistenceError(
                    "guided_interaction_submission_conflict",
                    "Submission identity was reused with different content.",
                    stage="guided_product_repository",
                )
            return GuidedInteractionAcceptedV1.model_validate_json(
                str(existing["result_json"])
            ).model_copy(update={"replayed": True})
        handoff_id = self.create_pending_handoff(
            workflow_id=workflow_id,
            session_id=interaction.session_id,
            input_kind=request.action.input_kind,
            asset_versions=request.action.asset_versions,
            idempotency_key=idempotency_key,
        )
        with self._workflows.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionSubmissionRow).where(
                            AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if str(existing["request_digest"]) != request_digest_value:
                        raise V2PersistenceError(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different content.",
                            stage="guided_product_repository",
                        )
                    connection.commit()
                    return GuidedInteractionAcceptedV1.model_validate_json(
                        str(existing["result_json"])
                    ).model_copy(update={"replayed": True})
                cursor = connection.execute(
                    select(WorkflowEventRow.seq)
                    .where(WorkflowEventRow.workflow_id == workflow_id)
                    .order_by(WorkflowEventRow.seq.desc())
                ).scalar()
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=handoff_id,
                    resulting_session_revision=interaction.expected_session_revision,
                    events_cursor=int(cursor or 0),
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest_value,
                        request_json=request.model_dump_json(),
                        result_json=accepted.model_dump_json(),
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def submit_generate(
        self,
        *,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedProductSourceSubmitV1,
        submission_id: str,
        idempotency_key: str,
        continuation_writer: Callable[..., None] | None,
    ) -> GuidedInteractionAcceptedV1:
        """Close a Product source choice and queue the existing Product continuation."""

        if continuation_writer is None:
            raise V2PersistenceError(
                "guidance_continuation_unavailable",
                "Product generation cannot publish its continuation.",
                stage="guided_product_repository",
            )
        request_json = request.model_dump_json()
        request_digest_value = sha256(request_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._workflows.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionSubmissionRow).where(
                            AgentCanvasGuidedInteractionSubmissionRow.submission_id == submission_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if str(existing["request_digest"]) != request_digest_value:
                        raise V2PersistenceError(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different content.",
                            stage="guided_product_repository",
                        )
                    connection.rollback()
                    return GuidedInteractionAcceptedV1.model_validate_json(
                        str(existing["result_json"])
                    ).model_copy(update={"replayed": True})

                _current_interaction, awaiting = self._require_product_interaction(
                    connection,
                    workflow_id=workflow_id,
                    input_kind=request.action.input_kind,
                    interaction_id=interaction.interaction_id,
                    expected_interaction_revision=request.expected_interaction_revision,
                    expected_session_revision=request.expected_session_revision,
                )
                source_turn = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow)
                        .where(
                            AgentCanvasChatTurnRow.workflow_id == workflow_id,
                            AgentCanvasChatTurnRow.status.in_(("queued", "running", "completed")),
                        )
                        .order_by(
                            AgentCanvasChatTurnRow.created_at.desc(),
                            AgentCanvasChatTurnRow.turn_id.desc(),
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_turn is None:
                    raise V2PersistenceError(
                        "guidance_resume_evidence_missing",
                        "Product generation source Turn is unavailable.",
                        stage="guided_product_repository",
                    )
                session = (
                    connection.execute(
                        select(AgentCanvasGuidanceSessionRow).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id,
                            AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                identity = sha256(
                    f"product-generate:{workflow_id}:{submission_id}".encode("utf-8")
                ).hexdigest()
                continuation_id = f"continuation_{identity[:24]}"
                continuation_turn_id = f"turn_{identity[24:56]}"
                continuation_writer(
                    connection,
                    workflow_id=workflow_id,
                    conversation_id=str(source_turn["conversation_id"]),
                    continuation=ContinuationCommitV2(
                        continuation_id=continuation_id,
                        continuation_turn_id=continuation_turn_id,
                        source_turn_id=str(source_turn["turn_id"]),
                        source_action_id=interaction.interaction_id,
                        idempotency_key=f"product-generate:{workflow_id}:{submission_id}",
                    ),
                    now=now,
                )
                next_session_revision = request.expected_session_revision + 1
                journey = parse_production_journey(str(session["journey_state_json"]))
                next_journey = journey.model_copy(
                    update={
                        "stage_status": "working",
                        "active_action": JourneyActionProjectionV2(
                            action_id=f"product-generate:{interaction.interaction_id}",
                            action_kind="invoke_capability",
                            stage="product",
                            stage_revision=journey.stage_revision,
                            status="reserved",
                            turn_id=continuation_turn_id,
                            occurrence_id=journey.active_occurrence_id,
                        ),
                    }
                )
                connection.execute(
                    update(AgentCanvasGuidedInteractionRow)
                    .where(
                        AgentCanvasGuidedInteractionRow.interaction_id
                        == interaction.interaction_id,
                        AgentCanvasGuidedInteractionRow.status == "open",
                    )
                    .values(status="closed", revision=interaction.revision + 1, updated_at=now)
                )
                connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting["awaiting_id"]
                    )
                )
                updated_session = connection.execute(
                    update(AgentCanvasGuidanceSessionRow)
                    .where(
                        AgentCanvasGuidanceSessionRow.session_id == interaction.session_id,
                        AgentCanvasGuidanceSessionRow.revision == request.expected_session_revision,
                    )
                    .values(
                        journey_state_json=next_journey.model_dump_json(),
                        revision=next_session_revision,
                        updated_at=now,
                    )
                )
                if updated_session.rowcount != 1:
                    raise V2PersistenceError(
                        "guidance_revision_conflict",
                        "Guidance session changed before Product generation submit.",
                        stage="guided_product_repository",
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guided_interaction_submitted",
                        transition_key=f"guided-submission:{submission_id}:submitted",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "interaction_id": interaction.interaction_id,
                            "submission_id": submission_id,
                            "kind": interaction.kind,
                            "choice": "generate",
                        },
                    ),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guidance-awaiting:{awaiting['awaiting_id']}:resumed",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "awaiting_id": awaiting["awaiting_id"],
                            "interaction_id": interaction.interaction_id,
                            "resume_evidence": "product_generate",
                        },
                    ),
                )
                final_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="journey_stage_started",
                        transition_key=f"guided-submission:{submission_id}:journey",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "stage": journey.stage,
                            "stage_revision": journey.stage_revision,
                            "source_submission_id": submission_id,
                        },
                    ),
                )
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=f"receipt_{submission_id}",
                    continuation_id=continuation_id,
                    resulting_session_revision=next_session_revision,
                    events_cursor=final_event.seq,
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest_value,
                        request_json=request_json,
                        result_json=accepted.model_dump_json(),
                        created_at=now,
                    )
                )
                connection.commit()
                return accepted
            except BaseException:
                connection.rollback()
                raise

    def commit(
        self,
        *,
        node: CanvasNodeV2,
        request: GuidedProductInputCommitRequestV1,
        idempotency_key: str,
        request_digest: str,
        expected_workflow_revision: int,
        guidance_revision: int,
        compiled_asset: ProjectAssetSummaryV2 | None,
        output_asset_id: str,
        output_version_id: str,
        provenance_digest: str | None,
        submission_id: str | None = None,
        submission_request: GuidedProductSourceSubmitV1 | None = None,
    ) -> GuidedProductInputCommitResponseV1:
        operation = f"guided_product_input:{node.workflow_id}"
        database = self._workflows.database
        try:
            with database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = _load_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_digest,
                    )
                    if replay is not None:
                        connection.commit()
                        return GuidedProductInputCommitResponseV1.model_validate_json(
                            replay
                        ).model_copy(update={"replayed": True})

                    current_revision = _require_workflow_revision(
                        connection,
                        node.workflow_id,
                        expected_workflow_revision,
                    )
                    existing = connection.execute(
                        select(AgentCanvasNodeRow.node_id).where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.creative_role == "product",
                            AgentCanvasNodeRow.metadata_json.contains(
                                f'"source_input_kind":"{request.input_kind}"'
                            ),
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        raise V2PersistenceError(
                            "guided_product_input_already_committed",
                            "This Product input kind already has a canonical source Node.",
                            stage="guided_product_repository",
                        )
                    guidance_revision_row = connection.execute(
                        select(AgentCanvasGuidanceSessionRow.revision).where(
                            AgentCanvasGuidanceSessionRow.workflow_id == node.workflow_id
                        )
                    ).scalar_one_or_none()
                    current_guidance_revision = (
                        int(guidance_revision_row) if guidance_revision_row is not None else 1
                    )
                    if current_guidance_revision != guidance_revision:
                        raise V2PersistenceError(
                            "guidance_revision_conflict",
                            "Guidance session revision does not match the current revision.",
                            stage="guided_product_repository",
                        )
                    previous_journey = parse_production_journey(
                        str(
                            connection.execute(
                                select(AgentCanvasGuidanceSessionRow.journey_state_json).where(
                                    AgentCanvasGuidanceSessionRow.workflow_id == node.workflow_id
                                )
                            ).scalar_one()
                        )
                    )
                    interaction, awaiting = self._require_product_interaction(
                        connection,
                        workflow_id=node.workflow_id,
                        input_kind=request.input_kind,
                        interaction_id=request.interaction_id,
                        expected_interaction_revision=request.expected_interaction_revision,
                        expected_session_revision=request.expected_session_revision,
                    )
                    handoff = self._require_pending_handoff(
                        connection,
                        workflow_id=node.workflow_id,
                        request=request,
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    _advance_workflow_revision(
                        connection,
                        workflow_id=node.workflow_id,
                        current_revision=current_revision,
                        updated_at=node.updated_at.isoformat(),
                    )
                    next_revision = current_revision + 1
                    next_session_revision = request.expected_session_revision + 1
                    next_journey = self._next_journey(
                        connection,
                        workflow_id=node.workflow_id,
                        request=request,
                        node=node,
                        journey=previous_journey,
                        next_session_revision=next_session_revision,
                    )
                    connection.execute(
                        update(AgentCanvasGuidedInteractionRow)
                        .where(
                            AgentCanvasGuidedInteractionRow.interaction_id
                            == request.interaction_id,
                            AgentCanvasGuidedInteractionRow.status == "open",
                        )
                        .values(
                            status="closed",
                            revision=request.expected_interaction_revision + 1,
                            updated_at=node.updated_at.isoformat(),
                        )
                    )
                    connection.execute(
                        delete(AgentCanvasGuidanceAwaitingRow).where(
                            AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting["awaiting_id"]
                        )
                    )
                    if handoff is not None:
                        connection.execute(
                            update(AgentCanvasGuidedProductHandoffRow)
                            .where(
                                AgentCanvasGuidedProductHandoffRow.handoff_id
                                == request.pending_handoff_id,
                                AgentCanvasGuidedProductHandoffRow.status == "pending",
                            )
                            .values(
                                status="consumed",
                                consumed_at=node.updated_at.isoformat(),
                                updated_at=node.updated_at.isoformat(),
                            )
                        )
                    updated_session = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == interaction["session_id"],
                            AgentCanvasGuidanceSessionRow.revision
                            == request.expected_session_revision,
                        )
                        .values(
                            journey_state_json=next_journey.model_dump_json(),
                            revision=next_session_revision,
                            updated_at=node.updated_at.isoformat(),
                        )
                    )
                    if updated_session.rowcount != 1:
                        raise V2PersistenceError(
                            "guidance_revision_conflict",
                            "Guidance session changed before Product source commit.",
                            stage="guided_product_repository",
                        )
                    operation_id = f"op_{uuid4().hex}"
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            node_id=node.node_id,
                            asset_id=output_asset_id,
                            version_id=output_version_id,
                            event_type="guided_product_source_materialized",
                            transition_key=f"guided-product:{node.workflow_id}:{request.input_kind}",
                            created_at=node.updated_at.isoformat(),
                            payload={
                                "operation_id": operation_id,
                                "input_kind": request.input_kind,
                                "node_revision": node.revision,
                                "workflow_revision": next_revision,
                                "provenance_digest": provenance_digest,
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            event_type="guidance_awaiting_resumed",
                            transition_key=(
                                f"guided-product:{request.interaction_id}:awaiting-resumed"
                            ),
                            created_at=node.updated_at.isoformat(),
                            payload={
                                "interaction_id": request.interaction_id,
                                "input_kind": request.input_kind,
                                "resume_evidence": "product_source_commit",
                            },
                        ),
                    )
                    final_event = self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=node.workflow_id,
                            event_type=(
                                "journey_stage_changed"
                                if next_journey.stage != previous_journey.stage
                                else "journey_stage_started"
                            ),
                            transition_key=(
                                f"guided-product:{request.interaction_id}:journey:{next_session_revision}"
                            ),
                            created_at=node.updated_at.isoformat(),
                            payload={
                                "input_kind": request.input_kind,
                                "next_stage": next_journey.stage,
                                "stage_revision": next_journey.stage_revision,
                                "session_revision": next_session_revision,
                            },
                        ),
                    )
                    receipt = GuidedProductInputCommitReceiptV1(
                        operation_id=operation_id,
                        request_digest=request_digest,
                        workflow_id=node.workflow_id,
                        input_kind=request.input_kind,
                        node_id=node.node_id,
                        asset_id=output_asset_id,
                        version_id=output_version_id,
                        compiled_asset_id=(compiled_asset.asset_id if compiled_asset else None),
                        compiled_version_id=(compiled_asset.version_id if compiled_asset else None),
                        provenance_digest=provenance_digest,
                        workflow_revision=next_revision,
                        guidance_revision=next_session_revision,
                        events_cursor=final_event.seq,
                        committed_at=datetime.now(timezone.utc),
                    )
                    response = GuidedProductInputCommitResponseV1(
                        workflow_id=node.workflow_id,
                        workflow_revision=next_revision,
                        guidance_revision=next_session_revision,
                        input_kind=request.input_kind,
                        node=node,
                        compiled_asset=compiled_asset,
                        receipt=receipt,
                        events_cursor=final_event.seq,
                    )
                    _store_idempotency(
                        connection,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_digest,
                        response_json=response.model_dump_json(),
                        created_at=node.updated_at.isoformat(),
                    )
                    if submission_id is not None and submission_request is not None:
                        accepted = GuidedInteractionAcceptedV1(
                            workflow_id=node.workflow_id,
                            interaction_id=request.interaction_id,
                            submission_id=submission_id,
                            receipt_id=receipt.operation_id,
                            created_node_ids=(node.node_id,),
                            resulting_session_revision=next_session_revision,
                            events_cursor=final_event.seq,
                        )
                        connection.execute(
                            insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                                submission_id=submission_id,
                                workflow_id=node.workflow_id,
                                interaction_id=request.interaction_id,
                                idempotency_key=idempotency_key,
                                request_digest=sha256(
                                    submission_request.model_dump_json().encode("utf-8")
                                ).hexdigest(),
                                request_json=submission_request.model_dump_json(),
                                result_json=accepted.model_dump_json(),
                                created_at=node.updated_at.isoformat(),
                            )
                        )
                    connection.commit()
                    return response
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _idempotency_conflict_error() from error
        except SQLAlchemyError as error:
            raise V2PersistenceError(
                "guided_product_persistence_unavailable",
                "Product source materialization could not be persisted.",
                stage="guided_product_repository",
            ) from error

    @staticmethod
    def _require_product_interaction(
        connection,
        *,
        workflow_id,
        input_kind,
        interaction_id,
        expected_interaction_revision,
        expected_session_revision,
    ):
        row = (
            connection.execute(
                select(AgentCanvasGuidedInteractionRow).where(
                    AgentCanvasGuidedInteractionRow.interaction_id == interaction_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or str(row["status"]) != "open":
            raise V2PersistenceError(
                "guided_interaction_not_found",
                "The Product source interaction was not found or is closed.",
                stage="guided_product_repository",
            )
        if str(row["workflow_id"]) != workflow_id:
            raise V2PersistenceError(
                "guided_interaction_not_found",
                "The Product source interaction does not belong to this Workflow.",
                stage="guided_product_repository",
            )
        if int(row["revision"]) != expected_interaction_revision:
            raise V2PersistenceError(
                "guided_interaction_stale",
                "Product source interaction revision is stale.",
                stage="guided_product_repository",
            )
        content = json.loads(str(row["content_json"]))
        if str(row["kind"]) != "product_source" or content.get("input_kind") != input_kind:
            raise V2PersistenceError(
                "guided_interaction_action_not_allowed",
                "The Product source interaction does not match this input kind.",
                stage="guided_product_repository",
            )
        awaiting = (
            connection.execute(
                select(AgentCanvasGuidanceAwaitingRow).where(
                    AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id,
                    AgentCanvasGuidanceAwaitingRow.interaction_id == interaction_id,
                    AgentCanvasGuidanceAwaitingRow.kind == "product_source",
                )
            )
            .mappings()
            .one_or_none()
        )
        if awaiting is None:
            raise V2PersistenceError(
                "guidance_resume_evidence_missing",
                "The Product source interaction is not the current awaiting authority.",
                stage="guided_product_repository",
            )
        if int(row["expected_session_revision"]) != expected_session_revision:
            raise V2PersistenceError(
                "guided_interaction_stale",
                "Product source session revision is stale.",
                stage="guided_product_repository",
            )
        return row, awaiting

    @staticmethod
    def _require_pending_handoff(connection, *, workflow_id, request):
        if request.pending_handoff_id is None:
            return None
        row = (
            connection.execute(
                select(AgentCanvasGuidedProductHandoffRow).where(
                    AgentCanvasGuidedProductHandoffRow.handoff_id == request.pending_handoff_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise V2PersistenceError(
                "guided_product_handoff_not_found",
                "Product pending handoff was not found.",
                stage="guided_product_repository",
            )
        if (
            str(row["workflow_id"]) != workflow_id
            or str(row["input_kind"]) != request.input_kind
            or str(row["status"]) != "pending"
            or json.loads(str(row["asset_versions_json"]))
            != [item.model_dump(mode="json") for item in request.asset_versions]
        ):
            raise V2PersistenceError(
                "guided_product_handoff_conflict",
                "Product pending handoff does not match the typed source selection.",
                stage="guided_product_repository",
            )
        return row

    def _next_journey(
        self,
        connection,
        *,
        workflow_id,
        request,
        node: CanvasNodeV2,
        journey: GuidedProductionJourneyV2,
        next_session_revision: int,
    ) -> GuidedProductionJourneyV2:
        if request.input_kind == "multiview":
            return GuidedProductionJourneyPolicyService().apply_evidence(
                journey,
                JourneyEvidenceV2(
                    evidence_id=f"guided-product:{request.interaction_id}:{node.node_id}",
                    evidence_kind="product_materialized",
                    source_id=node.node_id,
                    source_revision=node.revision,
                    stage="product",
                    stage_revision=journey.stage_revision,
                    occurrence_id=journey.active_occurrence_id,
                    actor="user",
                ),
            )
        identity = sha256(
            f"product-multiview:{request.interaction_id}:{next_session_revision}".encode("utf-8")
        ).hexdigest()[:32]
        connection.execute(
            delete(AgentCanvasGuidanceAwaitingRow).where(
                AgentCanvasGuidanceAwaitingRow.workflow_id == workflow_id
            )
        )
        interaction_id = f"interaction_product_source_{identity}"
        checkpoint_id = f"product_source:{journey.stage_revision}:multiview"
        now = datetime.now(timezone.utc)
        session = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one()
        )
        question = GuidedProductSourceQuestionV1(
            input_kind="multiview",
            question_id="product_multiview_source",
            prompt="Provide two to eight ordered Product Multiview images.",
            expected_guidance_revision=next_session_revision,
            min_asset_count=2,
            max_asset_count=8,
        )
        interaction = GuidedInteractionV1(
            interaction_id=interaction_id,
            workflow_id=workflow_id,
            session_id=str(session["session_id"]),
            checkpoint_id=checkpoint_id,
            kind="product_source",
            status="open",
            response_locale=str(session["response_locale"]),
            expected_session_revision=next_session_revision,
            revision=1,
            title="Product image source",
            context="Choose how to provide Product Multiview images.",
            content=question,
            allowed_actions=("select_source",),
            submit_path=(
                f"/api/v2/workflows/{workflow_id}/chat/interactions/{interaction_id}/submit"
            ),
            created_at=now,
            updated_at=now,
        )
        awaiting = GuidanceAwaitingV2(
            awaiting_id=f"awaiting_product_source_{identity}",
            workflow_id=interaction.workflow_id,
            session_id=interaction.session_id,
            checkpoint_id=checkpoint_id,
            kind="product_source",
            requires_user_action=True,
            resume_policy="submit_interaction",
            interaction_id=interaction_id,
            stage="product",
            stage_revision=journey.stage_revision,
            created_at=now,
        )
        connection.execute(
            insert(AgentCanvasGuidedInteractionRow).values(
                interaction_id=interaction.interaction_id,
                workflow_id=interaction.workflow_id,
                session_id=interaction.session_id,
                checkpoint_id=interaction.checkpoint_id,
                kind=interaction.kind,
                status=interaction.status,
                response_locale=interaction.response_locale,
                expected_session_revision=interaction.expected_session_revision,
                revision=interaction.revision,
                title=interaction.title,
                context=interaction.context,
                content_json=interaction.content.model_dump_json(),
                allowed_actions_json=json.dumps(interaction.allowed_actions),
                submit_path=interaction.submit_path,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
        )
        connection.execute(
            insert(AgentCanvasGuidanceAwaitingRow).values(
                awaiting_id=awaiting.awaiting_id,
                workflow_id=awaiting.workflow_id,
                session_id=awaiting.session_id,
                checkpoint_id=awaiting.checkpoint_id,
                kind=awaiting.kind,
                requires_user_action=awaiting.requires_user_action,
                resume_policy=awaiting.resume_policy,
                interaction_id=awaiting.interaction_id,
                node_ids_json="[]",
                stage=awaiting.stage,
                stage_revision=awaiting.stage_revision,
                created_at=now.isoformat(),
            )
        )
        return journey.model_copy(
            update={
                "stage_status": "waiting_user",
                "active_action": JourneyActionProjectionV2(
                    action_id=f"product-source:{interaction_id}",
                    action_kind="wait_for_user",
                    stage="product",
                    stage_revision=journey.stage_revision,
                    status="waiting_user",
                    occurrence_id=journey.active_occurrence_id,
                ),
            }
        )

    def lookup_replay(
        self,
        *,
        workflow_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> GuidedProductInputCommitResponseV1 | None:
        """Read one exact typed commit receipt before expensive compilation."""

        operation = f"guided_product_input:{workflow_id}"
        with self._workflows.database.engine.connect() as connection:
            replay = _load_idempotency(
                connection,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_digest,
            )
        if replay is None:
            return None
        return GuidedProductInputCommitResponseV1.model_validate_json(replay).model_copy(
            update={"replayed": True}
        )


def request_digest(
    workflow_id: str,
    request: GuidedProductInputCommitRequestV1,
    expected_workflow_revision: int,
) -> str:
    payload = {
        "contract": "guided-product-input-v1",
        "workflow_id": workflow_id,
        "workflow_revision": expected_workflow_revision,
        **request.model_dump(mode="json"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
