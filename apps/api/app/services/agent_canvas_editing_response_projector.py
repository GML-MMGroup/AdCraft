"""Read-only canonical projections for Editing nodes in V2 responses."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, CanvasNodeV2
from app.schemas.agent_canvas_editing import EditingNodeContentV2
from app.services.agent_canvas_editing import EditingNodeService


class EditingResponseProjector:
    """Project Editing response content without changing authoring state."""

    def __init__(self, editing_nodes: EditingNodeService) -> None:
        self._editing_nodes = editing_nodes

    def project_node(self, node: CanvasNodeV2) -> CanvasNodeV2:
        """Return one node with canonical content when it is an Editing node."""

        if node.node_type != "editing":
            return node
        try:
            content = self._editing_nodes.content(node.workflow_id, node.node_id)
        except (V2PersistenceError, TypeError, ValueError) as error:
            raise _projection_error(node, error) from error
        return self._project_node(node, content)

    def project_workflow(self, workflow: AgentCanvasWorkflowV2) -> AgentCanvasWorkflowV2:
        """Return a workflow with every Editing node canonically projected."""

        return workflow.model_copy(
            update={"nodes": tuple(self.project_node(node) for node in workflow.nodes)}
        )

    def validate_workflow(self, workflow: AgentCanvasWorkflowV2) -> None:
        """Validate a candidate response projection without persisting it."""

        for node in workflow.nodes:
            if node.node_type == "editing":
                try:
                    content = self._editing_nodes.content_from_snapshot(workflow, node.node_id)
                except (V2PersistenceError, TypeError, ValueError) as error:
                    raise _projection_error(node, error) from error
                self._project_node(node, content)

    def _project_node(
        self,
        node: CanvasNodeV2,
        content: EditingNodeContentV2,
    ) -> CanvasNodeV2:
        try:
            projected = node.model_copy(
                update={"structured_content": content.model_dump(mode="json")}
            )
            return CanvasNodeV2.model_validate(projected.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError) as error:
            raise _projection_error(node, error) from error


def _projection_error(node: CanvasNodeV2, error: BaseException) -> V2PersistenceError:
    reason_code = getattr(error, "code", None) or type(error).__name__
    return V2PersistenceError(
        "editing_manifest_projection_invalid",
        "Canonical Editing response projection is invalid.",
        stage="agent_canvas_editing_response_projector",
        details={"workflow_id": node.workflow_id, "node_id": node.node_id, "reason_code": reason_code},
    )
