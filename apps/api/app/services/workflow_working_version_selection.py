from typing import Any

from app.schemas.workflow_working_versions import WorkflowBatchUseCurrentVersionsRequest
from app.services.workflow_item_prompt_utils import item_id_from_payload


def batch_target_item_ids(
    items: list[dict[str, Any]],
    request: WorkflowBatchUseCurrentVersionsRequest,
) -> list[str]:
    if request.scope == "listed_items":
        return [item_id for item_id in request.item_ids if item_id]
    if request.scope in {"all_needs_apply_in_node", "selected_shots"}:
        return [
            item_id_from_payload(item)
            for item in items
            if item.get("needs_apply") and item_id_from_payload(item)
        ]
    raise ValueError(f"Unsupported batch scope: {request.scope}.")
