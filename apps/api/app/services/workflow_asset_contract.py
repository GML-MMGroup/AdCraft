from collections.abc import Mapping
from typing import Any

from app.services.canonical_assets import (
    AUDIO_SEMANTICS,
    IMAGE_SEMANTICS,
    VIDEO_SEMANTICS,
    canonical_media_type,
    normalize_canonical_asset,
)
from app.services.output_assets import dedupe_output_assets

CANONICAL_OUTPUT_ASSET_KEY = "output_assets"
LEGACY_ASSETS_ALIAS_KEY = "assets"
LEGACY_PROVIDER_OUTPUT_ASSET_CONTAINER_KEYS = (
    "assets",
    "output_assets",
    "segments",
    "final_video",
    "images",
    "videos",
    "audio",
    "generated_assets",
)
STRUCTURED_OUTPUT_ASSET_CONTAINER_KEYS = (
    "segments",
    "images",
    "videos",
    "audio",
    "generated_assets",
)
LEGACY_ACTIVE_OUTPUT_ASSET_CONTAINER_KEYS = (
    "output_assets",
    "assets",
    "segments",
    "final_video",
    "images",
    "videos",
    "audio",
    "generated_assets",
)
MEDIA_REFERENCE_KEYS = ("local_path", "public_url", "remote_url", "url", "uri")


def canonical_output_assets(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read only the canonical top-level output asset container."""
    value = payload.get(CANONICAL_OUTPUT_ASSET_KEY)
    if not isinstance(value, list):
        return []
    return dedupe_output_assets(
        [_normalize_contract_asset(asset) for asset in value if isinstance(asset, Mapping)]
    )


def legacy_output_assets_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compatibility boundary for old active/result JSON that predated top-level output_assets."""
    assets = canonical_output_assets(payload)
    output = payload.get("output")
    if isinstance(output, Mapping):
        assets.extend(extract_provider_output_assets(output))
    return dedupe_output_assets(assets)


def extract_provider_output_assets(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract assets from raw provider/output-contract input containers."""
    assets: list[dict[str, Any]] = []
    for key in LEGACY_PROVIDER_OUTPUT_ASSET_CONTAINER_KEYS:
        value = output.get(key)
        if key == "final_video" and isinstance(value, Mapping) and not _has_media_reference(value):
            continue
        assets.extend(_asset_dicts_from_container(value))
    if _looks_like_output_asset(output, allow_unavailable=False):
        assets.append(_normalize_contract_asset(output))
    return dedupe_output_assets(assets)


def normalize_node_output_assets(output: Mapping[str, Any]) -> dict[str, Any]:
    """Return a node output payload with canonical output_assets and derived legacy assets."""
    normalized = dict(output)
    output_assets = extract_provider_output_assets(normalized)
    normalized[CANONICAL_OUTPUT_ASSET_KEY] = output_assets
    normalized[LEGACY_ASSETS_ALIAS_KEY] = derive_legacy_assets_alias(output_assets)
    return normalized


def derive_legacy_assets_alias(output_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility alias for clients that still read output.assets."""
    return [dict(asset) for asset in dedupe_output_assets(output_assets)]


def _asset_dicts_from_container(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            _normalize_contract_asset(item)
            for item in value
            if isinstance(item, Mapping) and _looks_like_output_asset(item)
        ]
    if isinstance(value, Mapping) and _looks_like_output_asset(value):
        return [_normalize_contract_asset(value)]
    return []


def _normalize_contract_asset(asset: Mapping[str, Any]) -> dict[str, Any]:
    original = dict(asset)
    normalized = normalize_canonical_asset(asset)
    for key in ("semantic_type", "entity_type", "role"):
        if original.get(key) not in (None, ""):
            normalized[key] = original[key]
    if not original.get("semantic_type"):
        role_semantic = _semantic_type_from_role(original.get("role"))
        if role_semantic:
            normalized["semantic_type"] = role_semantic
    asset_id = _asset_identifier(normalized)
    if asset_id:
        normalized["asset_id"] = asset_id
    if not normalized.get("remote_url") and normalized.get("url"):
        normalized["remote_url"] = normalized.get("url")
    return normalized


def _looks_like_output_asset(
    value: Mapping[str, Any],
    *,
    allow_unavailable: bool = True,
) -> bool:
    if not allow_unavailable and _is_unavailable_single_asset_output(value):
        return False
    if not _asset_identifier(value):
        return False
    if _has_media_reference(value):
        return True
    media_type = canonical_media_type(value)
    return bool(media_type and str(value.get("asset_id") or "").strip())


def _asset_identifier(asset: Mapping[str, Any]) -> str:
    for key in (
        "asset_id",
        "segment_id",
        "id",
        "task_id",
        "local_path",
        "public_url",
        "remote_url",
        "url",
        "uri",
        "metadata_path",
    ):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_media_reference(asset: Mapping[str, Any]) -> bool:
    return any(
        isinstance(asset.get(key), str) and bool(str(asset.get(key)).strip())
        for key in MEDIA_REFERENCE_KEYS
    )


def _is_unavailable_single_asset_output(output: Mapping[str, Any]) -> bool:
    status = str(output.get("status") or "").lower()
    if status == "failed":
        return True
    if output.get("asset_id") == "final-ad-video" and status != "ready":
        return True
    if str(output.get("semantic_type") or "").lower() == "final_video" and status != "ready":
        return True
    return status in {
        "waiting_for_segments",
        "not_started",
        "submitted",
    } and not _has_media_reference(output)


def _semantic_type_from_role(value: Any) -> str:
    role = str(value or "").strip()
    if role in IMAGE_SEMANTICS or role in VIDEO_SEMANTICS or role in AUDIO_SEMANTICS:
        return role
    return ""
