from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.media_paths import with_public_urls
from app.services.workflow_item_prompt_utils import item_id_from_payload, item_prompt_from_payload
from app.services.workflow_asset_prompts import asset_prompt_records_for_item, asset_slot_id
from app.services import workflow_working_version_items as wv_items
from app.services import workflow_working_version_store as wv_store


def enrich_output(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    node_type: str,
    output: dict[str, Any],
    output_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(output or {})
    assets = wv_store.version_assets(data_dir, workflow_id, node_id, output_assets or [])
    items = wv_items.payload_items(enriched, node_type, dedupe=False)
    if not items:
        items = wv_items.ensure_default_items(enriched, assets, node_type)
    for index, item in enumerate(items, start=1):
        enrich_item(
            item,
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            assets=assets,
            fallback_order=index,
        )
    _stabilize_region_collections(enriched, node_type, _unique_items(items))
    return with_public_urls(enriched)


def enrich_item(
    item: dict[str, Any],
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    assets: list[dict[str, Any]],
    fallback_order: int,
) -> None:
    item_id = item_id_from_payload(item)
    if not item_id:
        item_id = wv_items.synthesize_item_id(node_type, fallback_order)
    item["item_id"] = item_id
    item.setdefault("item_type", wv_items.default_item_type(node_type))
    item.setdefault("order", wv_items.item_order(item, fallback_order))
    prompt = item_prompt_from_payload(item)
    if prompt:
        item.setdefault("prompt", prompt)
    item.setdefault("prompt_source", _prompt_source(item))
    item.setdefault("manual_prompt_dirty", False)
    item.setdefault("display_name", _display_name(item, item_id))
    item.setdefault("description", _description(item))
    versions = wv_items.versions_for_item(
        assets,
        item_id=item_id,
        node_type=node_type,
        prompt=prompt,
    )
    selected = versions["selected_version"]
    current = versions["current_working_version"]
    item["selected_version"] = selected
    item["current_working_version"] = current
    item["history_versions"] = versions["history_versions"]
    item["needs_apply"] = bool(
        current
        and (
            not selected
            or current.get("version_id") != selected.get("version_id")
            or current.get("asset_ids") != selected.get("asset_ids")
        )
    )
    lifecycle = str(item.get("lifecycle_state") or "")
    if lifecycle not in {"draft", "active", "archived"}:
        lifecycle = "active" if selected else "draft"
    item["lifecycle_state"] = lifecycle
    if current and not item.get("quality_status"):
        item["quality_status"] = current.get("quality_status")
    item["status"] = _item_status(item, selected=selected, current=current)
    item_assets = _item_assets(
        workflow_id=workflow_id,
        node_id=node_id,
        node_type=node_type,
        item_id=item_id,
        assets=assets,
    )
    item["assets"] = item_assets
    item["output_assets"] = [asset for asset in item_assets if asset.get("is_active") is True]
    item["asset_prompts"] = asset_prompt_records_for_item(
        workflow_id=workflow_id,
        node_id=node_id,
        node_type=node_type,
        item=item,
        assets=assets,
    )
    item.setdefault("metadata", {})


def _stabilize_region_collections(
    output: dict[str, Any],
    node_type: str,
    items: list[dict[str, Any]],
) -> None:
    if node_type not in {"character-generation", "scene-generation"}:
        return
    structured = output.setdefault("structured_output", {})
    if not isinstance(structured, dict):
        structured = {}
        output["structured_output"] = structured
    output["media_items"] = items
    if node_type == "character-generation":
        structured["characters"] = items
    elif node_type == "scene-generation":
        structured["scene_assets"] = items
        structured["scenes"] = items


def _unique_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item_id_from_payload(item) or str(id(item))
        if key in by_key:
            _merge_item_fields(by_key[key], item)
            continue
        by_key[key] = item
        unique.append(item)
    return unique


def _merge_item_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key == "metadata" and isinstance(value, dict):
            metadata = target.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata.update({k: v for k, v in value.items() if v not in (None, "", [], {})})
            continue
        if key in {"assets", "output_assets", "asset_prompts", "history_versions"}:
            if not target.get(key) and value:
                target[key] = value
            continue
        if target.get(key) in (None, "", [], {}):
            target[key] = value


def _item_assets(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = [
        _stable_asset_contract(
            workflow_id=workflow_id,
            node_id=node_id,
            node_type=node_type,
            item_id=item_id,
            asset=asset,
        )
        for asset in assets
        if wv_items.asset_matches_item(asset, item_id, node_type)
        and str(asset.get("semantic_type") or "") in wv_items.supported_semantics(node_type)
    ]
    records.sort(
        key=lambda item: (str(item.get("asset_slot_id") or ""), str(item.get("asset_id") or ""))
    )
    return with_public_urls(records)


def _stable_asset_contract(
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    item_id: str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    item = dict(asset)
    semantic_type = str(item.get("semantic_type") or wv_items.semantic_type_for_node(node_type))
    entity_id = str(item.get("entity_id") or item.get("item_id") or item_id)
    media_type = _first_string(item, "media_type", "asset_type", "type", "kind") or (
        "video" if semantic_type.endswith("video") else "image"
    )
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    item["workflow_id"] = str(item.get("workflow_id") or workflow_id)
    item["node_id"] = str(item.get("node_id") or node_id)
    item["source_node_id"] = str(item.get("source_node_id") or node_id)
    item["entity_id"] = entity_id
    item["item_id"] = str(item.get("item_id") or entity_id)
    item["target_entity_id"] = str(item.get("target_entity_id") or entity_id)
    item["asset_slot_id"] = asset_slot_id(item)
    item["semantic_type"] = semantic_type
    item["asset_role"] = str(item.get("asset_role") or item.get("role") or semantic_type)
    item["media_type"] = media_type
    item["asset_type"] = str(item.get("asset_type") or media_type)
    item["type"] = str(item.get("type") or media_type)
    item["is_active"] = item.get("is_active") is not False
    item["selected"] = bool(item["is_active"])
    item["run_id"] = str(item.get("run_id") or metadata.get("revision_id") or "")
    item["revision_id"] = str(
        metadata.get("revision_id") or item.get("revision_id") or item["run_id"]
    )
    item.setdefault("library_state", "linked" if item.get("library_entity_id") else "skipped")
    item.setdefault("library_entity_id", "")
    item.setdefault("library_asset_id", "")
    item["metadata"] = dict(metadata)
    return item


def _item_status(
    item: dict[str, Any],
    *,
    selected: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> str:
    status = str(item.get("status") or "")
    if status in {"ready", "running", "waiting", "failed", "stale", "unknown"}:
        return status
    if current and current.get("status") in {"running", "waiting", "failed"}:
        return str(current["status"])
    if current and (not selected or current.get("asset_ids") != selected.get("asset_ids")):
        return "stale"
    if selected:
        return "ready"
    return "unknown"


def _display_name(item: dict[str, Any], fallback: str) -> str:
    for key in ("display_name", "roleName", "sceneName", "name", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _description(item: dict[str, Any]) -> str:
    for key in ("description", "roleDescription", "sceneDescription", "summary"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _prompt_source(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for value in (item.get("prompt_source"), metadata.get("prompt_source")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "user" if item.get("manual_prompt_dirty") is True else "system"


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
