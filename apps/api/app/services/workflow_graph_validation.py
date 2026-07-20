from __future__ import annotations


from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
    WorkflowGraphValidationIssue,
    WorkflowGraphValidationResponse,
)
from app.schemas.workflow_handles import (
    LEGACY_SOURCE_HANDLES,
    LEGACY_TARGET_HANDLES,
)

from app.services.workflow_graph_common import WorkflowGraphError
from app.services.workflow_graph_topology import _has_cycle


def validate_graph(graph: WorkflowGraph) -> WorkflowGraphValidationResponse:
    issues: list[WorkflowGraphValidationIssue] = []
    node_ids = {node.id for node in graph.nodes}
    nodes_by_id = {node.id: node for node in graph.nodes}
    issues.extend(_graph_edge_validation_issues(graph, node_ids, nodes_by_id))
    if _has_cycle(graph):
        issues.append(
            WorkflowGraphValidationIssue(level="error", message="workflow graph has cycle")
        )
    issues.extend(_graph_node_validation_issues(graph))
    return WorkflowGraphValidationResponse(
        workflow_id=graph.workflow_id,
        valid=not any(issue.level == "error" for issue in issues),
        issues=issues,
    )


def _graph_edge_validation_issues(
    graph: WorkflowGraph,
    node_ids: set[str],
    nodes_by_id: dict[str, WorkflowGraphNode],
) -> list[WorkflowGraphValidationIssue]:
    issues: list[WorkflowGraphValidationIssue] = []
    for edge in graph.edges:
        if edge.source_node_id not in node_ids:
            issues.append(
                WorkflowGraphValidationIssue(
                    level="error",
                    edge_id=edge.id,
                    message=f"source_node_id not found: {edge.source_node_id}",
                )
            )
        if edge.target_node_id not in node_ids:
            issues.append(
                WorkflowGraphValidationIssue(
                    level="error",
                    edge_id=edge.id,
                    message=f"target_node_id not found: {edge.target_node_id}",
                )
            )
        if edge.source_node_id in nodes_by_id:
            source_outputs = {
                handle.id for handle in nodes_by_id[edge.source_node_id].handles.outputs
            }
            if edge.source_handle not in source_outputs:
                issues.append(
                    WorkflowGraphValidationIssue(
                        level="error",
                        edge_id=edge.id,
                        message=(
                            f"source_handle not found on {edge.source_node_id}: "
                            f"{edge.source_handle}"
                        ),
                    )
                )
        if edge.target_node_id in nodes_by_id:
            target_inputs = {
                handle.id for handle in nodes_by_id[edge.target_node_id].handles.inputs
            }
            if edge.target_handle not in target_inputs:
                issues.append(
                    WorkflowGraphValidationIssue(
                        level="error",
                        edge_id=edge.id,
                        message=(
                            f"target_handle not found on {edge.target_node_id}: "
                            f"{edge.target_handle}"
                        ),
                    )
                )
        for item in edge.mapping:
            if not isinstance(item, dict) or "from" not in item or "to" not in item:
                issues.append(
                    WorkflowGraphValidationIssue(
                        level="error",
                        edge_id=edge.id,
                        message=f"edge mapping cannot be resolved: {edge.id}",
                    )
                )
    return issues


def _graph_node_validation_issues(
    graph: WorkflowGraph,
) -> list[WorkflowGraphValidationIssue]:
    issues: list[WorkflowGraphValidationIssue] = []
    for node in graph.nodes:
        if node.stale:
            issues.append(
                WorkflowGraphValidationIssue(
                    level="warning",
                    node_id=node.id,
                    message=node.stale_reason or "node is stale",
                )
            )
        if node.locked and node.stale_reason:
            issues.append(
                WorkflowGraphValidationIssue(
                    level="warning",
                    node_id=node.id,
                    message=node.stale_reason,
                )
            )
    return issues


def _reject_incompatible_requested_handles(
    source_node: WorkflowGraphNode,
    target_node: WorkflowGraphNode,
    source_handle: str | None,
    target_handle: str | None,
) -> None:
    if source_handle and source_handle not in LEGACY_SOURCE_HANDLES:
        source_outputs = {handle.id for handle in source_node.handles.outputs}
        if source_handle not in source_outputs:
            raise WorkflowGraphError(
                f"source_handle not found on {source_node.id}: {source_handle}"
            )
    if target_handle and target_handle not in LEGACY_TARGET_HANDLES:
        target_inputs = {handle.id for handle in target_node.handles.inputs}
        if target_handle not in target_inputs:
            raise WorkflowGraphError(
                f"target_handle not found on {target_node.id}: {target_handle}"
            )
