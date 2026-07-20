from pathlib import Path
from typing import Any

from app.services.media_paths import public_url_for_path
from app.services.workflow_asset_contract import (
    extract_provider_output_assets,
    normalize_node_output_assets,
)
from app.services.workflow_item_prompt_utils import normalize_item_prompt_fields_in_payload
from app.services.workflow_node_media_items import media_items_for_node
from app.services.workflow_shot_bindings import (
    canonical_storyboard_shots_from_output,
    normalize_scene_assets,
)


CREATIVE_MEDIA_NODE_TYPES = {
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
}


def with_structured_output_and_assets(
    output: dict[str, Any],
    node_type: str,
    workflow_id: str,
) -> dict[str, Any]:
    assets = generic_assets_for_node(output, node_type, workflow_id)
    structured_output = structured_output_for_node(output, assets, node_type, workflow_id)
    media_items = media_items_for_node(output, assets, node_type)
    payload = {
        **output,
        "media_items": media_items,
        "structured_output": structured_output,
        "assets": assets,
        "output_assets": assets,
    }
    normalize_item_prompt_fields_in_payload(payload, node_type=node_type, output_assets=assets)
    return payload


def with_node_output_contract(
    output: dict[str, Any],
    node_type: str,
    workflow_id: str,
) -> dict[str, Any]:
    if "structured_output" in output and ("assets" in output or "output_assets" in output):
        output = normalize_node_output_assets(output)
        output_assets = output.get("output_assets")
        normalize_item_prompt_fields_in_payload(
            output,
            node_type=node_type,
            output_assets=output_assets if isinstance(output_assets, list) else [],
        )
        return output
    if node_type == "script":
        return {
            **output,
            "structured_output": structured_script_output(output),
            "assets": [],
            "output_assets": [],
        }
    if node_type == "final-composition":
        return with_structured_output_and_assets(output, node_type, workflow_id)
    if node_type in CREATIVE_MEDIA_NODE_TYPES and output.get("status") != "optimized":
        return with_structured_output_and_assets(output, node_type, workflow_id)
    return output


def with_node_instance_identity(
    output: dict[str, Any],
    node_id: str,
    node_type: str,
) -> dict[str, Any]:
    retargeted = dict(output)
    retargeted["node_id"] = node_id
    retargeted["node_type"] = node_type
    for key in (
        "assets",
        "output_assets",
        "segments",
        "images",
        "videos",
        "audio",
        "generated_assets",
    ):
        value = retargeted.get(key)
        if isinstance(value, list):
            retargeted[key] = [
                with_asset_node_identity(asset, node_id, node_type)
                if isinstance(asset, dict)
                else asset
                for asset in value
            ]
        elif isinstance(value, dict):
            retargeted[key] = with_asset_node_identity(value, node_id, node_type)
    final_video = retargeted.get("final_video")
    if isinstance(final_video, dict):
        retargeted["final_video"] = with_asset_node_identity(final_video, node_id, node_type)
    media_items = retargeted.get("media_items")
    if isinstance(media_items, list):
        retargeted["media_items"] = [
            with_media_item_node_identity(item, node_id, node_type)
            if isinstance(item, dict)
            else item
            for item in media_items
        ]
    return retargeted


def with_asset_node_identity(
    asset: dict[str, Any],
    node_id: str,
    node_type: str,
) -> dict[str, Any]:
    retargeted = dict(asset)
    if not retargeted.get("node_id") or retargeted.get("node_id") == node_type:
        retargeted["node_id"] = node_id
    if not retargeted.get("source_node_id") or retargeted.get("source_node_id") == node_type:
        retargeted["source_node_id"] = node_id
    retargeted.setdefault("node_type", node_type)
    return retargeted


def with_media_item_node_identity(
    item: dict[str, Any],
    node_id: str,
    node_type: str,
) -> dict[str, Any]:
    retargeted = dict(item)
    if not retargeted.get("node_id") or retargeted.get("node_id") == node_type:
        retargeted["node_id"] = node_id
    if not retargeted.get("source_node_id") or retargeted.get("source_node_id") == node_type:
        retargeted["source_node_id"] = node_id
    retargeted.setdefault("node_type", node_type)
    output_assets = retargeted.get("output_assets")
    if isinstance(output_assets, list):
        retargeted["output_assets"] = [
            with_asset_node_identity(asset, node_id, node_type)
            if isinstance(asset, dict)
            else asset
            for asset in output_assets
        ]
    return retargeted


def generic_assets_for_node(
    output: dict[str, Any],
    node_type: str,
    workflow_id: str,
) -> list[dict[str, Any]]:
    generic_assets: list[dict[str, Any]] = []
    for index, asset in enumerate(extract_output_assets(output), start=1):
        uri = _asset_uri(asset)
        if not uri:
            continue
        asset_type = str(asset.get("asset_type") or asset.get("type") or "document")
        semantic_type = _semantic_type_for_node_asset(node_type, asset, index)
        generic_assets.append(
            {
                **asset,
                "asset_id": str(asset.get("asset_id") or f"{node_type}-asset-{index}"),
                "workflow_id": str(asset.get("workflow_id") or workflow_id),
                "node_id": node_type,
                "asset_type": asset_type,
                "semantic_type": semantic_type,
                "entity_id": _asset_entity_id(node_type, asset, index, workflow_id),
                "uri": uri,
                "mime_type": asset.get("mime_type") or _mime_type_for_asset_type(asset_type),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "duration_seconds": asset.get("duration_seconds"),
                "metadata": _asset_metadata(asset),
            }
        )
    return generic_assets


def extract_output_assets(output: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_provider_output_assets(output)


def structured_output_for_node(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
    node_type: str,
    workflow_id: str,
) -> dict[str, Any]:
    if node_type == "character-generation":
        return {"characters": _structured_characters(assets)}
    if node_type == "product-generation":
        return {"products": _structured_products(assets)}
    if node_type == "scene-generation":
        scene_assets = normalize_scene_assets({"scene_generation": output}, assets)
        return {
            "scenes": _structured_scenes(assets),
            "scene_assets": scene_assets,
        }
    if node_type == "storyboard":
        shots = _structured_storyboard_shots(output, assets)
        return {
            "scene_assets": output.get("scene_assets")
            if isinstance(output.get("scene_assets"), list)
            else [],
            "shots": shots,
            "storyboardItems": _structured_storyboard_items(output, assets, shots),
        }
    if node_type == "storyboard-video-generation":
        return {
            "shots": canonical_storyboard_shots_from_output(output),
            "videoSegments": _structured_video_segments(output, assets),
        }
    if node_type == "bgm":
        return _structured_bgm(output, assets, workflow_id)
    if node_type == "final-composition":
        return _structured_final_composition(output, assets)
    return {}


def structured_script_output(output: dict[str, Any]) -> dict[str, Any]:
    lines = [str(line) for line in output.get("subtitle_lines", []) if str(line).strip()]
    script_text = "\n".join(
        str(output.get(key) or "")
        for key in ("hook", "body", "cta")
        if str(output.get(key) or "").strip()
    )
    if not lines and script_text:
        lines = [line for line in script_text.splitlines() if line.strip()]
    duration_seconds = int(output.get("duration_seconds") or 30)
    cue_count = max(len(lines), 1)
    cue_duration = duration_seconds / cue_count
    subtitle_lines = [
        {
            "lineId": f"line_{index:03d}",
            "startTime": round((index - 1) * cue_duration, 3),
            "endTime": round(index * cue_duration, 3),
            "text": line,
        }
        for index, line in enumerate(lines, start=1)
    ]
    structure_values = output.get("script_structure") or output.get("structure") or []
    structure_items = [
        {
            "segmentId": f"seg_{index:03d}",
            "startTime": round((index - 1) * cue_duration, 3),
            "endTime": round(index * cue_duration, 3),
            "purpose": str(value),
            "visualIntent": str(value),
            "audioIntent": str(value),
        }
        for index, value in enumerate(structure_values, start=1)
    ]
    return {
        "title": str(output.get("title") or "Ad Script"),
        "summary": str(output.get("summary") or output.get("hook") or ""),
        "scriptText": script_text,
        "subtitleLines": subtitle_lines,
        "scriptStructure": structure_items,
        "scriptBeats": output.get("shot_beats") or output.get("beats") or [],
    }


def sanitize_node_output(
    node_type: str,
    output: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    if node_type != "final-composition":
        return output
    return _sanitize_final_composition_output(output, data_dir)


def node_run_status_from_output(
    node_type: str,
    output: dict[str, Any],
    data_dir: Path | None = None,
) -> str:
    output_status = str(output.get("status") or "").lower()
    if output_status == "failed":
        return "failed"
    if output_status == "optimized":
        return "waiting"
    if node_type == "final-composition":
        if output_status == "candidate_pending":
            return "completed"
        if output_status == "ready":
            local_path = output.get("local_path")
            if not isinstance(local_path, str) or not local_path:
                return "failed"
            if data_dir is not None and not (data_dir / local_path).exists():
                return "failed"
            return "completed"
        return "waiting"
    return "completed"


def node_run_error_from_output(
    node_type: str,
    output: dict[str, Any],
) -> str | None:
    if str(output.get("status") or "").lower() == "failed":
        default_error = (
            "Final composition failed."
            if node_type == "final-composition"
            else "Provider execution failed."
        )
        return str(output.get("error") or default_error)
    return None


def node_run_is_waiting(
    node_type: str,
    output: dict[str, Any],
    data_dir: Path | None = None,
) -> bool:
    if str(output.get("status") or "").lower() == "optimized":
        return True
    if node_type != "final-composition":
        return False
    return node_run_status_from_output(node_type, output, data_dir) == "waiting"


def _asset_uri(asset: dict[str, Any]) -> str | None:
    for key in ("public_url", "local_path", "remote_url", "url", "metadata_path"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _semantic_type_for_node_asset(
    node_type: str,
    asset: dict[str, Any],
    index: int,
) -> str:
    role = str(asset.get("role") or asset.get("semantic_type") or "").lower()
    if node_type == "character-generation":
        return _character_semantic_type(role)
    simple_types = {
        "product-generation": "product_image",
        "storyboard": "storyboard_image",
        "storyboard-video-generation": "storyboard_video",
        "bgm": "bgm",
    }
    if node_type in simple_types:
        return simple_types[node_type]
    if node_type == "scene-generation":
        return "scene_multi_view" if "multi" in role else "scene_main"
    if node_type == "final-composition":
        return "final_video" if index == 1 else "timeline"
    return role or "document"


def _character_semantic_type(role: str) -> str:
    role_patterns = (
        ("face", "character_face_id"),
        ("three", "character_three_view"),
        ("concept", "character_concept"),
    )
    for marker, semantic_type in role_patterns:
        if marker in role:
            return semantic_type
    return "character_main"


def _asset_entity_id(
    node_type: str,
    asset: dict[str, Any],
    index: int,
    workflow_id: str,
) -> str:
    if node_type == "character-generation":
        return str(asset.get("character_id") or asset.get("entity_id") or f"role_{index:03d}")
    if node_type == "product-generation":
        return str(asset.get("product_id") or asset.get("entity_id") or f"product-{index}")
    if node_type == "scene-generation":
        return str(
            asset.get("scene_id")
            or asset.get("entity_id")
            or asset.get("scene")
            or f"scene_{index:03d}"
        )
    if node_type in {"storyboard", "storyboard-video-generation"}:
        return str(
            asset.get("shot_id")
            or asset.get("item_id")
            or asset.get("entity_id")
            or f"shot_{index:03d}"
        )
    return str(asset.get("entity_id") or workflow_id)


def _mime_type_for_asset_type(asset_type: str) -> str:
    return {
        "image": "image/png",
        "video": "video/mp4",
        "audio": "audio/mpeg",
        "subtitle": "text/plain",
        "timeline": "application/json",
    }.get(asset_type, "application/json")


def _asset_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = asset.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {
        key: value
        for key, value in asset.items()
        if key
        not in {
            "asset_id",
            "workflow_id",
            "node_id",
            "asset_type",
            "semantic_type",
            "entity_id",
            "uri",
            "mime_type",
            "width",
            "height",
            "duration_seconds",
            "metadata",
        }
    }


def _structured_characters(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not assets:
        return []
    characters = []
    for index, asset in enumerate(assets, start=1):
        if asset.get("semantic_type") != "character_main":
            continue
        role_id = str(asset.get("entity_id") or f"role_{index:03d}")
        characters.append(
            {
                "roleId": role_id,
                "roleName": asset.get("character_name") or f"Character {index}",
                "roleDescription": asset.get("role") or "Generated character reference.",
                "rolePrompt": asset.get("prompt") or "",
                "roleMainImageUri": asset["uri"],
                "roleFaceIdImageUri": "",
                "roleThreeViewImageUri": "",
                "roleConceptImageUri": "",
                "styleTags": [],
                "metadata": {"asset_id": asset["asset_id"]},
            }
        )
    return characters


def _structured_products(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    products = []
    for index, asset in enumerate(assets, start=1):
        if asset.get("semantic_type") != "product_image":
            continue
        product_id = str(asset.get("entity_id") or f"product-{index}")
        products.append(
            {
                "item_id": product_id,
                "productId": product_id,
                "productName": asset.get("display_name") or f"Product image {index}",
                "productPrompt": asset.get("prompt") or "",
                "productImageUri": asset["uri"],
                "referenceMode": asset.get("reference_mode") or "strict",
                "inputAssetIds": asset.get("input_asset_ids") or [],
                "metadata": {
                    "asset_id": asset["asset_id"],
                    **(asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}),
                },
            }
        )
    return products


def _structured_scenes(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenes = []
    for index, asset in enumerate(assets, start=1):
        if asset.get("semantic_type") not in {"scene_main", "scene_multi_view"}:
            continue
        scene_id = str(asset.get("entity_id") or f"scene_{index:03d}")
        scenes.append(
            {
                "sceneId": scene_id,
                "sceneName": f"Scene {index}",
                "sceneDescription": asset.get("role") or "Generated scene reference.",
                "scenePrompt": asset.get("prompt") or "",
                "sceneMainImageUri": asset["uri"]
                if asset.get("semantic_type") == "scene_main"
                else "",
                "sceneMultiViewImageUri": asset["uri"]
                if asset.get("semantic_type") == "scene_multi_view"
                else "",
                "styleTags": [],
                "metadata": {"asset_id": asset["asset_id"]},
            }
        )
    return scenes


def _shot_payload_from_storyboard_asset(asset: dict[str, Any], index: int) -> dict[str, Any]:
    order = _int_value(asset.get("order") or asset.get("scene"), index)
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    bindings = metadata.get("reference_bindings") if isinstance(metadata, dict) else {}
    bindings = bindings if isinstance(bindings, dict) else {}
    return {
        "shot_id": asset.get("shot_id")
        or asset.get("item_id")
        or asset.get("entity_id")
        or f"shot_{order:03d}",
        "item_id": asset.get("item_id")
        or asset.get("shot_id")
        or asset.get("entity_id")
        or f"shot_{order:03d}",
        "order": order,
        "prompt": asset.get("prompt") or "",
        "primary_scene_id": asset.get("primary_scene_id") or bindings.get("primary_scene_id"),
        "scene_reference_ids": asset.get("scene_reference_ids")
        or bindings.get("scene_reference_ids")
        or [],
        "character_ids": asset.get("character_ids") or bindings.get("character_ids") or [],
        "product_reference_ids": asset.get("product_reference_ids")
        or bindings.get("product_reference_ids")
        or [],
        "style_reference_ids": asset.get("style_reference_ids")
        or bindings.get("style_reference_ids")
        or [],
        "no_scene_reason": asset.get("no_scene_reason") or bindings.get("no_scene_reason"),
        "input_asset_ids": asset.get("input_asset_ids") or bindings.get("input_asset_ids") or [],
        "metadata": metadata,
    }


def _storyboard_asset_for_structured_shot(
    assets: list[dict[str, Any]],
    shot: dict[str, Any],
    order: int,
) -> dict[str, Any] | None:
    shot_id = str(shot.get("shot_id") or shot.get("item_id") or "")
    for asset in assets:
        if asset.get("semantic_type") != "storyboard_image":
            continue
        if shot_id and shot_id in {
            str(asset.get("shot_id") or ""),
            str(asset.get("item_id") or ""),
            str(asset.get("entity_id") or ""),
        }:
            return asset
    for asset in assets:
        if (
            asset.get("semantic_type") == "storyboard_image"
            and _int_value(asset.get("order") or asset.get("scene"), 0) == order
        ):
            return asset
    return None


def _structured_storyboard_shots(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_shots = canonical_storyboard_shots_from_output(output)
    if not raw_shots:
        raw_shots = [
            _shot_payload_from_storyboard_asset(asset, index)
            for index, asset in enumerate(assets, start=1)
        ]
    structured: list[dict[str, Any]] = []
    for index, shot in enumerate(raw_shots, start=1):
        order = _storyboard_order(shot, index)
        shot_id = str(shot.get("shot_id") or shot.get("item_id") or f"shot_{order:03d}")
        asset = _storyboard_asset_for_structured_shot(assets, shot, order)
        input_asset_ids = _list_of_strings(
            shot.get("input_asset_ids") or (asset or {}).get("input_asset_ids")
        )
        metadata = dict(shot.get("metadata")) if isinstance(shot.get("metadata"), dict) else {}
        if asset and isinstance(asset.get("metadata"), dict):
            metadata = {**asset["metadata"], **metadata}
        structured.append(
            {
                "shot_id": shot_id,
                "item_id": shot_id,
                "order": order,
                "shot_type": str(shot.get("shot_type") or shot.get("shotType") or ""),
                "prompt": str(
                    shot.get("prompt")
                    or shot.get("storyboardImagePrompt")
                    or shot.get("visual")
                    or (asset or {}).get("prompt")
                    or ""
                ),
                "primary_scene_id": shot.get("primary_scene_id")
                or shot.get("primarySceneId")
                or (asset or {}).get("primary_scene_id"),
                "scene_reference_ids": _list_of_strings(
                    shot.get("scene_reference_ids")
                    or shot.get("sceneReferenceIds")
                    or (asset or {}).get("scene_reference_ids")
                ),
                "character_ids": _list_of_strings(
                    shot.get("character_ids")
                    or shot.get("characterIds")
                    or (asset or {}).get("character_ids")
                ),
                "product_reference_ids": _list_of_strings(
                    shot.get("product_reference_ids")
                    or shot.get("productReferenceIds")
                    or (asset or {}).get("product_reference_ids")
                ),
                "style_reference_ids": _list_of_strings(
                    shot.get("style_reference_ids")
                    or shot.get("styleReferenceIds")
                    or (asset or {}).get("style_reference_ids")
                ),
                "no_scene_reason": shot.get("no_scene_reason")
                or shot.get("noSceneReason")
                or (asset or {}).get("no_scene_reason"),
                "input_asset_ids": input_asset_ids,
                "output_asset_ids": [asset["asset_id"]] if asset and asset.get("asset_id") else [],
                "metadata": metadata,
            }
        )
    return structured


def _structured_storyboard_items(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
    shots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items = []
    storyboard_shots = shots or _structured_storyboard_shots(output, assets)
    for index, shot in enumerate(storyboard_shots, start=1):
        asset = _storyboard_asset_for_structured_shot(assets, shot, _storyboard_order(shot, index))
        shot_id = str(shot.get("shot_id") or shot.get("item_id") or f"shot_{index:03d}")
        metadata = dict(shot.get("metadata")) if isinstance(shot.get("metadata"), dict) else {}
        if asset and asset.get("asset_id"):
            metadata.setdefault("asset_id", asset["asset_id"])
        items.append(
            {
                "shotId": shot_id,
                "shotIndex": _storyboard_order(shot, index),
                "scriptSegmentId": "",
                "shotDescription": shot.get("prompt") or "Generated storyboard image.",
                "characters": shot.get("character_ids") or [],
                "sceneId": str(shot.get("primary_scene_id") or ""),
                "primarySceneId": shot.get("primary_scene_id"),
                "sceneReferenceIds": shot.get("scene_reference_ids") or [],
                "characterIds": shot.get("character_ids") or [],
                "productReferenceIds": shot.get("product_reference_ids") or [],
                "styleReferenceIds": shot.get("style_reference_ids") or [],
                "noSceneReason": shot.get("no_scene_reason"),
                "inputAssetIds": shot.get("input_asset_ids") or [],
                "storyboardImagePrompt": shot.get("prompt") or output.get("provider_prompt") or "",
                "storyboardImageUri": (asset or {}).get("uri") or "",
                "cameraLanguage": "",
                "durationSeconds": shot.get("duration_seconds")
                or (asset or {}).get("duration_seconds")
                or 3,
                "metadata": metadata,
            }
        )
    return items


def _structured_video_segments(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segments = []
    for index, asset in enumerate(assets, start=1):
        if asset.get("semantic_type") != "storyboard_video":
            continue
        shot_id = str(asset.get("entity_id") or f"shot_{index:03d}")
        segments.append(
            {
                "shotId": shot_id,
                "shotIndex": int(asset.get("order") or index),
                "sourceStoryboardImageUri": "",
                "primarySceneId": asset.get("primary_scene_id"),
                "sceneReferenceIds": asset.get("scene_reference_ids") or [],
                "characterIds": asset.get("character_ids") or [],
                "productReferenceIds": asset.get("product_reference_ids") or [],
                "styleReferenceIds": asset.get("style_reference_ids") or [],
                "noSceneReason": asset.get("no_scene_reason"),
                "inputAssetIds": asset.get("input_asset_ids") or [],
                "storyboardVideoPrompt": asset.get("prompt") or output.get("provider_prompt") or "",
                "storyboardVideoUri": asset["uri"],
                "cameraMotionPrompt": "",
                "soundEffectPrompt": "",
                "dialoguePrompt": "",
                "durationSeconds": asset.get("duration_seconds") or 0,
                "metadata": {
                    "asset_id": asset["asset_id"],
                    **(asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}),
                },
            }
        )
    return segments


def _structured_bgm(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
    workflow_id: str,
) -> dict[str, Any]:
    music_asset = next((asset for asset in assets if asset.get("semantic_type") == "bgm"), None)
    return {
        "musicPrompt": output.get("generation_prompt") or output.get("provider_prompt") or "",
        "musicUri": music_asset["uri"] if music_asset else "",
        "durationSeconds": output.get("duration_seconds") or 0,
        "moodTags": [output["mood"]] if output.get("mood") else [],
        "tempo": output.get("tempo") or "",
        "metadata": {"workflow_id": workflow_id},
    }


def _structured_final_composition(
    output: dict[str, Any],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    final_asset = next(
        (asset for asset in assets if asset.get("semantic_type") == "final_video"), None
    )
    return {
        "timeline": output.get("timeline")
        or {
            "tracks": [],
            "durationSeconds": output.get("duration_seconds") or 0,
            "subtitleTrack": [],
            "audioTracks": [],
            "videoTracks": [],
        },
        "finalVideoUri": final_asset["uri"] if final_asset else "",
        "coverImageUri": "",
        "exportSettings": output.get("export_settings")
        or {"resolution": "1080p", "aspectRatio": "9:16", "fps": 30},
    }


def _sanitize_final_composition_output(
    output: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    sanitized = dict(output)
    status = str(sanitized.get("status") or "").lower()
    if status == "failed":
        return _without_playable_final_paths(sanitized)
    if status == "ready":
        local_path = sanitized.get("local_path")
        if (
            not isinstance(local_path, str)
            or not local_path
            or not (data_dir / local_path).exists()
        ):
            sanitized["status"] = "failed"
            sanitized["error"] = (
                sanitized.get("error")
                or "Final composition reported ready but final video file does not exist."
            )
            return _without_playable_final_paths(sanitized)
        sanitized["public_url"] = public_url_for_path(local_path)
    return sanitized


def _without_playable_final_paths(output: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(output)
    sanitized["local_path"] = None
    sanitized["public_url"] = None
    sanitized.pop("url", None)
    sanitized.pop("remote_url", None)
    return sanitized


def _is_unavailable_single_asset_output(output: dict[str, Any]) -> bool:
    status = str(output.get("status") or "").lower()
    if status == "failed":
        return True
    if output.get("asset_id") == "final-ad-video" and status != "ready":
        return True
    has_accessible_path = any(
        isinstance(output.get(key), str) and bool(str(output.get(key)).strip())
        for key in ("local_path", "public_url", "remote_url", "url")
    )
    return (
        status in {"waiting_for_segments", "not_started", "submitted"} and not has_accessible_path
    )


def _storyboard_order(scene: dict[str, Any], fallback: int) -> int:
    return _int_value(scene.get("order") or scene.get("shotIndex"), fallback)


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
