from __future__ import annotations

from typing import Any

from app.services.agent_trace import utc_now
from app.services.workflow_run_plan_adapter import (
    can_reuse_active_result as _can_reuse_active_result,
)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def new_items(existing: list[str], incoming: list[str]) -> list[str]:
    seen = set(existing)
    return [item for item in incoming if item not in seen]


def order_node_subset(order: list[str], values: list[str]) -> list[str]:
    value_set = set(values)
    ordered = [node_id for node_id in order if node_id in value_set]
    ordered.extend(node_id for node_id in values if node_id not in set(order))
    return ordered


def should_skip_node_results_only_node(
    active_result: dict[str, Any] | None,
    *,
    force_selected: bool,
    data_dir: Any,
) -> bool:
    if not active_result or force_selected:
        return False
    return _can_reuse_active_result(active_result, data_dir)
