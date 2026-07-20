from __future__ import annotations


from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphNode,
)

from app.services.workflow_graph_common import WorkflowGraphError


def topological_node_ids(graph: WorkflowGraph) -> list[str]:
    node_ids = [node.id for node in graph.nodes]
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in graph.edges:
        if edge.source_node_id in indegree and edge.target_node_id in indegree:
            outgoing[edge.source_node_id].append(edge.target_node_id)
            indegree[edge.target_node_id] += 1
    ready = [node_id for node_id in node_ids if indegree[node_id] == 0]
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(ordered) != len(node_ids):
        raise WorkflowGraphError("workflow graph has cycle")
    return ordered


def selected_graph_node_ids(
    graph: WorkflowGraph,
    *,
    start_node_id: str | None,
    run_downstream: bool,
) -> list[str]:
    ordered = topological_node_ids(graph)
    if start_node_id is None:
        return ordered
    if start_node_id not in ordered:
        raise WorkflowGraphError(f"unsupported start_node_id: {start_node_id}")
    if not run_downstream:
        return [start_node_id]
    downstream = {start_node_id, *_downstream_node_ids(graph, start_node_id)}
    return [node_id for node_id in ordered if node_id in downstream]


def _refresh_depends_on(graph: WorkflowGraph) -> None:
    depends_on = _depends_on(graph.edges)
    for node in graph.nodes:
        node.depends_on = depends_on.get(node.id, [])


def _depends_on(edges: list[WorkflowGraphEdge]) -> dict[str, list[str]]:
    depends_on: dict[str, list[str]] = {}
    for edge in edges:
        depends_on.setdefault(edge.target_node_id, []).append(edge.source_node_id)
    return depends_on


def _downstream_node_ids(graph: WorkflowGraph, node_id: str) -> list[str]:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    seen: set[str] = set()
    queue = list(outgoing.get(node_id, []))
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        queue.extend(outgoing.get(current, []))
    return ordered


def _affected_downstream_node_ids(graph: WorkflowGraph, node_id: str) -> list[str]:
    return list(dict.fromkeys([node_id, *_downstream_node_ids(graph, node_id)]))


def _has_cycle(graph: WorkflowGraph) -> bool:
    try:
        topological_node_ids(graph)
    except WorkflowGraphError:
        return True
    return False


def _find_node(graph: WorkflowGraph, node_id: str) -> WorkflowGraphNode | None:
    return next((node for node in graph.nodes if node.id == node_id), None)


def _require_node(graph: WorkflowGraph, node_id: str) -> WorkflowGraphNode:
    node = _find_node(graph, node_id)
    if node is None:
        raise WorkflowGraphError(f"node not found: {node_id}")
    return node


def _require_edge(graph: WorkflowGraph, edge_id: str) -> WorkflowGraphEdge:
    edge = next((edge for edge in graph.edges if edge.id == edge_id), None)
    if edge is None:
        raise WorkflowGraphError(f"edge not found: {edge_id}")
    return edge
