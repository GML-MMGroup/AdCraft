"""Frozen Storyboard context lookup and fenced repair of malformed fan-out intents."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update

from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
    normalize_queued_node,
)
from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _advance_workflow_revision,
    _node_from_row,
    _node_values,
    _require_workflow_revision,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasMaterializationCommitRow,
    AgentCanvasNodeRow,
    AgentCanvasPromptPreparationOutboxRow,
    AgentWorkingDocumentRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_materialization_commit import MaterializationOutcomeV1
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_prompt_preparation_dispatch import (
    PromptPreparationDispatchV1,
    detached_context_payload,
)
from app.schemas.agent_canvas_role_prompt_preparation import is_user_edited_prompt
from app.schemas.v2_persistence import V2EventInsert


# Failures caused by an incomplete frozen context, not by the prompt itself.
_RECOVERABLE_ERROR_CODES = frozenset(
    {"prompt_preparation_context_missing", "identity_safety_decision_required"}
)


class StoryboardPromptContextRepository:
    """Keep historical managed context separate from the user's current prompt."""

    def __init__(self, workflows: AgentCanvasWorkflowRepository, events: EventRepository) -> None:
        self._workflows = workflows
        self._events = events
        self._dispatches = AgentCanvasPromptPreparationDispatchRepository(
            workflows.database, events
        )

    def resolve(self, source: CanvasNodeV2, *, plan_document_id: str) -> StageAuthoringContextV1:
        dispatch = None
        operation_id = source.prompt_preparation.operation_id
        if operation_id:
            dispatch = self._dispatches.get_by_node_operation(
                source.workflow_id, source.node_id, operation_id
            )
        elif source.prompt_preparation.status == "ready" and is_user_edited_prompt(
            source.prompt_presentation
        ):
            with self._workflows.database.engine.connect() as connection:
                outcomes = connection.execute(
                    select(AgentCanvasMaterializationCommitRow.outcome_json)
                    .where(AgentCanvasMaterializationCommitRow.workflow_id == source.workflow_id)
                    .order_by(AgentCanvasMaterializationCommitRow.created_at.desc())
                ).scalars()
                for payload in outcomes:
                    outcome = MaterializationOutcomeV1.model_validate_json(payload)
                    if source.node_id not in outcome.node_ids or not any(
                        item.document_id == plan_document_id for item in outcome.document_results
                    ):
                        continue
                    operation_id = outcome.prompt_preparation_ids[
                        outcome.node_ids.index(source.node_id)
                    ]
                    dispatch = self._dispatches.get_for_node_operation_in_transaction(
                        connection, source.workflow_id, source.node_id, operation_id
                    )
                    break
                if dispatch is None:
                    # PATCH supersedes even completed managed dispatches. Preserve
                    # their completion evidence when selecting the latest fallback.
                    completed_at = (
                        select(func.max(WorkflowEventRow.created_at))
                        .where(
                            WorkflowEventRow.workflow_id == source.workflow_id,
                            WorkflowEventRow.node_id == source.node_id,
                            WorkflowEventRow.event_type
                            == "node_prompt_preparation_dispatch_reconciled",
                            func.json_extract(WorkflowEventRow.payload_json, "$.status")
                            == "completed",
                            func.json_extract(WorkflowEventRow.payload_json, "$.dispatch_id")
                            == AgentCanvasPromptPreparationOutboxRow.dispatch_id,
                        )
                        .scalar_subquery()
                    )
                    operation_id = connection.execute(
                        select(AgentCanvasPromptPreparationOutboxRow.operation_id)
                        .where(
                            AgentCanvasPromptPreparationOutboxRow.workflow_id == source.workflow_id,
                            AgentCanvasPromptPreparationOutboxRow.node_id == source.node_id,
                            or_(
                                AgentCanvasPromptPreparationOutboxRow.status == "completed",
                                and_(
                                    AgentCanvasPromptPreparationOutboxRow.status == "superseded",
                                    completed_at.is_not(None),
                                ),
                            ),
                        )
                        .order_by(
                            func.coalesce(
                                completed_at, AgentCanvasPromptPreparationOutboxRow.terminal_at
                            ).desc(),
                            AgentCanvasPromptPreparationOutboxRow.dispatch_id.desc(),
                        )
                        .limit(1)
                    ).scalar_one_or_none()
                    if operation_id:
                        dispatch = self._dispatches.get_for_node_operation_in_transaction(
                            connection, source.workflow_id, source.node_id, operation_id
                        )
        if dispatch is None or not dispatch.context_json:
            raise V2PersistenceError(
                "storyboard_prompt_context_missing",
                "Progressive Storyboard Draft has no frozen prompt context.",
                stage="storyboard_progression",
            )
        try:
            context = StageAuthoringContextV1.model_validate(dispatch.context_json)
            _, digest = detached_context_payload(context)
        except ValueError as error:
            raise V2PersistenceError(
                "storyboard_prompt_context_invalid",
                "Frozen Storyboard context is invalid.",
                stage="storyboard_progression",
            ) from error
        if context.workflow_id != source.workflow_id or digest != dispatch.context_digest:
            raise V2PersistenceError(
                "storyboard_prompt_context_invalid",
                "Frozen Storyboard context proof is stale.",
                stage="storyboard_progression",
            )
        return context

    def redispatch(
        self,
        *,
        node: CanvasNodeV2,
        source: CanvasNodeV2,
        bindings: tuple[CanvasBindingV2, ...],
        context: StageAuthoringContextV1,
        plan_document_id: str,
        expected_plan_revision: int,
        expected_workflow_revision: int,
        dispatch_id: str,
        expected_lease_generation: int,
    ) -> PromptPreparationDispatchV1:
        """Replace only an inspected Agent Draft intent that failed on its frozen context."""

        now = datetime.now(timezone.utc)
        payload, digest = detached_context_payload(context)
        if context.workflow_id != node.workflow_id:
            raise _conflict()
        with self._workflows.database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                _require_workflow_revision(connection, node.workflow_id, expected_workflow_revision)
                self._workflows.require_node_revision_in_transaction(
                    connection,
                    workflow_id=source.workflow_id,
                    node_id=source.node_id,
                    expected_revision=source.revision,
                    expected_output_asset_id=source.output_asset_id,
                )
                plan_revision = connection.execute(
                    select(AgentWorkingDocumentRow.revision).where(
                        AgentWorkingDocumentRow.workflow_id == node.workflow_id,
                        AgentWorkingDocumentRow.document_id == plan_document_id,
                    )
                ).scalar_one_or_none()
                row = (
                    connection.execute(
                        select(AgentCanvasNodeRow).where(
                            AgentCanvasNodeRow.workflow_id == node.workflow_id,
                            AgentCanvasNodeRow.node_id == node.node_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    row is None
                    or _node_from_row(row) != node
                    or plan_revision != expected_plan_revision
                ):
                    raise _conflict()
                failed = self._dispatches.get_for_node_operation_in_transaction(
                    connection, node.workflow_id, node.node_id, node.prompt_preparation.operation_id
                )
                if (
                    failed is None
                    or failed.dispatch_id != dispatch_id
                    or failed.status != "failed"
                    or failed.lease_generation != expected_lease_generation
                    or failed.last_error_code not in _RECOVERABLE_ERROR_CODES
                    or (
                        failed.last_error_code == "prompt_preparation_context_missing"
                        and failed.context_json
                    )
                    or failed.lease_owner is not None
                    or node.status != "draft"
                    or node.execution_mode != "generative"
                    or node.metadata.get("authoring_origin") == "user"
                    or node.metadata.get("source_agent_document_id") != plan_document_id
                    or node.prompt_preparation.status != "failed"
                    or node.prompt_preparation.error is None
                    or node.prompt_preparation.error.code != failed.last_error_code
                    or node.generation_prompt
                    or is_user_edited_prompt(node.prompt_presentation)
                ):
                    raise _conflict()
                successor_node = normalize_queued_node(
                    node.model_copy(
                        update={
                            "revision": node.revision + 1,
                            "updated_at": now,
                            "prompt_preparation": NodePromptPreparationV1(
                                status="queued", attempt_no=0, updated_at=now
                            ),
                        }
                    ),
                    bindings=bindings,
                    context_digest=digest,
                )
                values = _node_values(successor_node)
                values.pop("node_id")
                values.pop("workflow_id")
                connection.execute(
                    update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == node.workflow_id,
                        AgentCanvasNodeRow.node_id == node.node_id,
                        AgentCanvasNodeRow.revision == node.revision,
                    )
                    .values(**values)
                )
                successor = self._dispatches.supersede_and_enqueue_in_transaction(
                    connection,
                    node=successor_node,
                    bindings=bindings,
                    context=payload,
                    reason="storyboard_missing_prompt_context_recovery",
                    now=now,
                )
                assert successor is not None
                _advance_workflow_revision(
                    connection,
                    workflow_id=node.workflow_id,
                    current_revision=expected_workflow_revision,
                    updated_at=now.isoformat(),
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=node.workflow_id,
                        node_id=node.node_id,
                        event_type="storyboard_prompt_context_recovered",
                        created_at=now.isoformat(),
                        transition_key=f"storyboard-context-recovery:{dispatch_id}",
                        payload={
                            "superseded_dispatch_id": dispatch_id,
                            "dispatch_id": successor.dispatch_id,
                            "node_revision": successor_node.revision,
                            "plan_document_id": plan_document_id,
                            "plan_revision": expected_plan_revision,
                            "source_node_id": source.node_id,
                            "source_revision": source.revision,
                        },
                    ),
                )
                connection.commit()
                return successor
            except BaseException:
                connection.rollback()
                raise


def _conflict() -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_prompt_context_recovery_conflict",
        "Failed Storyboard prompt context recovery authority changed.",
        stage="storyboard_progression",
    )
