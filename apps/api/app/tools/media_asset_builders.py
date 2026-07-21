from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.tools.media_response_parsing import (
    _video_duration_from_response,
    _video_ratio_from_response,
    _video_resolution_from_response,
)


def _url(endpoint: str, workflow_id: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/outputs/{workflow_id}/{path}"


def _storyboard_video_segment_asset(
    *,
    segment: dict[str, Any],
    workflow_id: str,
    provider: str,
    model: str,
    task_id: str,
    task_query_url: str,
    response: dict[str, Any],
    remote_url: str | None,
    resolution: str,
    ratio: str,
    download_result: dict[str, Any],
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    order = int(segment["order"])
    resolved_metadata_path = metadata_path or (
        Path("videos") / workflow_id / "segments" / f"segment-{order}.json"
    )
    actual_resolution = _video_resolution_from_response(response) or resolution
    actual_ratio = _video_ratio_from_response(response) or ratio
    actual_duration = _video_duration_from_response(response) or segment["duration_seconds"]
    warnings = []
    if actual_resolution != resolution:
        warnings.append(
            f"Requested resolution {resolution}, provider reported {actual_resolution}."
        )
    if actual_ratio != ratio:
        warnings.append(f"Requested ratio {ratio}, provider reported {actual_ratio}.")
    return {
        "provider": provider,
        "model": model,
        "asset_id": f"storyboard-video-segment-{order}",
        "asset_type": "video",
        "order": order,
        "entity_id": segment.get("shot_id") or segment.get("item_id") or f"shot_{order:03d}",
        "shot_id": segment.get("shot_id") or segment.get("item_id") or f"shot_{order:03d}",
        "scene_id": segment.get("scene_id") or f"scene-{order}",
        "primary_scene_id": segment.get("primary_scene_id") or segment.get("scene_id"),
        "scene_reference_ids": segment.get("scene_reference_ids", []),
        "character_ids": segment.get("character_ids", []),
        "product_reference_ids": segment.get("product_reference_ids", []),
        "style_reference_ids": segment.get("style_reference_ids", []),
        "no_scene_reason": segment.get("no_scene_reason"),
        "prompt": segment["prompt"],
        "duration_seconds": actual_duration,
        "task_id": task_id,
        "task_query_url": task_query_url,
        "url": remote_url,
        "remote_url": remote_url,
        "local_path": download_result.get("local_path"),
        "metadata_path": resolved_metadata_path.as_posix(),
        "status": response.get("status", "submitted"),
        "download_status": download_result.get("download_status"),
        "download_error": download_result.get("download_error"),
        "download_error_code": download_result.get("download_error_code"),
        "download_retryable": download_result.get("download_retryable"),
        "download_http_status": download_result.get("download_http_status"),
        "download_expected_bytes": download_result.get("download_expected_bytes"),
        "download_received_bytes": download_result.get("download_received_bytes"),
        "resolution": actual_resolution,
        "ratio": actual_ratio,
        "mime_type": "video/mp4",
        "source_assets": segment.get("source_assets") or segment.get("input_asset_ids", []),
        "input_asset_ids": segment.get("input_asset_ids", []),
        "input_assets": segment.get("input_assets", []),
        "source_storyboard_image": segment.get("source_storyboard_image"),
        "storyboard_asset_id": segment.get("storyboard_asset_id"),
        "source_scene_orders": segment.get("source_scene_orders", [order]),
        "warnings": warnings,
        "metadata": segment.get("metadata") if isinstance(segment.get("metadata"), dict) else {},
        "raw_response": response,
    }


# V1-only compatibility prompt builder. V2 must use canonical provider_prompt.
def _storyboard_image_prompt(scene: dict[str, Any]) -> str:
    input_asset_ids = (
        scene.get("input_asset_ids") if isinstance(scene.get("input_asset_ids"), list) else []
    )
    return (
        "Generate exactly one single full-frame storyboard keyframe for this one shot only. "
        "Do not create storyboard sheet, multi-panel layout, comic strip, collage, split screen, "
        "grid, before/after layout, contact sheet, numbered panel, title card, or multiple frames "
        "in one image. "
        "Do not render visible captions, shot labels, scene numbers, subtitles, UI text, or large "
        "typography in the image unless the scene explicitly requires product packaging/logo. "
        f"Scene order: {scene.get('order')}. "
        f"Shot id: {scene.get('shot_id') or scene.get('item_id') or ''}. "
        f"Primary scene id: {scene.get('primary_scene_id') or scene.get('scene_id') or ''}. "
        f"Scene reference ids: {', '.join(str(scene_id) for scene_id in scene.get('scene_reference_ids', []))}. "
        f"Character ids: {', '.join(str(character_id) for character_id in scene.get('character_ids', []))}. "
        f"Product reference ids: {', '.join(str(product_id) for product_id in scene.get('product_reference_ids', []))}. "
        f"Shot input_asset_ids: {', '.join(str(asset_id) for asset_id in input_asset_ids)}. "
        f"Shot: {scene.get('shot', '')}. "
        f"Visual: {scene.get('visual', '')}. "
        f"On-screen or spoken copy: {scene.get('text', '')}. "
        f"Camera: {scene.get('camera', '')}. "
        f"Action: {scene.get('action', '')}. "
        "Use the referenced scene only as environment/background reference. "
        "Include only characters listed by this shot's input_asset_ids. "
        "Keep product visible if required by the shot. "
        "Keep product packaging, colors, logo, shape, and proportions consistent. "
        "Keep character appearance, outfit, and body shape consistent. "
        "Keep scene spatial layout, lighting, and color tone consistent. "
        "保持产品包装、颜色、Logo、形状、比例一致；保持角色外貌、服装、体型一致；保持场景空间结构、光线、色调一致。 "
        "Clean commercial composition, clear product visibility, no unreadable text artifacts."
    )


def _storyboard_item_context(
    scene: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    item_context: dict[str, Any] = {
        "item_id": scene.get("item_id") or f"shot-{scene.get('order') or 1}",
        "item_type": "storyboard_image",
        "order": scene.get("order"),
        "shot_id": scene.get("shot_id") or scene.get("item_id"),
        "scene_id": scene.get("scene_id"),
        "primary_scene_id": scene.get("primary_scene_id"),
        "scene_reference_ids": scene.get("scene_reference_ids", []),
        "character_ids": scene.get("character_ids", []),
        "product_reference_ids": scene.get("product_reference_ids", []),
        "style_reference_ids": scene.get("style_reference_ids", []),
        "no_scene_reason": scene.get("no_scene_reason"),
        "input_asset_ids": scene.get("input_asset_ids", []),
    }
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        item_context["metadata"] = metadata
    reference_policy = context.get("reference_policy")
    if isinstance(reference_policy, dict):
        item_context["reference_policy"] = reference_policy
    reference_assets = context.get("reference_assets")
    if isinstance(reference_assets, list):
        item_context["reference_assets"] = _assets_for_storyboard_scene(
            scene,
            [asset for asset in reference_assets if isinstance(asset, dict)],
        )
    negative_prompt = context.get("negative_prompt")
    if isinstance(negative_prompt, str) and negative_prompt.strip():
        item_context["negative_prompt"] = negative_prompt
    return item_context


def _storyboard_image_asset(
    *,
    scene: dict[str, Any],
    workflow_id: str,
    prompt: str,
    provider: str,
    model: str,
    response: dict[str, Any],
    remote_url: str | None,
    download_result: dict[str, Any],
    input_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    order = int(scene["order"])
    metadata_path = Path("storyboards") / workflow_id / f"scene-{order}.json"
    return {
        "provider": provider,
        "model": model,
        "asset_id": f"storyboard-image-{order}",
        "asset_type": "image",
        "role": "storyboard",
        "scene": order,
        "order": order,
        "entity_id": scene.get("shot_id") or scene.get("item_id") or f"shot_{order:03d}",
        "shot_id": scene.get("shot_id") or scene.get("item_id") or f"shot_{order:03d}",
        "item_id": scene.get("shot_id") or scene.get("item_id") or f"shot_{order:03d}",
        "scene_id": scene.get("scene_id") or f"scene-{order}",
        "primary_scene_id": scene.get("primary_scene_id") or scene.get("scene_id"),
        "scene_reference_ids": scene.get("scene_reference_ids", []),
        "character_ids": scene.get("character_ids", []),
        "product_reference_ids": scene.get("product_reference_ids", []),
        "style_reference_ids": scene.get("style_reference_ids", []),
        "no_scene_reason": scene.get("no_scene_reason"),
        "input_asset_ids": scene.get("input_asset_ids", []),
        "prompt": prompt,
        "url": remote_url,
        "remote_url": remote_url,
        "local_path": download_result.get("local_path"),
        "metadata_path": metadata_path.as_posix(),
        "mime_type": "image/png",
        "status": response.get("status", "ready"),
        "download_status": download_result.get("download_status"),
        "download_error": download_result.get("download_error"),
        "input_assets": input_assets or [],
        "metadata": scene.get("metadata") if isinstance(scene.get("metadata"), dict) else {},
        "raw_response": response,
    }


def _image_generation_reference_inputs(input_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references = []
    for asset in input_assets:
        input_type = asset.get("model_input_type")
        input_value = asset.get("model_input_value")
        if input_type not in {
            "image_url",
            "data_url",
            "provider_file_id",
            "provider_uploaded_url",
        } or not isinstance(input_value, str):
            continue
        _validate_image_provider_reference(input_type, input_value)
        references.append(
            {
                "asset_id": asset.get("asset_id"),
                "role": asset.get("role"),
                "type": input_type,
                "value": input_value,
            }
        )
    return references


def _validate_image_provider_reference(input_type: Any, input_value: str) -> None:
    value = input_value.strip()
    if input_type == "provider_file_id":
        if value:
            return
        raise ValueError("v2_provider_reference_delivery_unsupported")
    if input_type == "data_url":
        if value.startswith("data:image/") and ";base64," in value:
            return
        raise ValueError("v2_provider_reference_delivery_unsupported")
    if input_type in {"image_url", "provider_uploaded_url"} and _is_external_https_url(value):
        return
    raise ValueError("v2_provider_reference_delivery_unsupported")


def _is_external_https_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname.lower() in {"localhost", "0.0.0.0"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def _assets_for_storyboard_scene(
    scene: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested_ids = scene.get("input_asset_ids")
    if isinstance(requested_ids, list) and requested_ids:
        return _assets_matching_ids(input_assets, [str(asset_id) for asset_id in requested_ids])

    fallback_ids = []
    scene_id = scene.get("scene_id")
    if isinstance(scene_id, str) and scene_id.strip():
        fallback_ids.append(_scene_reference_asset_id(scene_id))
    try:
        order = int(scene.get("order") or 0)
    except (TypeError, ValueError):
        order = 0
    if order:
        fallback_ids.append(f"scene-reference-{order}")
    product_ids = [
        str(asset.get("asset_id"))
        for asset in input_assets
        if asset.get("role") == "product_reference" and asset.get("asset_id")
    ]
    return _assets_matching_ids(input_assets, [*product_ids, *fallback_ids])


def _assets_matching_ids(
    input_assets: list[dict[str, Any]],
    asset_ids: list[str],
) -> list[dict[str, Any]]:
    requested = []
    seen: set[str] = set()
    for asset_id in asset_ids:
        normalized = str(asset_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        requested.append(normalized)
    requested_set = set(requested)
    return [
        asset for asset in input_assets if str(asset.get("asset_id") or "").strip() in requested_set
    ]


def _scene_reference_asset_id(scene_id: str) -> str:
    if scene_id.startswith("scene-reference-"):
        return scene_id
    suffix = scene_id.rsplit("-", 1)[-1]
    return f"scene-reference-{suffix}" if suffix.isdigit() else scene_id


def _scene_specs(scene_design: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = scene_design.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        return [
            {
                "location": "Brand-safe environment",
                "lighting": "Clean commercial lighting",
                "atmosphere": "Consistent advertising mood",
            }
        ]
    return [scene for scene in scenes if isinstance(scene, dict)]


# V1-only compatibility prompt builder. V2 must use canonical provider_prompt.
def _scene_reference_prompt(scene: dict[str, Any]) -> str:
    return (
        "Create a pure environment concept art reference image for an advertising video. "
        f"Location: {scene.get('location', '')}. "
        f"Lighting: {scene.get('lighting', '')}. "
        f"Atmosphere: {scene.get('atmosphere', '')}. "
        "Show only the environment, spatial layout, light, color palette, and mood. "
        "No people, no characters, no extra products, no text, no logos unless explicitly required by the scene."
    )


def _scene_reference_asset(
    *,
    workflow_id: str,
    index: int,
    scene: dict[str, Any],
    prompt: str,
    provider: str,
    model: str,
    response: dict[str, Any],
    remote_url: str | None,
    download_result: dict[str, Any],
) -> dict[str, Any]:
    metadata_path = Path("scenes") / workflow_id / f"scene-{index}.json"
    return {
        "provider": provider,
        "model": model,
        "asset_id": f"scene-reference-{index}",
        "asset_type": "image",
        "role": "scene_reference",
        "scene": index,
        "order": index,
        "scene_id": scene.get("scene_id") or f"scene-reference-{index}",
        "local_path": download_result.get("local_path"),
        "url": remote_url,
        "remote_url": remote_url,
        "metadata_path": metadata_path.as_posix(),
        "mime_type": "image/png",
        "prompt": prompt,
        "status": response.get("status", "ready"),
        "download_status": download_result.get("download_status"),
        "download_error": download_result.get("download_error"),
        "raw_response": response,
    }


def _product_specs(product_design: dict[str, Any]) -> list[dict[str, Any]]:
    products = product_design.get("products", [])
    if not isinstance(products, list) or not products:
        return [
            {
                "item_id": "product-1",
                "display_name": "Primary product hero image",
                "prompt": "Clean commercial hero product image.",
                "input_asset_ids": _asset_ids(product_design.get("reference_assets", [])),
                "reference_mode": "strict",
                "metadata": {
                    "product_reference_required": bool(
                        _asset_ids(product_design.get("reference_assets", []))
                    ),
                    "product_identity_locked": bool(
                        _asset_ids(product_design.get("reference_assets", []))
                    ),
                    "commercial_design_source": "director_context",
                },
            }
        ]
    return [product for product in products if isinstance(product, dict)]


def _product_image_prompt(product: dict[str, Any]) -> str:
    prompt = str(product.get("prompt") or product.get("productPrompt") or "").strip()
    if prompt:
        return prompt
    return (
        "Create a clean commercial product image. "
        f"Product: {product.get('display_name') or product.get('name') or 'Primary product'}. "
        "Preserve product packaging, logo, shape, material, colors, and proportions when "
        "references are provided. Use a brand-safe advertising composition."
    )


def _assets_for_product(
    product: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested_ids = product.get("input_asset_ids")
    if isinstance(requested_ids, list) and requested_ids:
        return _assets_matching_ids(input_assets, [str(asset_id) for asset_id in requested_ids])
    return [asset for asset in input_assets if asset.get("role") == "product_reference"]


def _asset_ids(assets: Any) -> list[str]:
    if not isinstance(assets, list):
        return []
    return [
        str(asset.get("asset_id"))
        for asset in assets
        if isinstance(asset, dict) and asset.get("asset_id")
    ]


def _product_item_context(
    product: dict[str, Any],
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "item_id": product.get("item_id") or product.get("product_id"),
        "item_type": "product_image",
        "reference_mode": product.get("reference_mode") or "strict",
        "input_asset_ids": product.get("input_asset_ids", []),
        "reference_assets": input_assets,
        "metadata": product.get("metadata") if isinstance(product.get("metadata"), dict) else {},
    }


def _product_image_asset(
    *,
    workflow_id: str,
    index: int,
    product: dict[str, Any],
    prompt: str,
    provider: str,
    model: str | None,
    response: dict[str, Any],
    remote_url: str | None,
    download_result: dict[str, Any],
    input_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item_id = str(
        product.get("item_id")
        or product.get("product_id")
        or product.get("entity_id")
        or f"product-{index}"
    )
    metadata_path = Path("products") / workflow_id / f"product-{index}.json"
    metadata = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
    return {
        "provider": provider,
        "model": model,
        "asset_id": f"product-image-{index}",
        "asset_type": "image",
        "type": "image",
        "media_type": "image",
        "kind": "image",
        "role": "product_image",
        "semantic_type": "product_image",
        "entity_id": item_id,
        "product_id": item_id,
        "display_name": str(product.get("display_name") or f"Product image {index}"),
        "order": int(product.get("order") or index),
        "input_asset_ids": product.get("input_asset_ids", []),
        "reference_mode": product.get("reference_mode") or "strict",
        "prompt": prompt,
        "url": remote_url,
        "remote_url": remote_url,
        "local_path": download_result.get("local_path"),
        "metadata_path": metadata_path.as_posix(),
        "mime_type": "image/png",
        "status": response.get("status", "ready"),
        "download_status": download_result.get("download_status"),
        "download_error": download_result.get("download_error"),
        "input_assets": input_assets or [],
        "metadata": {
            **metadata,
            "product_reference_required": bool(
                metadata.get("product_reference_required", product.get("input_asset_ids"))
            ),
            "product_identity_locked": bool(
                metadata.get("product_identity_locked", product.get("input_asset_ids"))
            ),
            "commercial_design_source": metadata.get(
                "commercial_design_source", "director_context"
            ),
        },
        "raw_response": response,
    }


def _real_audio_asset(
    endpoint: str,
    workflow_id: str,
    asset_id: str,
    model: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "provider": "volcengine-audio-generation",
        "model": model,
        "asset_id": asset_id,
        "audio_plan": plan,
        "url": _url(endpoint, workflow_id, f"audio/{asset_id}.wav"),
        "mime_type": "audio/wav",
        "status": "submitted",
    }


def _character_specs(character_design: dict[str, Any]) -> list[dict[str, Any]]:
    characters = character_design.get("characters", [])
    if not isinstance(characters, list) or not characters:
        return [
            {
                "name": "Main Character",
                "role": "Main character",
                "appearance": "Brand-aligned advertising character.",
                "personality": "Approachable and consistent.",
            }
        ]
    return [character for character in characters if isinstance(character, dict)]


# V1-only compatibility prompt builder. V2 must use canonical provider_prompt.
def _character_turnaround_prompt(character: dict[str, Any]) -> str:
    return (
        "Create a pure character design turnaround sheet with front view, side view, and back view. "
        "Do not include any complex scene, environment, props, or other people. "
        "Use a plain white or light gray design sheet background. "
        f"Character name: {character.get('name', 'Main Character')}. "
        f"Role: {character.get('role', 'Main character')}. "
        f"Appearance: {character.get('appearance', '')}. "
        f"Personality: {character.get('personality', '')}. "
        "Keep the same face shape, hairstyle, outfit, body type, age, and temperament across all "
        "three views. Clean neutral background, production reference sheet, no extra characters."
    )


def _character_turnaround_asset(
    *,
    workflow_id: str,
    index: int,
    character: dict[str, Any],
    prompt: str,
    provider: str,
    url: str | None,
    status: str,
    model: str | None = None,
) -> dict[str, Any]:
    character_id = f"character-{index}"
    base_path = Path("characters") / workflow_id / character_id
    intended_local_path = (base_path / "turnaround.png").as_posix()
    return {
        "provider": provider,
        "model": model,
        "asset_id": f"character-turnaround-{index}",
        "character_id": character_id,
        "character_name": str(character.get("name") or f"Character {index}"),
        "asset_type": "image",
        "role": "character_turnaround",
        "local_path": None,
        "intended_local_path": intended_local_path,
        "url": url,
        "remote_url": url,
        "mime_type": "image/png",
        "prompt": prompt,
        "views": ["front", "side", "back"],
        "status": status,
        "download_status": "waiting_for_remote_url" if url else "mock_not_downloaded",
        "metadata_path": (base_path / "metadata.json").as_posix(),
    }
