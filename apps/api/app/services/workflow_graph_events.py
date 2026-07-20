from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import (
    WorkflowGraphNode,
)
from app.services.canvas_runtime_events import CanvasRuntimeEventService


def _payload_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return str(status) if status else None


def _append_canvas_graph_events(
    *,
    data_dir: Path,
    workflow_id: str,
    node: WorkflowGraphNode,
    result: dict[str, Any],
    graph_version: int,
) -> None:
    events = CanvasRuntimeEventService(data_dir)
    node_run_id = str(result.get("node_run_id") or "") or None
    output_status = _payload_status(result.get("output")) or _payload_status(result)
    events.append_event(
        workflow_id,
        "graph_updated",
        node_id=node.id,
        node_type=node.node_type,
        resource_type="graph",
        resource_id=workflow_id,
        version=graph_version,
        payload={
            "node_id": node.id,
            "node_run_id": node_run_id,
            "refresh": ["workflow_graph"],
        },
    )
    events.append_node_output_updated(
        workflow_id,
        execution_id=None,
        node_id=node.id,
        node_type=node.node_type,
        node_run_id=node_run_id,
        output_status=output_status,
    )
    if node.output_assets:
        events.append_node_assets_updated(
            workflow_id,
            execution_id=None,
            node_id=node.id,
            node_type=node.node_type,
            node_run_id=node_run_id,
        )
