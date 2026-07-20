from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.services.media_paths import with_public_urls
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_item_prompt_utils import item_id_from_payload


def payload_items(
    payload: dict[str, Any],
    node_type: str,
    *,
    dedupe: bool = True,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for container in payload_containers(payload):
        for key in collection_keys(node_type):
            value = container.get(key)
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    if dedupe:
                        item_key = item_id_from_payload(item) or str(id(item))
                        if item_key in seen:
                            continue
                        seen.add(item_key)
                    items.append(item)
    return items


def payload_containers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [payload]
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        containers.append(structured)
    return containers


def canonical_items(
    payload: dict[str, Any], node_type: str, *, create: bool
) -> list[dict[str, Any]]:
    structured = payload.setdefault("structured_output", {})
    if not isinstance(structured, dict):
        structured = {}
        payload["structured_output"] = structured
    key = canonical_collection_key(node_type)
    value = structured.get(key)
    if isinstance(value, list):
        return value
    if create:
        structured[key] = []
        return structured[key]
    return []


def ensure_default_items(
    payload: dict[str, Any],
    assets: list[dict[str, Any]],
    node_type: str,
) -> list[dict[str, Any]]:
    items = canonical_items(payload, node_type, create=True)
    seen: set[str] = set()
    for index, asset in enumerate(assets, start=1):
        item_id = asset_entity_id(asset) or str(asset.get("asset_id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        items.append(
            new_item_payload(
                item_id=item_id,
                item_type=default_item_type(node_type),
                node_type=node_type,
                prompt=str(asset.get("prompt") or ""),
                order=index,
                metadata={},
            )
        )
    sync_media_items(payload, items)
    return items


def collection_keys(node_type: str) -> tuple[str, ...]:
    if not node_type:
        return (
            "productItems",
            "products",
            "characterItems",
            "characters",
            "scene_assets",
            "sceneItems",
            "scenes",
            "storyboardItems",
            "shots",
            "storyboardVideoItems",
            "videoSegments",
            "segments",
            "media_items",
            "items",
        )
    return {
        "product-generation": ("productItems", "products", "media_items", "items"),
        "character-generation": ("characterItems", "characters", "media_items", "items"),
        "scene-generation": ("scene_assets", "sceneItems", "scenes", "media_items", "items"),
        "storyboard": ("storyboardItems", "shots", "media_items", "items"),
        "storyboard-video-generation": (
            "storyboardVideoItems",
            "videoSegments",
            "segments",
            "media_items",
            "items",
        ),
    }.get(node_type, ("media_items", "items"))


def canonical_collection_key(node_type: str) -> str:
    return {
        "product-generation": "products",
        "character-generation": "characters",
        "scene-generation": "scenes",
        "storyboard": "storyboardItems",
        "storyboard-video-generation": "videoSegments",
    }.get(node_type, "items")


def default_item_type(node_type: str) -> str:
    return {
        "product-generation": "product",
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard_image",
        "storyboard-video-generation": "storyboard_video",
    }.get(node_type, "item")


def semantic_type_for_node(node_type: str) -> str:
    return {
        "product-generation": "product_image",
        "character-generation": "character_main",
        "scene-generation": "scene_main",
        "storyboard": "storyboard_image",
        "storyboard-video-generation": "storyboard_video",
    }.get(node_type, "item")


def supported_semantics(node_type: str) -> set[str]:
    return {
        "product-generation": {"product_image"},
        "character-generation": {
            "character_main",
            "character_face_id",
            "character_three_view",
            "character_concept",
        },
        "scene-generation": {"scene_main", "scene_multi_view", "scene_reference", "scene_angle"},
        "storyboard": {"storyboard_image"},
        "storyboard-video-generation": {"storyboard_video"},
    }.get(node_type, set())


def asset_type_for_node(node_type: str) -> str:
    return "video" if node_type == "storyboard-video-generation" else "image"


def asset_root_for_node(node_type: str) -> str:
    return {
        "product-generation": "assets/images",
        "character-generation": "characters",
        "scene-generation": "scenes",
        "storyboard": "storyboards",
        "storyboard-video-generation": "videos",
    }.get(node_type, "assets")


def new_item_payload(
    *,
    item_id: str,
    item_type: str,
    node_type: str,
    prompt: str,
    order: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    item = {
        "item_id": item_id,
        "item_type": item_type,
        "order": order,
        "prompt": prompt,
        "lifecycle_state": "draft",
        "current_working_version": None,
        "selected_version": None,
        "history_versions": [],
        "needs_apply": False,
        "metadata": dict(metadata),
    }
    if node_type == "scene-generation":
        item["sceneId"] = item_id
        item["sceneName"] = item_id
        item["scenePrompt"] = prompt
    elif node_type == "character-generation":
        item["roleId"] = item_id
        item["roleName"] = item_id
        item["rolePrompt"] = prompt
    elif node_type == "product-generation":
        item["productId"] = item_id
        item["productPrompt"] = prompt
    elif node_type == "storyboard":
        item["shotId"] = item_id
        item["storyboardImagePrompt"] = prompt
    elif node_type == "storyboard-video-generation":
        item["shot_id"] = item_id
        item["shotId"] = item_id
        item["storyboardVideoPrompt"] = prompt
    return item


def insert_item(
    items: list[dict[str, Any]],
    item: dict[str, Any],
    mode: str,
    relative_item_id: str | None,
) -> None:
    if mode == "append":
        items.append(item)
        return
    if not relative_item_id:
        raise ValueError("relative_item_id is required.")
    index = next(
        (
            idx
            for idx, existing in enumerate(items)
            if item_id_from_payload(existing) == relative_item_id
        ),
        None,
    )
    if index is None:
        raise ValueError("relative item was not found.")
    insert_at = index if mode == "insert_before" else index + 1
    items.insert(insert_at, item)


def renumber_items(items: list[dict[str, Any]]) -> None:
    for index, item in enumerate(items, start=1):
        item["order"] = index


def sync_media_items(payload: dict[str, Any], items: list[dict[str, Any]]) -> None:
    payload["media_items"] = items


def next_item_id(items: list[dict[str, Any]], item_type: str) -> str:
    prefix = {
        "scene": "scene",
        "character": "character",
        "product": "product",
        "storyboard_image": "shot",
        "storyboard_video": "shot",
    }.get(item_type, item_type or "item")
    existing = {item_id_from_payload(item) for item in items}
    index = len(existing) + 1
    candidate = f"{prefix}-{index}"
    while candidate in existing:
        index += 1
        candidate = f"{prefix}-{index}"
    return candidate


def require_item(payload: dict[str, Any], item_id: str) -> dict[str, Any]:
    for item in payload_items(payload, ""):
        if item_id_from_payload(item) == item_id:
            return item
    raise ValueError(f"Target item not found: {item_id}.")


def versions_for_item(
    assets: list[dict[str, Any]],
    *,
    item_id: str,
    node_type: str,
    prompt: str,
) -> dict[str, Any]:
    matching = [
        asset
        for asset in assets
        if asset_matches_item(asset, item_id, node_type)
        and str(asset.get("semantic_type") or "") in supported_semantics(node_type)
    ]
    selected_assets = [asset for asset in matching if asset.get("is_active") is True]
    candidate_assets = [
        asset
        for asset in matching
        if asset_is_working_candidate(asset) and asset.get("is_archived") is not True
    ]
    current_assets = latest_version_assets(candidate_assets) or selected_assets
    selected_version = version_from_assets(selected_assets, source="selected", prompt=prompt)
    current_version = version_from_assets(current_assets, source="generation", prompt=prompt)
    history_versions = history_versions_for_item(
        matching, selected_version, current_version, prompt
    )
    return {
        "selected_version": selected_version,
        "current_working_version": current_version,
        "history_versions": history_versions,
    }


def history_versions_for_item(
    matching: list[dict[str, Any]],
    selected_version: dict[str, Any] | None,
    current_version: dict[str, Any] | None,
    prompt: str,
) -> list[dict[str, Any]]:
    history_versions: list[dict[str, Any]] = []
    current_ids = set(current_version.get("asset_ids", []) if current_version else [])
    selected_ids = set(selected_version.get("asset_ids", []) if selected_version else [])
    for group in group_assets_by_version(matching):
        group_ids = {str(asset.get("asset_id") or "") for asset in group}
        if group_ids == current_ids:
            continue
        if not current_ids and group_ids == selected_ids:
            continue
        version = version_from_assets(group, source="history", prompt=prompt)
        if version:
            history_versions.append(version)
    if selected_version and current_version and selected_ids and selected_ids != current_ids:
        if not any(
            set(version.get("asset_ids", [])) == selected_ids for version in history_versions
        ):
            history_versions.append(
                {**selected_version, "status": "selected", "source": "selected"}
            )
    history_versions.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return history_versions


def asset_matches_item(asset: dict[str, Any], item_id: str, node_type: str) -> bool:
    candidates = {
        str(asset.get(key) or "")
        for key in (
            "entity_id",
            "item_id",
            "scene_id",
            "sceneId",
            "character_id",
            "characterId",
            "roleId",
            "role_id",
            "shotId",
            "shot_id",
            "segment_id",
            "segmentId",
            "productId",
            "product_id",
        )
    }
    if item_id in candidates:
        return True
    if node_type == "storyboard-video-generation":
        return str(asset.get("shot_id") or asset.get("shotId") or "") == item_id
    return False


def asset_entity_id(asset: dict[str, Any]) -> str:
    for key in (
        "entity_id",
        "item_id",
        "scene_id",
        "sceneId",
        "character_id",
        "characterId",
        "roleId",
        "role_id",
        "shotId",
        "shot_id",
        "productId",
        "product_id",
    ):
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def asset_is_working_candidate(asset: dict[str, Any]) -> bool:
    acceptance = str(asset.get("acceptance_status") or "")
    candidate_status = str(asset.get("candidate_status") or "")
    return acceptance == "pending" or candidate_status == "pending"


def latest_version_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = group_assets_by_version(assets)
    if not grouped:
        return []
    grouped.sort(key=lambda group: max(str(asset.get("created_at") or "") for asset in group))
    return grouped[-1]


def group_assets_by_version(assets: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        key = version_key(asset)
        groups.setdefault(key, []).append(asset)
    return list(groups.values())


def version_key(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    return str(
        metadata.get("revision_id")
        or asset.get("revision_id")
        or asset.get("run_id")
        or asset.get("asset_id")
        or uuid4().hex
    )


def version_from_assets(
    assets: list[dict[str, Any]],
    *,
    source: str,
    prompt: str,
) -> dict[str, Any] | None:
    if not assets:
        return None
    assets = sorted(assets, key=lambda asset: str(asset.get("asset_id") or ""))
    first = assets[0]
    metadata = first.get("metadata") if isinstance(first.get("metadata"), dict) else {}
    quality_issues: list[Any] = []
    for asset in assets:
        issues = asset.get("quality_issues")
        if isinstance(issues, list):
            quality_issues.extend(issues)
    quality_status = next(
        (
            str(asset.get("quality_status"))
            for asset in assets
            if str(asset.get("quality_status") or "")
        ),
        "unchecked",
    )
    version_id = version_key(first)
    status = "ready"
    if any(str(asset.get("status") or "") in {"failed", "error"} for asset in assets):
        status = "failed"
    elif source == "selected":
        status = "selected"
    return {
        "version_id": version_id,
        "revision_id": metadata.get("revision_id")
        or first.get("revision_id")
        or first.get("run_id"),
        "asset_ids": [
            str(asset.get("asset_id") or "") for asset in assets if asset.get("asset_id")
        ],
        "status": status,
        "prompt": str(first.get("prompt") or metadata.get("prompt") or prompt or ""),
        "provider_prompt": str(
            first.get("provider_prompt") or metadata.get("provider_prompt") or ""
        ),
        "quality_status": quality_status,
        "quality_issues": quality_issues,
        "created_at": str(first.get("created_at") or ""),
        "source": source,
        "selected_at": first.get("selected_at"),
        "selected_by": first.get("selected_by"),
        "quality_override": bool(
            first.get("quality_override")
            or (isinstance(metadata, dict) and metadata.get("quality_override"))
        ),
        "metadata": {
            "assets": with_public_urls(assets),
            "selected_reason": first.get("selected_reason"),
            "selected_for_composition": first.get("selected_for_composition"),
        },
    }


def active_assets_for_output(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return with_public_urls(
        dedupe_output_assets(
            [
                deepcopy(asset)
                for asset in history
                if asset.get("is_active") is True and asset.get("is_archived") is not True
            ]
        )
    )


def asset_uri(asset: dict[str, Any]) -> str:
    for key in ("local_path", "uri", "public_url", "remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def set_item_uri(item: dict[str, Any], node_type: str, uri: str) -> None:
    field = {
        "product-generation": "productImageUri",
        "character-generation": "roleMainImageUri",
        "scene-generation": "sceneMainImageUri",
        "storyboard": "storyboardImageUri",
        "storyboard-video-generation": "storyboardVideoUri",
    }.get(node_type)
    if field:
        item[field] = uri


def item_order(item: dict[str, Any], fallback: int) -> int:
    for key in ("order", "shotIndex", "scene", "index"):
        value = item.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return fallback


def synthesize_item_id(node_type: str, index: int) -> str:
    prefix = (
        "shot"
        if node_type in {"storyboard", "storyboard-video-generation"}
        else default_item_type(node_type)
    )
    return f"{prefix}-{index}"
