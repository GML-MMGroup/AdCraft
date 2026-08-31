"""SQLite authority for typed guided Character and Scene reference inputs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update

from app.persistence.agent_canvas_guided_interaction_repository import (
    _awaiting_for_workflow,
    _error,
    _journey,
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _advance_workflow_revision,
    _binding_values,
    _node_values,
    _require_workflow_revision,
)
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasChatTurnRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasNodeRow,
    AssetVersionRow,
)
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_conversation import ContinuationCommitV2
from app.schemas.agent_canvas_guided_interactions import (
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
    GuidedReferenceSourceQuestionV1,
    GuidedReferenceSourceSubmitV1,
)
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.v2_persistence import V2EventInsert


class AgentCanvasGuidedReferenceRepository:
    """Commit a reference source and its target binding in one authority transaction."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        events: EventRepository,
        interactions: AgentCanvasGuidedInteractionRepository,
        *,
        continuation_writer: Callable[..., None] | None = None,
    ) -> None:
        self._workflows = workflows
        self._events = events
        self._interactions = interactions
        self._continuation_writer = continuation_writer

    def set_continuation_writer(self, writer: Callable[..., None]) -> None:
        self._continuation_writer = writer

    def open_reference_source_with_journey(self, *args, **kwargs) -> GuidedInteractionV1:
        """Delegate opening to the canonical interaction transaction."""

        return self._interactions.open_reference_source_with_journey(*args, **kwargs)

    def submit(
        self,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedReferenceSourceSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
        asset_sha256: str | None = None,
    ) -> GuidedInteractionAcceptedV1:
        """Apply use/skip without entering an LLM or media execution path."""

        if not isinstance(interaction.content, GuidedReferenceSourceQuestionV1):
            raise _error(
                "guided_interaction_action_not_allowed", "This is not a reference question."
            )
        content = interaction.content
        if request.reference_kind != content.reference_kind:
            raise _error("guided_reference_source_kind_invalid", "Reference kind is stale.")
        request_json = request.model_dump_json()
        request_digest = hashlib.sha256(request_json.encode()).hexdigest()
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
                    if str(existing["request_digest"]) != request_digest:
                        raise _error(
                            "guided_interaction_submission_conflict",
                            "Submission identity was reused with different content.",
                        )
                    connection.rollback()
                    return GuidedInteractionAcceptedV1.model_validate_json(
                        str(existing["result_json"])
                    ).model_copy(update={"replayed": True})

                current = (
                    connection.execute(
                        select(AgentCanvasGuidedInteractionRow).where(
                            AgentCanvasGuidedInteractionRow.interaction_id
                            == interaction.interaction_id,
                            AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
                            AgentCanvasGuidedInteractionRow.status == "open",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                awaiting = _awaiting_for_workflow(connection, workflow_id)
                if (
                    current is None
                    or awaiting is None
                    or awaiting.interaction_id != interaction.interaction_id
                ):
                    raise _error(
                        "guided_interaction_not_found",
                        "Reference source interaction is not the current wait.",
                    )
                if int(current["revision"]) != request.expected_interaction_revision:
                    raise _error(
                        "guided_interaction_stale", "Reference interaction revision is stale."
                    )
                if int(current["expected_session_revision"]) != request.expected_session_revision:
                    raise _error("guided_interaction_stale", "Reference session revision is stale.")
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
                journey = _journey(session)
                current_revision = _require_workflow_revision(
                    connection, workflow_id, self._workflows.get_workflow(workflow_id).revision
                )
                created_node_ids: tuple[str, ...] = ()
                created_binding_ids: tuple[str, ...] = ()
                node = None
                binding = None
                if request.action == "use_reference":
                    if request.asset_id is None or request.asset_version_id is None:
                        raise _error(
                            "guided_reference_source_asset_required",
                            "A reference AssetVersion is required.",
                        )
                    version = (
                        connection.execute(
                            select(AssetVersionRow).where(
                                AssetVersionRow.asset_id == request.asset_id,
                                AssetVersionRow.version_id == request.asset_version_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if version is None:
                        raise _error(
                            "guided_reference_source_asset_not_found",
                            "Reference AssetVersion was not found.",
                        )
                    if str(version["source_workflow_id"]) != workflow_id:
                        raise _error(
                            "guided_reference_source_asset_foreign_workflow",
                            "Reference AssetVersion is outside this Workflow.",
                        )
                    if str(version["status"]) != "ready":
                        raise _error(
                            "guided_reference_source_asset_unreadable",
                            "Reference AssetVersion is not readable.",
                        )
                    if not str(version["mime_type"]).startswith("image/"):
                        raise _error(
                            "guided_reference_source_asset_not_image",
                            "Reference AssetVersion must be an image.",
                        )
                    identity = hashlib.sha256(
                        f"guided-reference:{workflow_id}:{content.target_node_id}:{content.target_node_revision}:"
                        f"{content.reference_kind}:{content.occurrence_id or '-'}:{request.asset_version_id}".encode()
                    ).hexdigest()[:32]
                    node_id = f"node_guided_reference_{identity}"
                    binding_id = f"binding_guided_reference_{identity}"
                    node = CanvasNodeV2(
                        node_id=node_id,
                        workflow_id=workflow_id,
                        node_type="image",
                        creative_role="general_image",
                        title=(
                            "Character reference source"
                            if content.reference_kind == "character_main"
                            else "Scene reference source"
                        ),
                        status="ready",
                        execution_mode="source_only",
                        summary_prompt=None,
                        generation_prompt="",
                        structured_content={},
                        model_selection_mode="default",
                        model_ref=None,
                        parameters={},
                        metadata={
                            "source_type": "upload",
                            "operation_id": submission_id,
                            "rendition_kind": "original",
                            "reference_source": True,
                            "reference_kind": content.reference_kind,
                            "target_node_id": content.target_node_id,
                            "target_node_revision": content.target_node_revision,
                            "occurrence_id": content.occurrence_id,
                            "asset_id": request.asset_id,
                            "asset_version_id": request.asset_version_id,
                            "asset_sha256": asset_sha256 or str(version["sha256"]),
                        },
                        output_asset_id=request.asset_id,
                        position=CanvasPositionV2(x=0, y=0),
                        revision=1,
                        error=None,
                        prompt_preparation=NodePromptPreparationV1.source_only(
                            updated_at=datetime.now(timezone.utc)
                        ),
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    binding = CanvasBindingV2(
                        binding_id=binding_id,
                        workflow_id=workflow_id,
                        source=CanvasBindingSourceNodeV2(source_node_id=node_id),
                        target_node_id=content.target_node_id,
                        input_role="image_reference",
                        required=True,
                        enabled=True,
                        order=0,
                        label="Guided reference",
                        metadata={
                            "operation_id": submission_id,
                            "rendition_kind": "original",
                            "semantic_reference_role": (
                                "character_reference"
                                if content.reference_kind == "character_main"
                                else "scene_reference"
                            ),
                            "reference_purpose": (
                                "identity_guidance"
                                if content.reference_kind == "character_main"
                                else "environment_guidance"
                            ),
                            "occurrence_id": content.occurrence_id,
                            "source_node_revision": 1,
                            "source_asset_id": request.asset_id,
                            "source_asset_version_id": request.asset_version_id,
                        },
                        created_at=node.created_at,
                        updated_at=node.updated_at,
                    )
                    connection.execute(insert(AgentCanvasNodeRow).values(**_node_values(node)))
                    connection.execute(
                        insert(AgentCanvasBindingRow).values(**_binding_values(binding))
                    )
                    created_node_ids = (node_id,)
                    created_binding_ids = (binding_id,)

                _advance_workflow_revision(
                    connection,
                    workflow_id=workflow_id,
                    current_revision=current_revision,
                    updated_at=now,
                )

                next_journey = journey.model_copy(
                    update={"stage_status": "working", "active_action": None}
                )
                connection.execute(
                    update(AgentCanvasGuidedInteractionRow)
                    .where(
                        AgentCanvasGuidedInteractionRow.interaction_id == interaction.interaction_id
                    )
                    .values(status="closed", revision=interaction.revision + 1, updated_at=now)
                )
                connection.execute(
                    delete(AgentCanvasGuidanceAwaitingRow).where(
                        AgentCanvasGuidanceAwaitingRow.awaiting_id == awaiting.awaiting_id
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
                        revision=request.expected_session_revision + 1,
                        updated_at=now,
                    )
                )
                if updated_session.rowcount != 1:
                    raise _error(
                        "guided_reference_source_revision_conflict",
                        "Guidance session changed before reference submit.",
                    )
                source_turn = (
                    connection.execute(
                        select(AgentCanvasChatTurnRow)
                        .where(
                            AgentCanvasChatTurnRow.workflow_id == workflow_id,
                            AgentCanvasChatTurnRow.status.in_(("queued", "running", "completed")),
                        )
                        .order_by(AgentCanvasChatTurnRow.created_at.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                continuation_id = None
                if self._continuation_writer is not None and source_turn is not None:
                    continuation_digest = hashlib.sha256(
                        f"guided-reference:{workflow_id}:{submission_id}".encode()
                    ).hexdigest()
                    continuation_id = f"continuation_{continuation_digest[:24]}"
                    self._continuation_writer(
                        connection,
                        workflow_id=workflow_id,
                        conversation_id=str(source_turn["conversation_id"]),
                        continuation=ContinuationCommitV2(
                            continuation_id=continuation_id,
                            continuation_turn_id=f"turn_{continuation_digest[24:56]}",
                            source_turn_id=str(source_turn["turn_id"]),
                            source_action_id=interaction.interaction_id,
                            idempotency_key=f"guided-reference:{workflow_id}:{submission_id}",
                        ),
                        now=now,
                    )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type=(
                            "guided_reference_source_used"
                            if request.action == "use_reference"
                            else "guided_reference_source_skipped"
                        ),
                        transition_key=f"guided-reference:{submission_id}:applied",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={
                            "reference_kind": content.reference_kind,
                            "target_node_id": content.target_node_id,
                            "target_node_revision": content.target_node_revision,
                            "occurrence_id": content.occurrence_id,
                            "asset_id": request.asset_id,
                            "asset_version_id": request.asset_version_id,
                            "asset_sha256": (
                                asset_sha256 or str(version["sha256"])
                                if request.action == "use_reference"
                                else None
                            ),
                            "operation_id": submission_id,
                            "rendition_kind": "original"
                            if request.action == "use_reference"
                            else None,
                            "created_node_ids": list(created_node_ids),
                            "created_binding_ids": list(created_binding_ids),
                        },
                    ),
                )
                final_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        event_type="guidance_awaiting_resumed",
                        transition_key=f"guided-reference:{submission_id}:resumed",
                        action_id=interaction.interaction_id,
                        created_at=now,
                        payload={"resume_evidence": "guided_reference_source"},
                    ),
                )
                accepted = GuidedInteractionAcceptedV1(
                    workflow_id=workflow_id,
                    interaction_id=interaction.interaction_id,
                    submission_id=submission_id,
                    receipt_id=f"receipt_{submission_id}",
                    created_node_ids=created_node_ids,
                    created_binding_ids=created_binding_ids,
                    continuation_id=continuation_id,
                    resulting_session_revision=request.expected_session_revision + 1,
                    events_cursor=final_event.seq,
                )
                connection.execute(
                    insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                        submission_id=submission_id,
                        workflow_id=workflow_id,
                        interaction_id=interaction.interaction_id,
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
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
