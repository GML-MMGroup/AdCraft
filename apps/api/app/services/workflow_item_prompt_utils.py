from __future__ import annotations

# V1/legacy compatibility only. V2 high-risk provider, repair, fallback,
# and storyboard detail prompt paths must not import this module.

from typing import Any

from app.services.workflow_asset_contract import extract_provider_output_assets


ITEM_COLLECTION_KEYS = (
    "media_items",
    "mediaItems",
    "characterItems",
    "sceneItems",
    "storyboardItems",
    "storyboardVideoItems",
    "videoSegments",
    "productItems",
    "items",
    "characters",
    "scenes",
    "shots",
    "segments",
    "products",
)

PROMPT_KEYS = (
    "prompt",
    "rolePrompt",
    "scenePrompt",
    "storyboardImagePrompt",
    "storyboardVideoPrompt",
    "productPrompt",
    "provider_prompt",
    "providerPrompt",
    "description",
    "roleDescription",
    "sceneDescription",
    "shotDescription",
    "visual",
    "action",
    "atmosphere",
)

PROMPT_KEY_BY_ITEM_TYPE = {
    "character": "rolePrompt",
    "scene": "scenePrompt",
    "storyboard_image": "storyboardImagePrompt",
    "storyboard_shot": "storyboardImagePrompt",
    "storyboard_video": "storyboardVideoPrompt",
    "storyboard_video_segment": "storyboardVideoPrompt",
    "product": "productPrompt",
    "product_image": "productPrompt",
}


def normalize_node_item_prompt_fields(node: Any) -> None:
    node_type = str(getattr(node, "node_type", "") or "")
    output = getattr(node, "output", None)
    output_assets = getattr(node, "output_assets", None)
    if isinstance(output, dict):
        normalize_item_prompt_fields_in_payload(
            output,
            node_type=node_type,
            output_assets=output_assets if isinstance(output_assets, list) else [],
        )
    input_context = getattr(node, "input_context", None)
    if isinstance(input_context, dict):
        normalize_item_prompt_fields_in_payload(input_context, node_type=node_type)


def normalize_item_prompt_fields_in_payload(
    payload: dict[str, Any],
    *,
    node_type: str,
    output_assets: list[dict[str, Any]] | None = None,
) -> None:
    assets = _assets_from_payload(payload)
    if output_assets:
        assets.extend(asset for asset in output_assets if isinstance(asset, dict))
    _normalize_item_collections(payload, node_type=node_type, assets=assets)
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        _normalize_item_collections(structured, node_type=node_type, assets=assets)


def update_item_prompt_in_payload(
    payload: dict[str, Any],
    *,
    item_id: str,
    prompt: str,
    node_type: str,
    semantic_type: str | None,
    mark_stale: bool,
) -> int:
    updated = _update_item_collections(
        payload,
        item_id=item_id,
        prompt=prompt,
        node_type=node_type,
        semantic_type=semantic_type,
        mark_stale=mark_stale,
    )
    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        updated += _update_item_collections(
            structured,
            item_id=item_id,
            prompt=prompt,
            node_type=node_type,
            semantic_type=semantic_type,
            mark_stale=mark_stale,
        )
    return updated


def item_id_from_payload(item: dict[str, Any]) -> str:
    for key in (
        "item_id",
        "itemId",
        "id",
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
        "entity_id",
        "entityId",
    ):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def item_prompt_from_payload(item: dict[str, Any]) -> str:
    for key in PROMPT_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in ("prompt", "provider_prompt", "providerPrompt", "source_prompt"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def item_semantic_type_for_revision(node_type: str, semantic_type: str | None) -> str:
    semantic = str(semantic_type or "").strip()
    if semantic in {
        "character_main",
        "character_face_id",
        "character_three_view",
        "character_concept",
        "scene_main",
        "scene_multi_view",
        "storyboard_image",
        "storyboard_video",
        "bgm",
        "product_image",
    }:
        return semantic
    if semantic in {"character", ""} and node_type == "character-generation":
        return "character_main"
    if semantic in {"scene", ""} and node_type == "scene-generation":
        return "scene_main"
    if semantic in {"storyboard_shot", "storyboard_image", ""} and node_type == "storyboard":
        return "storyboard_image"
    if (
        semantic
        in {
            "storyboard_video_segment",
            "storyboard_video",
            "",
        }
        and node_type == "storyboard-video-generation"
    ):
        return "storyboard_video"
    if semantic in {"product", ""} and node_type == "product-generation":
        return "product_image"
    if semantic in {"bgm", ""} and node_type == "bgm":
        return "bgm"
    return semantic or "item"


def target_item_context_from_active(active: dict[str, Any], item_id: str) -> dict[str, Any]:
    for container in _active_item_containers(active):
        for item in _iter_item_dicts(container):
            if item_id_from_payload(item) == item_id:
                return dict(item)
    return {}


def item_prompt_from_active(active: dict[str, Any], item_id: str) -> str:
    item = target_item_context_from_active(active, item_id)
    return item_prompt_from_payload(item) if item else ""


def _normalize_item_collections(
    container: dict[str, Any],
    *,
    node_type: str,
    assets: list[dict[str, Any]],
) -> None:
    for item in _iter_item_dicts(container):
        _normalize_item_prompt(item, node_type=node_type, assets=assets)


def _update_item_collections(
    container: dict[str, Any],
    *,
    item_id: str,
    prompt: str,
    node_type: str,
    semantic_type: str | None,
    mark_stale: bool,
) -> int:
    updated = 0
    for item in _iter_item_dicts(container):
        if item_id_from_payload(item) != item_id:
            continue
        item["prompt"] = prompt
        item["prompt_source"] = "user"
        item["manual_prompt_dirty"] = True
        if semantic_type:
            item["semantic_type"] = semantic_type
        prompt_key = _prompt_key_for_item(node_type, item)
        if prompt_key:
            item[prompt_key] = prompt
        if mark_stale:
            item["status"] = "stale"
        metadata = item.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["prompt_source"] = "user"
            metadata["manual_prompt_dirty"] = True
        updated += 1
    return updated


def _iter_item_dicts(container: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ITEM_COLLECTION_KEYS:
        value = container.get(key)
        if isinstance(value, list):
            items.extend(
                item for item in value if isinstance(item, dict) and _looks_like_dynamic_item(item)
            )
    return items


def _looks_like_dynamic_item(item: dict[str, Any]) -> bool:
    return any(
        key in item
        for key in (
            "item_id",
            "itemId",
            "item_type",
            "display_name",
            "roleId",
            "roleName",
            "sceneId",
            "sceneName",
            "shotId",
            "shotIndex",
            "segmentId",
            "productId",
            "prompt",
            "rolePrompt",
            "scenePrompt",
            "storyboardImagePrompt",
            "storyboardVideoPrompt",
            "productPrompt",
        )
    )


def _normalize_item_prompt(
    item: dict[str, Any],
    *,
    node_type: str,
    assets: list[dict[str, Any]],
) -> None:
    item_id = item_id_from_payload(item)
    prompt = item_prompt_from_payload(item)
    if not prompt:
        prompt = _asset_prompt_for_item(item_id, item, assets)
    if prompt:
        item["prompt"] = prompt
        prompt_key = _prompt_key_for_item(node_type, item)
        if prompt_key and not _text(item.get(prompt_key)):
            item[prompt_key] = prompt
    item.setdefault("prompt_source", _prompt_source(item))
    item.setdefault("manual_prompt_dirty", False)


def _prompt_key_for_item(node_type: str, item: dict[str, Any]) -> str:
    item_type = str(
        item.get("item_type")
        or item.get("semantic_type")
        or {
            "character-generation": "character",
            "scene-generation": "scene",
            "storyboard": "storyboard_image",
            "storyboard-video-generation": "storyboard_video",
            "product-generation": "product_image",
        }.get(node_type, "")
    )
    prompt_key = PROMPT_KEY_BY_ITEM_TYPE.get(item_type)
    if prompt_key:
        return prompt_key
    for key in PROMPT_KEY_BY_ITEM_TYPE.values():
        if key in item:
            return key
    return ""


def _prompt_source(item: dict[str, Any]) -> str:
    value = item.get("prompt_source")
    if isinstance(value, str) and value.strip():
        return value.strip()
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("prompt_source")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "user" if item.get("manual_prompt_dirty") is True else "system"


def _asset_prompt_for_item(
    item_id: str,
    item: dict[str, Any],
    assets: list[dict[str, Any]],
) -> str:
    if not item_id:
        return ""
    for asset in assets:
        if not _asset_matches_item(asset, item_id, item):
            continue
        prompt = item_prompt_from_payload(asset)
        if prompt:
            return prompt
    return ""


def _asset_matches_item(asset: dict[str, Any], item_id: str, item: dict[str, Any]) -> bool:
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
            "shotId",
            "shot_id",
            "segment_id",
            "segmentId",
            "asset_id",
        )
    }
    if item_id in candidates:
        return True
    item_order = _positive_int(item.get("order") or item.get("shotIndex"))
    asset_order = _positive_int(asset.get("order") or asset.get("scene") or asset.get("shotIndex"))
    return bool(item_order and asset_order and item_order == asset_order)


def _assets_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_provider_output_assets(payload)


def _active_item_containers(active: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    output = active.get("output")
    if isinstance(output, dict):
        containers.append(output)
        structured = output.get("structured_output")
        if isinstance(structured, dict):
            containers.append(structured)
    input_context = active.get("input_context")
    if isinstance(input_context, dict):
        containers.append(input_context)
    return containers


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0
