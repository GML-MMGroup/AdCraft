from __future__ import annotations

import json
from pathlib import Path

from app.schemas.ad_workflow import AdWorkflowResponse
from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
)
from app.services.agent_trace import utc_now
from app.services.workflow_state import load_workflow_plan

from app.services.workflow_graph_preservation import (
    _normalize_graph_edges,
    _raw_graph_edge_handles_differ,
)
from app.services.workflow_graph_topology import _refresh_depends_on


def workflow_graph_path(data_dir: Path, workflow_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "workflow.json"


def workflow_versions_path(data_dir: Path, workflow_id: str, node_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "nodes" / node_id / "versions.json"


def load_graph(data_dir: Path, workflow_id: str) -> WorkflowGraph | None:
    path = workflow_graph_path(data_dir, workflow_id)
    if path.exists():
        from app.services.workflow_graph_mutations import (
            _restore_canonical_product_edges_from_sources,
        )
        from app.services.workflow_graph_result_apply import _dedupe_graph_output_assets

        raw_payload = json.loads(path.read_text(encoding="utf-8"))
        graph = _dedupe_graph_output_assets(WorkflowGraph.model_validate(raw_payload))
        changed = _raw_graph_edge_handles_differ(raw_payload, graph)
        changed = _normalize_graph_edges(graph) or changed
        changed = (
            _restore_canonical_product_edges_from_sources(
                data_dir=data_dir,
                graph=graph,
                restore_from_plan=True,
            )
            or changed
        )
        if changed:
            graph = save_graph(data_dir, graph)
        return _dedupe_graph_output_assets(graph)
    plan = load_workflow_plan(data_dir, workflow_id)
    if plan is None:
        return None
    from app.services.workflow_graph_conversion import workflow_response_to_graph
    from app.services.workflow_graph_result_apply import _dedupe_graph_output_assets

    workflow = AdWorkflowResponse.model_validate(plan["workflow"])
    graph = workflow_response_to_graph(
        workflow,
        ad_request=plan.get("ad_request", {}),
        audio_mode=plan.get("audio_mode", "bgm_only"),
    )
    save_graph(data_dir, graph)
    return _dedupe_graph_output_assets(graph)


def save_graph(data_dir: Path, graph: WorkflowGraph) -> WorkflowGraph:
    graph = graph.model_copy(update={"updated_at": utc_now().isoformat()})
    _normalize_graph_edges(graph)
    _refresh_depends_on(graph)
    path = workflow_graph_path(data_dir, graph.workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            graph.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return graph


def _append_node_version(
    data_dir: Path,
    workflow_id: str,
    node: WorkflowGraphNode,
    *,
    reason: str,
) -> None:
    path = workflow_versions_path(data_dir, workflow_id, node.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    versions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    versions.append(
        {
            "version": node.version,
            "reason": reason,
            "created_at": utc_now().isoformat(),
            "node": node.model_dump(mode="json"),
        }
    )
    path.write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
