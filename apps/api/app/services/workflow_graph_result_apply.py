from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
)
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_item_prompt_utils import normalize_node_item_prompt_fields

from app.services.workflow_graph_common import (
    GRAPH_INPUT_CONTEXT_OMIT_KEYS,
    GRAPH_RECURSIVE_OMIT_KEYS,
)
from app.services.workflow_graph_events import _append_canvas_graph_events
from app.services.workflow_graph_store import load_graph, save_graph
from app.services.workflow_graph_topology import _find_node


def update_graph_node_from_run_result(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    result: dict[str, Any],
) -> WorkflowGraph | None:
    graph = load_graph(data_dir, workflow_id)
    if graph is None:
        return None
    node = _find_node(graph, node_id)
    if node is None:
        return graph
    _apply_run_result_to_graph_node(node, result)
    saved_graph = save_graph(data_dir, graph)
    _append_canvas_graph_events(
        data_dir=data_dir,
        workflow_id=workflow_id,
        node=node,
        result=result,
        graph_version=saved_graph.version,
    )
    return saved_graph


def _payload_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return str(status) if status not in (None, "") else None


def _apply_run_result_to_graph_node(node: WorkflowGraphNode, result: dict[str, Any]) -> None:
    failed = result.get("status") == "failed"
    waiting = result.get("status") == "waiting"
    if failed:
        node.status = "failed"
    elif waiting:
        node.status = "waiting"
    elif result.get("status") == "skipped":
        node.status = "skipped"
    else:
        node.status = "completed"
    node.output = (
        _sanitize_graph_payload(result.get("output", {}))
        if isinstance(result.get("output"), dict)
        else {}
    )
    node.input_assets = (
        _sanitize_graph_asset_list(result.get("input_assets", []))
        if isinstance(result.get("input_assets"), list)
        else []
    )
    node.output_assets = (
        dedupe_output_assets(_sanitize_graph_asset_list(result.get("output_assets", [])))
        if isinstance(result.get("output_assets"), list)
        else []
    )
    input_context = result.get("input_context")
    if isinstance(input_context, dict):
        for omitted_key in GRAPH_INPUT_CONTEXT_OMIT_KEYS:
            node.input_context.pop(omitted_key, None)
        node.input_context.update(_sanitize_graph_input_context(input_context))
    node.metadata = dict(node.metadata or {})
    if failed:
        node.metadata["last_error"] = str(result.get("error") or "")
        if result.get("last_failed_run_id"):
            node.metadata["last_failed_run_id"] = str(result.get("last_failed_run_id"))
        if "has_active_output" in result:
            node.metadata["has_active_output"] = bool(result.get("has_active_output"))
    elif waiting:
        node.metadata.pop("last_error", None)
        node.metadata.pop("last_failed_run_id", None)
        node.metadata["has_active_output"] = bool(result.get("has_active_output", False))
    else:
        node.metadata.pop("last_error", None)
        node.metadata.pop("last_failed_run_id", None)
        node.metadata.pop("has_active_output", None)
    node.stale = waiting
    node.stale_reason = "waiting_for_segments" if waiting else None


def _sanitize_graph_input_context(input_context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize_graph_payload(value)
        for key, value in input_context.items()
        if key not in GRAPH_INPUT_CONTEXT_OMIT_KEYS
    }


def _sanitize_graph_asset_list(assets: list[Any]) -> list[dict[str, Any]]:
    return [
        sanitized
        for asset in assets
        if isinstance(asset, dict)
        for sanitized in [_sanitize_graph_payload(asset)]
        if isinstance(sanitized, dict)
    ]


def _sanitize_graph_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_graph_payload(item)
            for key, item in value.items()
            if key not in GRAPH_RECURSIVE_OMIT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_graph_payload(item) for item in value]
    return value


def _dedupe_graph_output_assets(graph: WorkflowGraph) -> WorkflowGraph:
    for node in graph.nodes:
        node.output_assets = dedupe_output_assets(node.output_assets)
        normalize_node_item_prompt_fields(node)
    return graph
