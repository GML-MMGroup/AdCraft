"""Bounded read-only projection of current V2 Workflow authority."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from pydantic import ValidationError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_guidance_authority_repository import (
    GuidanceAdvanceAuthoritySnapshotRepository,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas_guidance import GuidanceAdvanceAuthoritySnapshotV1
from app.schemas.agent_operation_contexts import (
    WorkflowActionSummaryV1,
    WorkflowContextTruncationV1,
    WorkflowDocumentReferenceV1,
    WorkflowStateCapsuleV1,
    WorkflowWorkItemSummaryV1,
)
from app.schemas.language import BCP47Tag


_WORK_PRIORITY = {"failed": 0, "working": 1, "draft": 2, "ready": 3}


class AuthoritativeWorkflowContextProjector:
    """Compose existing persisted authorities without creating workflow state."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
    ) -> None:
        if workflows.database is not conversations.database:
            raise ValueError("Workflow context repositories must share one database.")
        database = workflows.database
        events = EventRepository(database)
        self._workflows = workflows
        self._conversations = conversations
        self._runtime = AgentCanvasRuntimeRepository(database, events)
        self._prompt_dispatch = AgentCanvasPromptPreparationDispatchRepository(database, events)
        self._documents = AgentWorkingDocumentRepository(database, events)
        self._guidance = GuidanceAdvanceAuthoritySnapshotRepository(
            AgentCanvasRequirementRepository(database)
        )

    def project(
        self,
        workflow_id: str,
        *,
        conversation_id: str,
        response_locale: BCP47Tag,
    ) -> WorkflowStateCapsuleV1:
        del conversation_id
        try:
            with self._workflows.database.engine.connect() as connection:
                snapshot = self._guidance.read_in_transaction(connection, workflow_id)
            workflow = self._workflows.get_workflow(workflow_id)
            members = {
                item.node_id: item
                for item in self._runtime.list_latest_members_for_workflow(workflow_id)
            }
            dispatches = {
                item.node_id: item
                for item in self._prompt_dispatch.list_for_workflow(workflow_id)
            }
            status_counts = Counter(node.status for node in workflow.nodes)
            work = [
                WorkflowWorkItemSummaryV1(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    title=node.title,
                    node_revision=node.revision,
                    node_status=node.status,
                    execution_id=(members[node.node_id].execution_id if node.node_id in members else None),
                    execution_state=(members[node.node_id].state if node.node_id in members else None),
                    prompt_preparation_state=(
                        dispatches[node.node_id].status
                        if node.node_id in dispatches
                        else node.prompt_preparation.status
                    ),
                    output_available=node.output_asset_id is not None,
                    failure_code=(node.error.code if node.error is not None else None),
                )
                for node in workflow.nodes
                if node.status != "ready"
            ]
            work.sort(key=lambda item: (_WORK_PRIORITY[item.node_status], item.node_id))
            current_action = self._current_action(snapshot)
            blockers = [
                WorkflowActionSummaryV1(
                    action_id=f"node-blocker:{node.node_id}:{node.revision}",
                    action_kind="node_failure",
                    stage=(snapshot.session.journey.stage if snapshot.session is not None else "workflow"),
                    stage_revision=(
                        snapshot.session.journey.stage_revision
                        if snapshot.session is not None
                        else workflow.revision
                    ),
                    status="failed",
                    objective=f"Resolve {node.title}.",
                    ownership_status="inconsistent",
                    leaf_error_code=(node.error.code if node.error is not None else "node_failed"),
                    blocker_class="unrecoverable",
                )
                for node in workflow.nodes
                if node.status == "failed"
            ]
            if current_action is not None and current_action.ownership_status in {
                "orphaned",
                "inconsistent",
            }:
                blockers.append(current_action)
            blockers.sort(key=_blocker_sort_key)
            documents = self._document_references(workflow_id)
            locale = snapshot.session.response_locale if snapshot.session is not None else response_locale
            return self._bounded_capsule(
                workflow_id=workflow_id,
                workflow_revision=workflow.revision,
                response_locale=locale,
                snapshot=snapshot,
                status_counts=status_counts,
                work=work,
                blockers=blockers,
                current_action=current_action,
                documents=documents,
            )
        except V2PersistenceError as error:
            if error.code == "agent_workflow_context_unavailable":
                raise
            raise _context_error(error.code) from error
        except (ValidationError, ValueError, TypeError) as error:
            raise _context_error("context_validation_failed") from error

    def _document_references(
        self,
        workflow_id: str,
    ) -> tuple[WorkflowDocumentReferenceV1, ...]:
        documents = self._documents.list(workflow_id, limit=100).items
        current: dict[str, WorkflowDocumentReferenceV1] = {}
        for document in documents:
            reference = WorkflowDocumentReferenceV1(
                document_id=document.document_id,
                document_kind=document.kind,
                revision=document.revision,
                content_digest=document.content_digest,
            )
            prior = current.get(document.kind)
            if prior is None or (reference.revision, reference.document_id) > (
                prior.revision,
                prior.document_id,
            ):
                current[document.kind] = reference
        return tuple(current[kind] for kind in sorted(current))

    @staticmethod
    def _current_action(snapshot) -> WorkflowActionSummaryV1 | None:
        session = snapshot.session
        if session is None or session.journey.active_action is None:
            return None
        action = session.journey.active_action
        base = {
            "action_id": action.action_id,
            "action_kind": action.action_kind,
            "stage": action.stage,
            "stage_revision": action.stage_revision,
            "status": action.status,
            "objective": f"Continue {action.stage}.",
            "turn_id": action.turn_id,
        }
        awaiting = session.awaiting
        if awaiting is not None:
            if awaiting.stage == action.stage and awaiting.stage_revision == action.stage_revision:
                return WorkflowActionSummaryV1(
                    **base,
                    ownership_status="awaiting",
                    owner_kind="typed_awaiting",
                    owner_id=awaiting.awaiting_id,
                    owner_state=awaiting.kind,
                    awaiting_id=awaiting.awaiting_id,
                    blocker_class="user_action_required",
                )
            return WorkflowActionSummaryV1(
                **base,
                ownership_status="inconsistent",
                error_code="guidance_orphaned_stall",
                leaf_error_code="guidance_orphaned_stall",
                blocker_class="unrecoverable",
            )
        if snapshot.guided_media_resume_owner is not None:
            owner = snapshot.guided_media_resume_owner
            return WorkflowActionSummaryV1(
                **base,
                ownership_status="owned",
                owner_kind="guided_media_resume",
                owner_id=owner.delivery_id,
                owner_state=owner.status,
                blocker_class="automatic_work_in_progress",
            )
        if snapshot.post_ready_owner is not None:
            owner_id = str(
                snapshot.post_ready_owner.get("effect_id")
                or snapshot.post_ready_owner.get("checkpoint_id")
                or snapshot.source_id
            )
            return WorkflowActionSummaryV1(
                **base,
                ownership_status="owned",
                owner_kind="post_ready_effect",
                owner_id=owner_id,
                owner_state=str(snapshot.post_ready_owner.get("status") or "working"),
                blocker_class="automatic_work_in_progress",
            )
        leaf = snapshot.execution_leaf
        if leaf is not None and (
            leaf.leaf_status in {"queued", "running"}
            or leaf.continuation_status in {"queued", "leased", "retry_wait"}
        ):
            return WorkflowActionSummaryV1(
                **base,
                ownership_status="owned",
                owner_kind="continuation",
                owner_id=leaf.continuation_id or leaf.leaf_turn_id,
                owner_state=leaf.continuation_status or leaf.leaf_status,
                turn_status=leaf.leaf_status,
                continuation_id=leaf.continuation_id,
                continuation_status=leaf.continuation_status,
                blocker_class="automatic_work_in_progress",
            )
        return WorkflowActionSummaryV1(
            **base,
            ownership_status="orphaned",
            turn_status=(leaf.leaf_status if leaf is not None else None),
            continuation_id=(leaf.continuation_id if leaf is not None else None),
            continuation_status=(leaf.continuation_status if leaf is not None else None),
            error_code="guidance_orphaned_stall",
            leaf_error_code=(
                leaf.error_code
                if leaf is not None and leaf.error_code is not None
                else "guidance_orphaned_stall"
            ),
            blocker_class="unrecoverable",
        )

    @staticmethod
    def _bounded_capsule(
        *,
        workflow_id,
        workflow_revision,
        response_locale,
        snapshot,
        status_counts,
        work,
        blockers,
        current_action,
        documents,
    ) -> WorkflowStateCapsuleV1:
        omitted_work = 0
        omitted_blockers = 0
        while True:
            payload = {
                "workflow_id": workflow_id,
                "workflow_revision": workflow_revision,
                "response_locale": response_locale,
                "guidance_session_id": (
                    snapshot.session.session_id if snapshot.session is not None else None
                ),
                "guidance_session_revision": (
                    snapshot.session.revision if snapshot.session is not None else None
                ),
                "journey_stage": (
                    snapshot.session.journey.stage if snapshot.session is not None else None
                ),
                "journey_status": (
                    snapshot.session.journey.stage_status if snapshot.session is not None else None
                ),
                "requirement_revision_id": (
                    snapshot.requirements.revision_id if snapshot.requirements is not None else None
                ),
                "requirement_revision_no": (
                    snapshot.requirements.revision_no if snapshot.requirements is not None else None
                ),
                "requirement_digest": (
                    snapshot.requirements.digest if snapshot.requirements is not None else None
                ),
                "node_status_counts": {
                    status: int(status_counts.get(status, 0))
                    for status in ("draft", "working", "ready", "failed")
                },
                "active_work": tuple(work),
                "blockers": tuple(blockers),
                "current_action": current_action,
                "awaiting_action": (
                    current_action
                    if current_action is not None
                    and current_action.ownership_status == "awaiting"
                    else None
                ),
                "next_valid_action": None,
                "documents": documents,
                "truncation": WorkflowContextTruncationV1(
                    omitted_active_work=omitted_work,
                    omitted_blockers=omitted_blockers,
                ),
            }
            digest_payload = _canonical_json(payload)
            payload["projection_digest"] = hashlib.sha256(digest_payload).hexdigest()
            if len(_canonical_json(payload)) <= 8_192:
                return WorkflowStateCapsuleV1.model_validate(payload)
            if work:
                work.pop()
                omitted_work += 1
                continue
            if len(blockers) > 1:
                blockers.pop()
                omitted_blockers += 1
                continue
            raise _context_error("context_budget_exceeded")


def _canonical_json(value: object) -> bytes:
    def default(item: object) -> object:
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        raise TypeError(f"Unsupported canonical value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=default,
    ).encode("utf-8")


def _blocker_sort_key(item: WorkflowActionSummaryV1) -> tuple[int, str]:
    priority = {
        "unrecoverable": 0,
        "user_action_required": 1,
        "automatic_work_in_progress": 2,
    }
    return priority.get(item.blocker_class or "", 99), item.action_id


def _context_error(reason: str) -> V2PersistenceError:
    return V2PersistenceError(
        "agent_workflow_context_unavailable",
        "Current Workflow context could not be assembled safely.",
        stage="authoritative_workflow_context",
        details={"reason": reason[:160]},
    )
