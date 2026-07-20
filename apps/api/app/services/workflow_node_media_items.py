from typing import Any


def media_item(
    *,
    item_id: str,
    item_type: str,
    order: int | None,
    display_name: str,
    prompt: str,
    input_asset_ids: list[str] | None = None,
    reference_mode: str = "strict",
    status: str = "waiting",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "item_type": item_type,
        "order": order,
        "display_name": display_name,
        "prompt": prompt,
        "input_asset_ids": input_asset_ids or [],
        "reference_mode": reference_mode,
        "status": status,
        "output_assets": [],
        "metadata": metadata or {},
    }


def product_media_items(
    product_design: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    products = product_design.get("products")
    if not isinstance(products, list):
        return []
    reference_mode = _reference_mode_from_context(context)
    return [
        media_item(
            item_id=str(product.get("item_id") or f"product-{index}"),
            item_type="product_image",
            order=_int_value(product.get("order"), index),
            display_name=str(product.get("display_name") or f"Product image {index}"),
            prompt=str(product.get("prompt") or ""),
            input_asset_ids=_list_of_strings(product.get("input_asset_ids")),
            reference_mode=str(product.get("reference_mode") or reference_mode),
            status=str(product.get("status") or "waiting"),
            metadata=product.get("metadata") if isinstance(product.get("metadata"), dict) else {},
        )
        for index, product in enumerate(products, start=1)
        if isinstance(product, dict)
    ]


def character_media_items(
    character_design: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    characters = character_design.get("characters")
    if not isinstance(characters, list):
        return []
    reference_mode = _reference_mode_from_context(context)
    return [
        media_item(
            item_id=str(character.get("character_id") or f"character-{index}"),
            item_type="character",
            order=index,
            display_name=str(character.get("name") or f"Character {index}"),
            prompt=str(character.get("appearance") or ""),
            input_asset_ids=_list_of_strings(character.get("input_asset_ids")),
            reference_mode=reference_mode,
            metadata={"role": character.get("role")},
        )
        for index, character in enumerate(characters, start=1)
        if isinstance(character, dict)
    ]


def scene_media_items(
    scene_design: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    scenes = scene_design.get("scenes")
    if not isinstance(scenes, list):
        return []
    reference_mode = _reference_mode_from_context(context)
    return [
        media_item(
            item_id=str(scene.get("scene_id") or f"scene-reference-{index}"),
            item_type="scene",
            order=_int_value(scene.get("order"), index),
            display_name=str(scene.get("location") or f"Scene {index}"),
            prompt=str(scene.get("atmosphere") or ""),
            input_asset_ids=_list_of_strings(scene.get("input_asset_ids")),
            reference_mode=reference_mode,
            metadata={"lighting": scene.get("lighting")},
        )
        for index, scene in enumerate(scenes, start=1)
        if isinstance(scene, dict)
    ]


def storyboard_media_items(
    storyboard_scenes: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    reference_mode = _reference_mode_from_context(context)
    return [
        media_item(
            item_id=_storyboard_item_id(scene, _int_value(scene.get("order"), index)),
            item_type="storyboard_image",
            order=_int_value(scene.get("order"), index),
            display_name=str(scene.get("shot") or f"Shot {index}"),
            prompt=str(scene.get("visual") or ""),
            input_asset_ids=_list_of_strings(scene.get("input_asset_ids")),
            reference_mode=reference_mode,
            metadata={"scene_id": scene.get("scene_id")},
        )
        for index, scene in enumerate(storyboard_scenes, start=1)
        if isinstance(scene, dict)
    ]


def storyboard_video_media_items(
    storyboard_video_prompt: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    scene_prompts = storyboard_video_prompt.get("scene_prompts")
    if not isinstance(scene_prompts, list):
        return []
    reference_mode = _reference_mode_from_context(context)
    return [
        media_item(
            item_id=str(scene.get("item_id") or f"segment-{index}"),
            item_type="storyboard_video",
            order=_int_value(scene.get("order"), index),
            display_name=f"Segment {index}",
            prompt=str(scene.get("prompt") or ""),
            input_asset_ids=_list_of_strings(scene.get("input_asset_ids")),
            reference_mode=reference_mode,
            metadata={"scene_id": scene.get("scene_id")},
        )
        for index, scene in enumerate(scene_prompts, start=1)
        if isinstance(scene, dict)
    ]


def media_items_for_node(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
    node_type: str,
) -> list[dict[str, Any]]:
    existing_items = output.get("media_items")
    if isinstance(existing_items, list) and existing_items:
        base_items = [item for item in existing_items if isinstance(item, dict)]
    else:
        base_items = infer_media_items_from_assets(assets, node_type)
    return attach_assets_to_media_items(base_items, assets, node_type)


def infer_media_items_from_assets(
    assets: list[dict[str, Any]],
    node_type: str,
) -> list[dict[str, Any]]:
    items = []
    item_type = item_type_for_node(node_type)
    if item_type is None:
        return items
    for index, asset in enumerate(assets, start=1):
        order = _int_value(asset.get("order") or asset.get("scene"), index)
        item_id = asset_item_id(asset, node_type, order)
        items.append(
            media_item(
                item_id=item_id,
                item_type=item_type,
                order=order,
                display_name=asset_item_display_name(asset, node_type, order),
                prompt=str(asset.get("prompt") or ""),
                input_asset_ids=_list_of_strings(asset.get("input_asset_ids")),
                reference_mode="strict",
                status=str(asset.get("status") or "ready"),
                metadata={"asset_id": asset.get("asset_id")},
            )
        )
    return items


def attach_assets_to_media_items(
    media_items: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    node_type: str,
) -> list[dict[str, Any]]:
    attached = []
    for item in media_items:
        item_copy = dict(item)
        item_order = _int_value(item_copy.get("order"), 0)
        item_assets = [
            asset
            for asset in assets
            if asset_matches_media_item(asset, item_copy, node_type, item_order)
        ]
        if item_assets:
            item_copy["output_assets"] = item_assets
            if all(str(asset.get("status") or "ready") != "failed" for asset in item_assets):
                item_copy["status"] = "ready"
        else:
            item_copy.setdefault("output_assets", [])
        attached.append(item_copy)
    return attached


def asset_matches_media_item(
    asset: dict[str, Any],
    item: dict[str, Any],
    node_type: str,
    item_order: int,
) -> bool:
    item_id = str(item.get("item_id") or "")
    if not item_id:
        return False
    order = _int_value(asset.get("order") or asset.get("scene"), 0)
    candidates = {
        str(asset.get("entity_id") or ""),
        str(asset.get("shot_id") or ""),
        str(asset.get("item_id") or ""),
        str(asset.get("character_id") or ""),
        str(asset.get("scene_id") or ""),
        str(asset.get("asset_id") or ""),
    }
    if order:
        candidates.add(asset_item_id(asset, node_type, order))
    if item_id in candidates:
        return True
    return bool(item_order and order and item_order == order)


def item_type_for_node(node_type: str) -> str | None:
    return {
        "product-generation": "product_image",
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard_image",
        "storyboard-video-generation": "storyboard_video",
    }.get(node_type)


def asset_item_id(asset: dict[str, Any], node_type: str, order: int) -> str:
    if node_type == "character-generation":
        return str(asset.get("character_id") or asset.get("entity_id") or f"character-{order}")
    if node_type == "product-generation":
        return str(asset.get("product_id") or asset.get("entity_id") or f"product-{order}")
    if node_type == "scene-generation":
        return str(asset.get("scene_id") or asset.get("entity_id") or f"scene-reference-{order}")
    if node_type == "storyboard":
        return str(
            asset.get("shot_id")
            or asset.get("item_id")
            or asset.get("entity_id")
            or f"shot-{order}"
        )
    if node_type == "storyboard-video-generation":
        return str(
            asset.get("shot_id")
            or asset.get("item_id")
            or asset.get("entity_id")
            or f"segment-{order}"
        )
    return str(asset.get("entity_id") or asset.get("asset_id") or f"item-{order}")


def asset_item_display_name(asset: dict[str, Any], node_type: str, order: int) -> str:
    if node_type == "character-generation":
        return str(asset.get("character_name") or f"Character {order}")
    if node_type == "product-generation":
        return str(asset.get("display_name") or f"Product image {order}")
    if node_type == "scene-generation":
        return f"Scene {order}"
    if node_type == "storyboard":
        return f"Shot {order}"
    if node_type == "storyboard-video-generation":
        return f"Segment {order}"
    return f"Item {order}"


def _reference_mode_from_context(context: dict[str, Any]) -> str:
    metadata = context.get("metadata")
    if isinstance(metadata, dict):
        reference_mode = metadata.get("reference_mode")
        if isinstance(reference_mode, str) and reference_mode.strip():
            return reference_mode
    reference_mode = context.get("reference_mode")
    return str(reference_mode) if isinstance(reference_mode, str) and reference_mode else "strict"


def _storyboard_item_id(scene: dict[str, Any], order: int) -> str:
    return str(scene.get("item_id") or scene.get("shot_id") or f"shot-{order}")


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
