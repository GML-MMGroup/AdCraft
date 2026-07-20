from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import WorkflowGraphNode
from app.services.workflow_graph import load_graph


@dataclass(frozen=True)
class ResolvedNodeIdentity:
    workflow_id: str
    node_id: str
    node_type: str
    graph_node: WorkflowGraphNode | None = None
    legacy_node_type_fallback: bool = False


class WorkflowNodeIdentityError(ValueError):
    def __init__(self, *, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail.get("message") or detail.get("code") or "node error"))


def resolve_node_identity(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str | None = None,
    node_type: str | None = None,
) -> ResolvedNodeIdentity:
    normalized_node_id = _clean(node_id)
    normalized_node_type = _clean(node_type)
    if not normalized_node_id and not normalized_node_type:
        raise WorkflowNodeIdentityError(
            status_code=422,
            detail={
                "code": "node_id_required",
                "message": "Provide node_id or node_type.",
                "workflow_id": workflow_id,
            },
        )

    graph = load_graph(data_dir, workflow_id) if workflow_id else None
    if graph is None:
        resolved_node_id = normalized_node_id or normalized_node_type or ""
        resolved_node_type = normalized_node_type or normalized_node_id or ""
        return ResolvedNodeIdentity(
            workflow_id=workflow_id,
            node_id=resolved_node_id,
            node_type=resolved_node_type,
            graph_node=None,
            legacy_node_type_fallback=not bool(normalized_node_id),
        )

    if normalized_node_id:
        graph_node = next((node for node in graph.nodes if node.id == normalized_node_id), None)
        if graph_node is None:
            raise WorkflowNodeIdentityError(
                status_code=404,
                detail={
                    "code": "workflow_node_not_found",
                    "message": f"Workflow node not found: {normalized_node_id}.",
                    "workflow_id": workflow_id,
                    "node_id": normalized_node_id,
                },
            )
        actual_node_type = graph_node.node_type
        if normalized_node_type and normalized_node_type != actual_node_type:
            raise WorkflowNodeIdentityError(
                status_code=422,
                detail={
                    "code": "node_type_mismatch",
                    "message": (
                        f"Workflow node {normalized_node_id} uses node_type "
                        f"{actual_node_type}, not {normalized_node_type}."
                    ),
                    "workflow_id": workflow_id,
                    "node_id": normalized_node_id,
                    "node_type": normalized_node_type,
                    "actual_node_type": actual_node_type,
                },
            )
        return ResolvedNodeIdentity(
            workflow_id=workflow_id,
            node_id=graph_node.id,
            node_type=actual_node_type,
            graph_node=graph_node,
            legacy_node_type_fallback=False,
        )

    matching_nodes = [node for node in graph.nodes if node.node_type == normalized_node_type]
    if len(matching_nodes) == 1:
        graph_node = matching_nodes[0]
        return ResolvedNodeIdentity(
            workflow_id=workflow_id,
            node_id=graph_node.id,
            node_type=graph_node.node_type,
            graph_node=graph_node,
            legacy_node_type_fallback=True,
        )
    if len(matching_nodes) > 1:
        matching_node_ids = [node.id for node in matching_nodes]
        raise WorkflowNodeIdentityError(
            status_code=422,
            detail={
                "code": "ambiguous_node_type",
                "message": (
                    f"Multiple workflow nodes use node_type {normalized_node_type}; "
                    "provide node_id."
                ),
                "workflow_id": workflow_id,
                "node_type": normalized_node_type,
                "matching_node_ids": matching_node_ids,
            },
        )
    raise WorkflowNodeIdentityError(
        status_code=404,
        detail={
            "code": "workflow_node_not_found",
            "message": f"Workflow node not found for node_type: {normalized_node_type}.",
            "workflow_id": workflow_id,
            "node_type": normalized_node_type,
        },
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
