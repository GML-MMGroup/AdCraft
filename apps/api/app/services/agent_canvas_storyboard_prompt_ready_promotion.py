"""Service boundary for Storyboard prompt-ready promotion."""

from __future__ import annotations

from app.persistence.agent_canvas_execution_settings_repository import (
    AgentCanvasExecutionSettingsRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_storyboard_prompt_ready_promotion_repository import (
    StoryboardPromptReadyPromotionRepository,
)
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_materialization_commit import MaterializationOutcomeV1
from app.schemas.agent_canvas_storyboard_prompt_ready_promotion import (
    StoryboardPromptPreparationPairV1,
    StoryboardPromptReadyPromotionCommandV1,
    StoryboardPromptReadyPromotionResultV1,
)


class StoryboardPromptReadyPromotionService:
    """Build and execute one strict promotion from persisted authority."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        repository: StoryboardPromptReadyPromotionRepository,
        documents: AgentWorkingDocumentRepository,
        settings: AgentCanvasExecutionSettingsRepository,
    ) -> None:
        database = workflows.database
        if any(candidate.database is not database for candidate in (documents, settings)):
            raise ValueError("Storyboard promotion dependencies must share one database.")
        self._workflows = workflows
        self._conversations = conversations
        self._repository = repository
        self._documents = documents
        self._settings = settings

    def promote(
        self,
        outcome: MaterializationOutcomeV1,
        *,
        action_turn_id: str,
        session_id: str,
    ) -> StoryboardPromptReadyPromotionResultV1 | None:
        workflow = self._workflows.get_workflow(outcome.workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        materialized_nodes = tuple(nodes.get(node_id) for node_id in outcome.node_ids)
        if (
            outcome.journey_stage != "storyboard_grids"
            or not materialized_nodes
            or any(
                node is None
                or node.node_type != "image"
                or node.creative_role != "storyboard_sequence"
                for node in materialized_nodes
            )
        ):
            return None
        documents = tuple(
            (
                result,
                self._documents.get(result.document_id),
            )
            for result in outcome.document_results
        )
        production_plans = tuple(
            (result, document)
            for result, document in documents
            if document is not None and document.kind == "storyboard_production_plan"
        )
        if not production_plans:
            return None
        if len(production_plans) != 1:
            raise _invalid("production_plan_count")
        if len(outcome.node_ids) != len(outcome.prompt_preparation_ids):
            raise _invalid("preparation_count")
        pairs: list[StoryboardPromptPreparationPairV1] = []
        for node_id, operation_id in zip(
            outcome.node_ids,
            outcome.prompt_preparation_ids,
            strict=True,
        ):
            node = nodes.get(node_id)
            if node is None:
                raise _invalid("node_lineage")
            pairs.append(
                StoryboardPromptPreparationPairV1(
                    node_id=node_id,
                    operation_id=operation_id,
                    expected_node_revision=node.revision,
                )
            )
        pairs.sort(key=lambda item: (item.node_id, item.operation_id))
        setting = self._settings.get(outcome.workflow_id)
        result, document = production_plans[0]
        assert document is not None
        command = StoryboardPromptReadyPromotionCommandV1(
            workflow_id=outcome.workflow_id,
            session_id=session_id,
            materialization_id=outcome.materialization_id,
            action_turn_id=action_turn_id,
            expected_workflow_revision=workflow.revision,
            expected_session_revision=(self._session_revision(outcome.workflow_id, session_id)),
            expected_stage_revision=self._stage_revision(outcome.workflow_id, session_id),
            preparations=tuple(pairs),
            production_plan_document_id=document.document_id,
            production_plan_revision=result.after_revision,
            execution_mode=(setting.media_execution_mode if setting is not None else "manual"),
        )
        return self._repository.promote(command)

    def _session_revision(self, workflow_id: str, session_id: str) -> int:
        session = self._session(workflow_id, session_id)
        return session.revision

    def _stage_revision(self, workflow_id: str, session_id: str) -> int:
        session = self._session(workflow_id, session_id)
        return session.journey.stage_revision

    def _session(self, workflow_id: str, session_id: str):
        session = self._conversations.get_guidance_session(workflow_id)
        if session.session_id != session_id:
            raise _invalid("guidance_session")
        return session


def _invalid(invariant: str) -> V2PersistenceError:
    return V2PersistenceError(
        "storyboard_prompt_ready_authority_invalid",
        "Storyboard prompt-ready authority is invalid.",
        stage="storyboard_prompt_ready_promotion",
        details={"invariant": invariant},
    )
