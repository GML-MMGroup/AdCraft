"""Ready-media variation authoring for Agent Canvas."""

from __future__ import annotations

from collections.abc import Callable

from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas import (
    CanvasNodeErrorV2,
    CanvasNodeV2,
    CanvasVariationDraftResponseV2,
    CanvasVariationDraftUpsertV2,
    CanvasVariationMaterializeRequestV2,
    CanvasVariationMaterializeResponseV2,
)
from app.schemas.agent_canvas_runtime import CanvasRunAcceptedV2


VariationValidator = Callable[[CanvasNodeV2, CanvasVariationDraftUpsertV2], None]
VariationRunNode = Callable[[str, str, str], CanvasRunAcceptedV2]


class AgentCanvasVariationService:
    """Persist and materialize one canonical variation per Ready media node."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        commands: AgentCanvasCommandRepository,
        *,
        variation_validator: VariationValidator | None = None,
        run_node: VariationRunNode | None = None,
    ) -> None:
        if workflows.database is not commands.database:
            raise ValueError("Variation repositories must share one database.")
        self._workflows = workflows
        self._commands = commands
        self._variation_validator = variation_validator
        self._run_node = run_node

    def save(
        self,
        workflow_id: str,
        source_node_id: str,
        request: CanvasVariationDraftUpsertV2,
        *,
        expected_revision: int,
    ) -> CanvasVariationDraftResponseV2:
        source = self._workflows.get_node(workflow_id, source_node_id)
        request = request.model_copy(
            update=(
                {
                    "model_selection_mode": source.model_selection_mode,
                    "model_ref": source.model_ref,
                }
                if request.model_selection_mode == "default" and request.model_ref is None
                else {}
            ),
            deep=True,
        )
        if self._variation_validator is not None:
            self._variation_validator(source, request)
        return self._commands.upsert_variation_draft(
            workflow_id,
            source_node_id,
            request,
            expected_revision=expected_revision,
        )

    def discard(
        self,
        workflow_id: str,
        source_node_id: str,
        *,
        expected_revision: int,
    ) -> None:
        self._commands.discard_variation_draft(
            workflow_id,
            source_node_id,
            expected_revision=expected_revision,
        )

    def materialize(
        self,
        workflow_id: str,
        source_node_id: str,
        request: CanvasVariationMaterializeRequestV2,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CanvasVariationMaterializeResponseV2:
        response, created = self._commands.materialize_variation_draft(
            workflow_id,
            source_node_id,
            request,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        if not created or request.action != "generate" or self._run_node is None:
            return response
        try:
            run = self._run_node(
                workflow_id,
                response.sibling_node.node_id,
                f"variation:{idempotency_key}",
            )
            response = response.model_copy(
                update={"run": run.model_dump(mode="json")},
                deep=True,
            )
        except Exception as error:
            response = response.model_copy(
                update={
                    "run_error": CanvasNodeErrorV2(
                        code=str(getattr(error, "code", "run_queue_failed")),
                        message="The variation was saved but its run could not be queued.",
                        retryable=True,
                    )
                },
                deep=True,
            )
        self._commands.update_variation_materialization_response(
            idempotency_key=idempotency_key,
            response=response,
        )
        return response
