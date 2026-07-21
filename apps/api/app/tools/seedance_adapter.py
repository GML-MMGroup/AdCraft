from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import quote, urlparse

from app.core.config import Settings
from app.schemas.ad_workflow import SUPPORTED_VIDEO_ASPECT_RATIOS, SUPPORTED_VIDEO_RESOLUTIONS

from app.tools.media_provider_protocol import (
    ARK_SEEDANCE_RESOLUTION,
    DEFAULT_VIDEO_RATIO,
    SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS,
    SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS,
    SEEDREAM_MIN_IMAGE_PIXELS,
    MediaConfigurationError,
)


class VolcengineSeedanceAdapter:
    """Translate generic video segment tasks into Ark Seedance task payloads."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def payload_for_segment(
        self,
        segment: dict[str, Any],
        ratio: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        prompt = str(segment.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("v2_video_prompt_empty")
        normalized_resolution = _normalize_video_resolution(
            resolution
            or segment.get("resolution")
            or segment.get("output_resolution")
            or self._settings.video_generation_resolution
        )
        normalized_ratio = _normalize_video_ratio(
            ratio or segment.get("ratio") or segment.get("aspect_ratio") or DEFAULT_VIDEO_RATIO
        )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt,
            }
        ]
        content.extend(_seedance_image_content_items(segment.get("input_assets", [])))
        return {
            "model": self._settings.video_generation_model,
            "content": content,
            "resolution": normalized_resolution,
            "ratio": normalized_ratio,
            "duration": segment["duration_seconds"],
            "generate_audio": bool(
                segment.get("generate_audio", self._settings.video_generation_generate_audio)
            ),
            "watermark": False,
            "camera_fixed": bool(segment.get("camera_fixed", False)),
        }

    def task_url(self, task_id: str) -> str:
        return _video_generation_task_url(
            self._settings.video_generation_endpoint or "",
            task_id,
        )


def _seedance_image_content_items(input_assets: Any) -> list[dict[str, Any]]:
    if not isinstance(input_assets, list):
        return []
    content_items = []
    for asset in input_assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("role") not in {
            "character_turnaround",
            "product_reference",
            "scene_reference",
            "storyboard",
        }:
            continue
        model_input_type = asset.get("model_input_type")
        image_url = (
            asset.get("model_input_value")
            if model_input_type in {"image_url", "data_url", "provider_uploaded_url"}
            else asset.get("url")
        )
        if not isinstance(image_url, str) or not image_url.strip():
            continue
        if not _is_seedance_compatible_image_input(image_url):
            raise ValueError("v2_provider_reference_url_invalid")
        content_items.append(
            {
                "type": "image_url",
                "role": "reference_image",
                "image_url": {
                    "url": image_url,
                },
            }
        )
    return content_items


def _is_seedance_compatible_image_input(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("data:image/") and ";base64," in stripped:
        return True
    parsed = urlparse(stripped)
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


def _normalize_video_resolution(value: Any) -> str:
    normalized = str(value or ARK_SEEDANCE_RESOLUTION).strip().lower()
    if normalized not in SUPPORTED_VIDEO_RESOLUTIONS:
        raise ValueError(
            "Unsupported video resolution. Supported values are: "
            f"{', '.join(sorted(SUPPORTED_VIDEO_RESOLUTIONS))}."
        )
    return normalized


def _normalize_video_ratio(value: Any) -> str:
    normalized = str(value or DEFAULT_VIDEO_RATIO).strip().replace("：", ":")
    if normalized not in SUPPORTED_VIDEO_ASPECT_RATIOS:
        raise ValueError(
            "Unsupported video aspect ratio. Supported values are: "
            f"{', '.join(sorted(SUPPORTED_VIDEO_ASPECT_RATIOS))}."
        )
    return normalized


def _normalize_image_generation_size(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.replace("X", "x").replace(" ", "").lower()
    parts = normalized.split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise MediaConfigurationError(
            "IMAGE_GENERATION_SIZE must be WxH with at least "
            f"{SEEDREAM_MIN_IMAGE_PIXELS} pixels; got {raw!r}."
        )

    width, height = (int(part) for part in parts)
    pixels = width * height
    if width <= 0 or height <= 0 or pixels < SEEDREAM_MIN_IMAGE_PIXELS:
        raise MediaConfigurationError(
            "IMAGE_GENERATION_SIZE must be WxH with at least "
            f"{SEEDREAM_MIN_IMAGE_PIXELS} pixels; got {raw!r} ({pixels} pixels)."
        )
    return f"{width}x{height}"


def _ark_seedance_video_task_payload(
    settings: Settings,
    final_video_prompt: dict[str, Any],
) -> dict[str, Any]:
    prompt = str(final_video_prompt.get("final_video_prompt") or "").strip()
    if not prompt:
        raise ValueError("Seedance video generation requires final_video_prompt.")

    return {
        "model": settings.video_generation_model,
        "content": [
            {
                "type": "text",
                "text": prompt,
            }
        ],
        "resolution": _normalize_video_resolution(
            final_video_prompt.get("output_resolution")
            or final_video_prompt.get("resolution")
            or settings.video_generation_resolution
        ),
        "ratio": _normalize_video_ratio(final_video_prompt.get("aspect_ratio")),
        "duration": _seedance_task_duration(final_video_prompt.get("duration_seconds")),
        "generate_audio": bool(final_video_prompt.get("generate_audio", False)),
        "watermark": False,
        "camera_fixed": bool(final_video_prompt.get("camera_fixed", False)),
    }


def _final_video_segments(final_video_prompt: dict[str, Any]) -> list[dict[str, Any]]:
    input_assets = [
        asset
        for asset in final_video_prompt.get("input_assets", [])
        if isinstance(asset, dict) and isinstance(asset.get("asset_id"), str)
    ]
    v2_segments = [
        segment for segment in final_video_prompt.get("segments", []) if isinstance(segment, dict)
    ]
    if v2_segments:
        return [
            _segment_from_v2_segment(segment, index, input_assets)
            for index, segment in enumerate(
                sorted(v2_segments, key=lambda value: int(value.get("order") or 0)),
                start=1,
            )
        ]

    total_duration = _integer_duration(final_video_prompt.get("duration_seconds"))
    scene_prompts = [
        scene
        for scene in final_video_prompt.get("scene_prompts", [])
        if isinstance(scene, dict) and str(scene.get("prompt") or "").strip()
    ]
    if _scene_prompts_are_valid_segments(scene_prompts, total_duration):
        return [
            _segment_from_scene_prompt(scene, index, input_assets)
            for index, scene in enumerate(scene_prompts, start=1)
        ]

    durations = _normalized_segment_durations(total_duration)
    return [
        _normalized_segment(
            final_video_prompt,
            scene_prompts,
            input_assets,
            order,
            duration,
            len(durations),
        )
        for order, duration in enumerate(durations, start=1)
    ]


def _scene_prompts_are_valid_segments(
    scene_prompts: list[dict[str, Any]],
    total_duration: int,
) -> bool:
    if not scene_prompts:
        return False
    durations = [
        _integer_duration(scene.get("duration_seconds"), allow_float=True)
        for scene in scene_prompts
    ]
    return (
        all(duration in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS for duration in durations)
        and sum(durations) == total_duration
    )


def _segment_from_scene_prompt(
    scene: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    segment_assets = _segment_input_assets(input_assets, scene.get("input_asset_ids", []))
    shot_id = str(scene.get("shot_id") or scene.get("item_id") or f"shot_{order:03d}")
    return {
        "order": order,
        "scene_id": scene.get("scene_id") or f"scene-{scene.get('order', order)}",
        "asset_id": f"storyboard-video-segment-{order}",
        "entity_id": shot_id,
        "shot_id": shot_id,
        "item_id": shot_id,
        "primary_scene_id": scene.get("primary_scene_id") or scene.get("scene_id"),
        "scene_reference_ids": scene.get("scene_reference_ids", []),
        "character_ids": scene.get("character_ids", []),
        "product_reference_ids": scene.get("product_reference_ids", []),
        "style_reference_ids": scene.get("style_reference_ids", []),
        "no_scene_reason": scene.get("no_scene_reason"),
        "prompt": str(scene["prompt"]).strip(),
        "duration_seconds": _seedance_task_duration(scene.get("duration_seconds")),
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "source_storyboard_image": scene.get("source_storyboard_image"),
        "storyboard_asset_id": scene.get("storyboard_asset_id"),
        "source_scene_orders": [scene.get("order", order)],
        "metadata": scene.get("metadata") if isinstance(scene.get("metadata"), dict) else {},
    }


def _segment_from_v2_segment(
    segment: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = str(segment.get("prompt") or segment.get("provider_prompt") or "").strip()
    input_asset_ids = _ordered_segment_asset_ids(
        segment.get("input_asset_ids"),
        segment.get("source_assets"),
        segment.get("source_asset_ids"),
    )
    segment_assets = _segment_input_assets(input_assets, input_asset_ids)
    shot_id = str(
        segment.get("shot_id")
        or segment.get("item_id")
        or segment.get("scene_id")
        or f"shot_{order:03d}"
    )
    return {
        **segment,
        "order": int(segment.get("order") or order),
        "scene_id": segment.get("scene_id") or shot_id,
        "asset_id": segment.get("asset_id") or f"storyboard-video-segment-{order}",
        "entity_id": segment.get("entity_id") or shot_id,
        "shot_id": shot_id,
        "item_id": segment.get("item_id") or shot_id,
        "prompt": prompt,
        "duration_seconds": _seedance_task_duration(segment.get("duration_seconds")),
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "metadata": segment.get("metadata") if isinstance(segment.get("metadata"), dict) else {},
    }


def _ordered_segment_asset_ids(*values: Any) -> list[str]:
    ordered: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        ordered.extend(str(asset_id) for asset_id in value if isinstance(asset_id, str))
    return list(dict.fromkeys(asset_id.strip() for asset_id in ordered if asset_id.strip()))


def _normalized_segment(
    final_video_prompt: dict[str, Any],
    scene_prompts: list[dict[str, Any]],
    input_assets: list[dict[str, Any]],
    order: int,
    duration: int,
    total_segments: int,
) -> dict[str, Any]:
    prompt = _normalized_segment_prompt(final_video_prompt, scene_prompts, order, total_segments)
    input_asset_ids = {
        asset_id
        for scene in scene_prompts
        for asset_id in scene.get("input_asset_ids", [])
        if isinstance(asset_id, str)
    }
    segment_assets = _segment_input_assets(input_assets, sorted(input_asset_ids))
    return {
        "order": order,
        "scene_id": f"scene-{order}",
        "asset_id": f"storyboard-video-segment-{order}",
        "prompt": prompt,
        "duration_seconds": duration,
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "source_scene_orders": _source_scene_orders(scene_prompts, order, total_segments),
    }


def _segment_input_assets(
    input_assets: list[dict[str, Any]],
    input_asset_ids: Any,
) -> list[dict[str, Any]]:
    requested_ids = (
        {asset_id for asset_id in input_asset_ids if isinstance(asset_id, str)}
        if isinstance(input_asset_ids, list)
        else set()
    )
    if requested_ids:
        return [
            asset
            for asset in input_assets
            if str(asset.get("asset_id") or "").strip() in requested_ids
        ]
    selected_assets = []
    seen_asset_ids = set()
    reusable_reference_roles = {
        "product_reference",
        "character_turnaround",
        "scene_reference",
        "storyboard",
    }
    for asset in input_assets:
        asset_id = asset["asset_id"]
        should_include = asset_id in requested_ids or asset.get("role") in reusable_reference_roles
        if should_include and asset_id not in seen_asset_ids:
            selected_assets.append(asset)
            seen_asset_ids.add(asset_id)
    return selected_assets


def _normalized_segment_prompt(
    final_video_prompt: dict[str, Any],
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> str:
    final_prompt = str(final_video_prompt.get("final_video_prompt") or "").strip()
    if len(scene_prompts) <= 1:
        return final_prompt

    selected_scenes = _scene_prompt_group(scene_prompts, order, total_segments)
    scene_text = " ".join(str(scene.get("prompt", "")).strip() for scene in selected_scenes)
    if not scene_text:
        return final_prompt
    return f"Segment {order}/{total_segments}. {scene_text}"


def _source_scene_orders(
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> list[Any]:
    return [
        scene.get("order")
        for scene in _scene_prompt_group(scene_prompts, order, total_segments)
        if scene.get("order") is not None
    ]


def _scene_prompt_group(
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> list[dict[str, Any]]:
    if not scene_prompts:
        return []
    start = (order - 1) * len(scene_prompts) // total_segments
    end = order * len(scene_prompts) // total_segments
    if end <= start:
        end = min(start + 1, len(scene_prompts))
    return scene_prompts[start:end]


def _normalized_segment_durations(total_duration: int) -> list[int]:
    if total_duration % 5 != 0:
        raise ValueError(
            "Cannot normalize final video duration into Seedance 5 or 10 second "
            f"segments: got {total_duration} seconds."
        )
    ten_second_count, remainder = divmod(total_duration, 10)
    durations = [10] * ten_second_count
    if remainder:
        durations.append(5)
    return durations


def _integer_duration(duration_seconds: Any, allow_float: bool = False) -> int:
    try:
        duration = float(duration_seconds) if allow_float else int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Video generation requires duration_seconds.") from exc
    if allow_float and not duration.is_integer():
        return int(duration)
    return int(duration)


def _seedance_task_duration(duration_seconds: Any) -> int:
    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seedance video generation requires an integer duration_seconds.") from exc

    if duration in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS:
        return duration
    if duration > SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS:
        raise ValueError(
            "Seedance single video generation supports 5 or 10 seconds per task; "
            f"got {duration} seconds. Split the workflow into multiple short video "
            "segments and compose them for longer ads."
        )
    raise ValueError(
        f"Seedance video generation duration must be 5 or 10 seconds; got {duration} seconds."
    )


def _video_generation_task_url(endpoint: str, task_id: str) -> str:
    safe_task_id = quote(task_id.strip(), safe="")
    return f"{endpoint.rstrip('/')}/{safe_task_id}"
