from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.media_paths import with_public_urls
from app.services.workflow_item_prompt_utils import item_id_from_payload, item_prompt_from_payload
from app.services import workflow_working_version_items as wv_items


def asset_prompt_records_for_item(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    item_id = item_id_from_payload(item)
    item_prompt = item_prompt_from_payload(item)
    matching = [
        asset
        for asset in assets
        if wv_items.asset_matches_item(asset, item_id, node_type)
        and str(asset.get("semantic_type") or "") in wv_items.supported_semantics(node_type)
    ]
    records = [
        asset_prompt_record(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            item_id=item_id,
            item_prompt=item_prompt,
            asset=asset,
            slot_assets=[candidate for candidate in matching if same_asset_slot(candidate, asset)],
        )
        for asset in matching
    ]
    records.sort(
        key=lambda item: (str(item.get("asset_slot_id") or ""), str(item.get("asset_id") or ""))
    )
    return with_public_urls(records)


def asset_prompt_record(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    item_prompt: str,
    asset: dict[str, Any],
    slot_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    slot_id = asset_slot_id(asset)
    selected_assets = [
        candidate
        for candidate in slot_assets
        if candidate.get("is_active") is True and candidate.get("is_archived") is not True
    ]
    candidate_assets = [
        candidate
        for candidate in slot_assets
        if wv_items.asset_is_working_candidate(candidate)
        and candidate.get("is_archived") is not True
    ]
    current_assets = wv_items.latest_version_assets(candidate_assets)
    selected_version = wv_items.version_from_assets(
        selected_assets,
        source="selected",
        prompt=asset_prompt_value(asset, item_prompt),
    )
    current_version = wv_items.version_from_assets(
        current_assets,
        source="generation",
        prompt=asset_prompt_value(asset, item_prompt),
    )
    return {
        "asset_id": str(asset.get("asset_id") or ""),
        "asset_slot_id": slot_id,
        "parent_item_id": item_id,
        "node_id": str(asset.get("node_id") or node_id),
        "node_type": node_type,
        "media_type": _first_string(asset, "media_type", "asset_type", "type", "kind"),
        "semantic_type": str(asset.get("semantic_type") or ""),
        "asset_role": str(asset.get("asset_role") or asset.get("role") or asset.get("kind") or ""),
        "prompt": asset_prompt_value(asset, item_prompt),
        "prompt_source": str(
            asset.get("prompt_source") or metadata.get("prompt_source") or "provider"
        ),
        "manual_prompt_dirty": bool(
            asset.get("manual_prompt_dirty") or metadata.get("manual_prompt_dirty")
        ),
        "generation_prompt": generation_prompt_value(asset, item_prompt),
        "provider_prompt": str(
            asset.get("provider_prompt") or metadata.get("provider_prompt") or ""
        ),
        "negative_prompt": str(
            asset.get("negative_prompt") or metadata.get("negative_prompt") or ""
        ),
        "current_working_version": current_version,
        "selected_version": selected_version,
        "history_versions": _history_versions_for_slot(
            slot_assets,
            selected_version,
            current_version,
            asset_prompt_value(asset, item_prompt),
        ),
        "metadata": {**deepcopy(metadata), "asset_slot_id": slot_id},
    }


def asset_slot_id(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    for value in (asset.get("asset_slot_id"), metadata.get("asset_slot_id")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(asset.get("asset_id") or "")


def same_asset_slot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return asset_slot_id(left) == asset_slot_id(right)


def asset_prompt_value(asset: dict[str, Any], item_prompt: str = "") -> str:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    for value in (
        asset.get("prompt"),
        asset.get("asset_prompt"),
        metadata.get("source_asset_prompt"),
        metadata.get("asset_prompt"),
        metadata.get("prompt"),
        asset.get("provider_prompt"),
        metadata.get("provider_prompt"),
        item_prompt,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def generation_prompt_value(asset: dict[str, Any], item_prompt: str = "") -> str:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    for value in (
        asset.get("generation_prompt"),
        metadata.get("generation_prompt"),
        asset.get("provider_prompt"),
        metadata.get("provider_prompt"),
        asset_prompt_value(asset, item_prompt),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _history_versions_for_slot(
    slot_assets: list[dict[str, Any]],
    selected_version: dict[str, Any] | None,
    current_version: dict[str, Any] | None,
    prompt: str,
) -> list[dict[str, Any]]:
    history_versions: list[dict[str, Any]] = []
    current_ids = set(current_version.get("asset_ids", []) if current_version else [])
    selected_ids = set(selected_version.get("asset_ids", []) if selected_version else [])
    for group in wv_items.group_assets_by_version(slot_assets):
        group_ids = {str(asset.get("asset_id") or "") for asset in group}
        if group_ids == current_ids:
            continue
        if not current_ids and group_ids == selected_ids:
            continue
        version = wv_items.version_from_assets(group, source="history", prompt=prompt)
        if version:
            history_versions.append(version)
    history_versions.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return history_versions


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
