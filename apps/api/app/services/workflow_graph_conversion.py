from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.ad_workflow import AdWorkflowResponse
from app.schemas.workflow_graph import (
    CanvasPosition,
    WorkflowGraph,
    WorkflowGraphEdge,
    WorkflowGraphNode,
)
from app.services.agent_trace import utc_now

from app.services.workflow_graph_common import DEFAULT_POSITIONS, NODE_CATEGORY_BY_TYPE
from app.services.workflow_graph_preservation import (
    _default_mapping,
    _edge_id,
    _hash_payload,
)
from app.services.workflow_graph_store import _append_node_version, save_graph
from app.services.workflow_graph_topology import _depends_on


def save_graph_for_plan(
    *,
    workflow: AdWorkflowResponse,
    ad_request: dict[str, Any],
    audio_mode: str,
    data_dir: Path,
) -> WorkflowGraph:
    graph = workflow_response_to_graph(workflow, ad_request=ad_request, audio_mode=audio_mode)
    save_graph(data_dir, graph)
    for node in graph.nodes:
        _append_node_version(data_dir, graph.workflow_id, node, reason="initial plan")
    return graph


def workflow_response_to_graph(
    workflow: AdWorkflowResponse,
    *,
    ad_request: dict[str, Any],
    audio_mode: str,
) -> WorkflowGraph:
    now = utc_now().isoformat()
    edges = [
        WorkflowGraphEdge(
            id=_edge_id(edge.source, edge.target),
            workflow_id=workflow.workflow_id,
            source_node_id=edge.source,
            target_node_id=edge.target,
            label=edge.label,
            source_handle=edge.source_handle,
            target_handle=edge.target_handle,
            mapping=_default_mapping(edge.label),
            required=True,
        )
        for edge in workflow.edges
    ]
    depends_on = _depends_on(edges)
    nodes = [
        WorkflowGraphNode(
            id=node.id,
            workflow_id=workflow.workflow_id,
            node_type=node.id,
            category=NODE_CATEGORY_BY_TYPE.get(node.id, "utility"),
            title=node.title,
            description=node.description,
            position=DEFAULT_POSITIONS.get(node.id, CanvasPosition()),
            config={
                "duration_seconds": node.metadata.get("duration_seconds"),
                "aspect_ratio": node.metadata.get("aspect_ratio"),
                "output_resolution": node.metadata.get("output_resolution"),
                "audio_mode": node.metadata.get("audio_mode"),
            },
            prompt=node.prompt,
            override_prompt=node.override_prompt,
            input_context=node.input_context,
            output=node.output or node.content,
            metadata=node.metadata,
            input_assets=node.input_assets,
            output_assets=node.output_assets,
            status=node.status,
            version=1,
            input_hash=_hash_payload(node.input_context) if node.input_context else None,
            output_hash=_hash_payload(node.output or node.content)
            if (node.output or node.content)
            else None,
            locked=False,
            stale=False,
            stale_reason=None,
            depends_on=depends_on.get(node.id, []),
            can_run_standalone=node.can_run_standalone,
            supports_override_prompt=node.supports_override_prompt,
        )
        for node in workflow.nodes
    ]
    name = f"{ad_request.get('product_name', 'Ad')} Workflow"
    return WorkflowGraph(
        workflow_id=workflow.workflow_id,
        name=name,
        description=str(ad_request.get("product_description") or ""),
        version=1,
        status="draft",
        nodes=nodes,
        edges=edges,
        created_at=now,
        updated_at=now,
        ad_request=ad_request,
        audio_mode=audio_mode,
    )
