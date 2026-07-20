from pathlib import Path
from typing import Any

from app.schemas.workflow_working_versions import (
    WorkflowBatchUseCurrentVersionsRequest,
    WorkflowUseCurrentVersionRequest,
)
from app.services.workflow_asset_history import load_node_asset_history
from app.services import workflow_working_version_items as wv_items
from app.services import workflow_working_version_selection as wv_selection
from app.services import workflow_working_version_store as wv_store


def validate_current_version(
    current: Any,
    request: WorkflowUseCurrentVersionRequest,
) -> dict[str, Any]:
    if not isinstance(current, dict):
        raise ValueError("working_version_missing: Current working version is missing.")
    if current.get("status") not in {"ready", "selected"}:
        raise ValueError("working_version_not_ready: Current working version is not ready.")
    if current.get("quality_status") == "failed" and not request.force_use_current_version:
        error = ValueError("quality_blocked: Current working version failed quality review.")
        error.quality_issues = current.get("quality_issues") or []
        raise error
    return current


def select_current_assets(
    data_dir: Path,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    version: dict[str, Any],
    request: WorkflowUseCurrentVersionRequest,
) -> list[dict[str, Any]]:
    return wv_store.select_current_assets(
        data_dir,
        workflow_id=workflow_id,
        node_id=node_id,
        node_type=node_type,
        item_id=item_id,
        version=version,
        force_quality_override=request.force_use_current_version,
        use_for_composition=request.use_for_composition,
    )


def apply_selected_assets_to_output(
    data_dir: Path,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    output: dict[str, Any],
    item_id: str,
    assets: list[dict[str, Any]],
    request: WorkflowUseCurrentVersionRequest,
) -> dict[str, Any]:
    return wv_store.apply_selected_assets_to_output(
        data_dir,
        workflow_id=workflow_id,
        node_id=node_id,
        node_type=node_type,
        output=output,
        item_id=item_id,
        assets=assets,
        quality_override=request.force_use_current_version,
    )


def active_output_assets(data_dir: Path, workflow_id: str, node_id: str) -> list[dict[str, Any]]:
    return wv_items.active_assets_for_output(
        load_node_asset_history(data_dir, workflow_id, node_id)
    )


def batch_target_item_ids(
    items: list[dict[str, Any]],
    request: WorkflowBatchUseCurrentVersionsRequest,
) -> list[str]:
    return wv_selection.batch_target_item_ids(items, request)
