"""Resolve bounded document context from a frozen Workflow state capsule."""

from __future__ import annotations

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import ConversationQueryV1
from app.schemas.agent_operation_contexts import WorkflowStateCapsuleV1
from app.schemas.agent_working_documents import AgentDocumentContextExcerptV2
from app.services.agent_working_documents import AgentWorkingDocumentService


class ConversationQueryDocumentResolver:
    """Pin one explanation request to the capsule's current document identity."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        working_documents: AgentWorkingDocumentService,
    ) -> None:
        self._workflows = workflows
        self._working_documents = working_documents

    def resolve(
        self,
        capsule: WorkflowStateCapsuleV1,
        query: ConversationQueryV1,
    ) -> AgentDocumentContextExcerptV2:
        if query.query_kind != "document_explanation" or query.document_kind is None:
            raise _query_error(
                "agent_document_query_invalid",
                "Document context requires one typed document explanation query.",
            )
        if not self._workflows.exists(capsule.workflow_id):
            raise _query_error(
                "agent_document_not_found",
                "The Workflow for the requested document was not found.",
            )
        reference = next(
            (item for item in capsule.documents if item.document_kind == query.document_kind),
            None,
        )
        if reference is None:
            raise _query_error(
                "agent_document_not_found",
                "The requested current Workflow document was not found.",
            )
        selector = _selector(query)
        excerpt = self._working_documents.build_bounded_context(
            reference.document_id,
            selector,
        )
        if (
            excerpt.document_id != reference.document_id
            or excerpt.document_kind != reference.document_kind
            or excerpt.revision != reference.revision
            or excerpt.content_digest != reference.content_digest
        ):
            raise _query_error(
                "agent_document_revision_conflict",
                "The requested Workflow document changed before it could be explained.",
            )
        if len(excerpt.model_dump_json().encode("utf-8")) > 16_384:
            raise _query_error(
                "agent_document_context_too_large",
                "The requested Workflow document context exceeds the bounded limit.",
            )
        return excerpt


def _selector(query: ConversationQueryV1) -> str:
    if query.document_kind == "anchor_registry":
        if query.anchor_aliases:
            return f"anchors:{','.join(query.anchor_aliases)}"
        return "overview"
    if query.sequence_id is not None:
        return f"sequence:{query.sequence_id}"
    return "overview"


def _query_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="conversation_query_document_resolution",
    )
