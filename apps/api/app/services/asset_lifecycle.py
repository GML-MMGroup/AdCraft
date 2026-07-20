from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_asset_lifecycle(
    asset: dict[str, Any],
    *,
    default_origin: str = "generated",
) -> dict[str, Any]:
    origin = str(asset.get("asset_origin") or default_origin or "generated")
    return {
        "asset_id": str(asset.get("asset_id") or ""),
        "asset_state": str(asset.get("asset_state") or _state_for_origin(origin)),
        "asset_visibility": str(asset.get("asset_visibility") or "visible"),
        "asset_origin": origin,
    }


def asset_lineage_from_run(
    *,
    workflow_id: str,
    node_id: str,
    node_run_id: str,
    revision_id: str | None = None,
    working_version_id: str | None = None,
    source_asset_ids: list[str] | None = None,
    source_entity_ids: list[str] | None = None,
    prompt_hash: str | None = None,
    provider: str | None = None,
    provider_model: str | None = None,
    created_from_binding_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_run_id": node_run_id,
        "revision_id": revision_id,
        "working_version_id": working_version_id,
        "source_asset_ids": source_asset_ids or [],
        "source_entity_ids": source_entity_ids or [],
        "prompt_hash": prompt_hash,
        "provider": provider,
        "provider_model": provider_model,
        "created_from_binding_ids": created_from_binding_ids or [],
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def mark_asset_active(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        **asset,
        "asset_state": "active",
        "asset_visibility": "visible",
        "is_active": True,
        "is_archived": False,
    }


def mark_asset_archived(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        **asset,
        "asset_state": "archived",
        "asset_visibility": "archived",
        "is_active": False,
        "is_archived": True,
    }


def mark_missing_file(asset: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    local_path = asset.get("local_path")
    if not isinstance(local_path, str) or not local_path:
        return asset
    if isinstance(local_path, str) and local_path and (data_dir / local_path).exists():
        return asset
    return {
        **asset,
        "asset_state": "deleted_missing_file",
        "asset_visibility": str(asset.get("asset_visibility") or "visible"),
        "warning": "asset_file_missing",
    }


def lifecycle_record_for_asset_run(
    asset: dict[str, Any],
    *,
    workflow_id: str,
    node_id: str,
    node_run_id: str,
    default_origin: str = "provider_generation",
    source_asset_ids: list[str] | None = None,
    source_entity_ids: list[str] | None = None,
    provider: str | None = None,
    provider_model: str | None = None,
    created_from_binding_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        **normalize_asset_lifecycle(asset, default_origin=default_origin),
        "lineage": asset_lineage_from_run(
            workflow_id=workflow_id,
            node_id=node_id,
            node_run_id=node_run_id,
            source_asset_ids=source_asset_ids,
            source_entity_ids=source_entity_ids,
            provider=provider,
            provider_model=provider_model,
            created_from_binding_ids=created_from_binding_ids,
        ),
    }


def compact_lifecycle_hint(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("asset_state", "asset_visibility", "asset_origin")
        if key in record
    }


def _state_for_origin(origin: str) -> str:
    if origin == "user_upload":
        return "uploaded"
    if origin in {"revision_candidate", "working_version"}:
        return "candidate"
    return "generated"
