from copy import deepcopy
from typing import Any

from app.services.agent_trace import utc_now
from app.services import workflow_working_version_items as wv_items


def add_item_to_output(
    node_output: dict[str, Any],
    *,
    node_type: str,
    item_type: str | None,
    prompt: str,
    insert_mode: str,
    relative_item_id: str | None,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = deepcopy(node_output or {})
    output.setdefault("structured_output", {})
    items = wv_items.canonical_items(output, node_type, create=True)
    resolved_item_type = item_type or wv_items.default_item_type(node_type)
    item_id = wv_items.next_item_id(items, resolved_item_type)
    item = wv_items.new_item_payload(
        item_id=item_id,
        item_type=resolved_item_type,
        node_type=node_type,
        prompt=prompt,
        order=len(items) + 1,
        metadata=metadata,
    )
    wv_items.insert_item(items, item, insert_mode, relative_item_id)
    wv_items.sync_media_items(output, items)
    wv_items.renumber_items(items)
    return output, item


def archive_draft_item(output: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = wv_items.require_item(output, item_id)
    item["lifecycle_state"] = "archived"
    item["archived_at"] = utc_now().isoformat()
    return item
