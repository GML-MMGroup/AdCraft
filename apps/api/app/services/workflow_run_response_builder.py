from typing import Any

from app.schemas.workflow_nodes import WorkflowRunResponse


def build_workflow_run_response(
    *,
    failed_node_errors: list[dict[str, str]] | None = None,
    **payload: Any,
) -> WorkflowRunResponse:
    if failed_node_errors is not None:
        payload["failed_nodes"] = failed_node_errors
        payload.setdefault(
            "failed_node_ids",
            [
                str(node.get("node_id") or "")
                for node in failed_node_errors
                if str(node.get("node_id") or "")
            ],
        )
    return WorkflowRunResponse(**payload)
