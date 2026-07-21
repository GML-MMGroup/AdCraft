from pathlib import Path
from typing import Any

from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.canonical_assets import canonical_media_type
from app.services.media_paths import public_url_for_path, with_public_urls
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_media_segments import load_workflow_segments, ready_segment_assets


def resolved_assets(
    node_type: str,
    active: dict[str, dict[str, Any]],
    graph: WorkflowGraph,
    graph_node: WorkflowGraphNode,
    data_dir: Path,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    if node_type == "final-composition":
        latest_segments = load_workflow_segments(data_dir, graph_node.workflow_id)
        for asset in ready_segment_assets(data_dir, latest_segments):
            append_asset(assets, seen, asset)
    for asset in selected_assets_for_node(node_type, graph):
        append_asset(assets, seen, normalize_asset(asset, "selected_assets"))
    for upstream_id in resolved_asset_upstream_ids(node_type, graph_node, graph):
        if node_type == "final-composition" and upstream_id == "storyboard-video-generation":
            continue
        active_payload = active.get(upstream_id, {})
        for asset in active_output_assets(active_payload):
            append_asset(assets, seen, normalize_asset(asset, upstream_id))
        if upstream_id == "bgm" and active_payload.get("output"):
            append_asset(assets, seen, bgm_asset(active_payload))
    for asset in graph_node.input_assets:
        append_asset(assets, seen, normalize_asset(asset, asset.get("source_node_id")))
    return with_public_urls(assets)


def resolved_asset_upstream_ids(
    node_type: str,
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
) -> list[str]:
    upstream_ids = asset_upstream_ids_from_edges(graph_node, graph)
    upstream_ids.extend(
        upstream_id
        for upstream_id in asset_upstream_ids(node_type)
        if upstream_id not in upstream_ids
    )
    return upstream_ids


def asset_upstream_ids_from_edges(
    graph_node: WorkflowGraphNode,
    graph: WorkflowGraph,
) -> list[str]:
    upstream_ids: list[str] = []
    for edge in graph.edges:
        if edge.target_node_id != graph_node.id:
            continue
        if edge.source_node_id and edge.source_node_id not in upstream_ids:
            upstream_ids.append(edge.source_node_id)
    return upstream_ids


def selected_assets_for_node(node_type: str, graph: WorkflowGraph) -> list[dict[str, Any]]:
    if node_type not in {"storyboard", "storyboard-video-generation"}:
        return []
    selected_assets = graph.ad_request.get("selected_assets")
    if not isinstance(selected_assets, list):
        return []
    assets = []
    for asset in selected_assets:
        if not isinstance(asset, dict):
            continue
        asset_copy = dict(asset)
        asset_copy["role"] = role_for_asset(asset_copy.get("asset_role") or asset_copy.get("role"))
        assets.append(asset_copy)
    return assets


def asset_upstream_ids(node_type: str) -> list[str]:
    upstream_map = {
        "storyboard": ["product-generation", "character-generation", "scene-generation"],
        "storyboard-video-generation": [
            "product-generation",
            "character-generation",
            "scene-generation",
            "storyboard",
        ],
        "final-composition": ["storyboard-video-generation", "bgm"],
    }
    return upstream_map.get(node_type, [])


def active_output_assets(active_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return legacy_output_assets_from_payload(active_payload)


def normalize_asset(asset: dict[str, Any], source_node_id: Any) -> dict[str, Any]:
    normalized = dict(asset)
    role = normalized.get("role") or normalized.get("asset_role") or role_for_asset(None)
    asset_type = canonical_media_type(normalized)
    mime_type = normalized.get("mime_type")
    local_path = normalized.get("local_path")
    public_url = normalized.get("public_url")
    remote_url = normalized.get("remote_url") or normalized.get("url")
    if not asset_type:
        asset_type = asset_type_from_mime_or_path(mime_type, local_path, remote_url or public_url)
    asset_type = str(asset_type or "reference")
    asset_id = (
        normalized.get("asset_id")
        or normalized.get("segment_id")
        or normalized.get("id")
        or normalized.get("task_id")
        or local_path
        or public_url
        or remote_url
    )
    if asset_id:
        normalized["asset_id"] = str(asset_id)
    normalized["role"] = role_for_asset(role)
    normalized["type"] = asset_type
    normalized["asset_type"] = asset_type
    normalized["kind"] = normalized.get("kind") or asset_type
    normalized["media_type"] = normalized.get("media_type") or asset_type
    normalized["source_node_id"] = (
        str(source_node_id)
        if source_node_id
        else str(normalized.get("source_node_id") or normalized.get("source") or "")
    )
    normalized["source"] = normalized.get("source") or normalized["source_node_id"]
    normalized["remote_url"] = remote_url
    normalized["public_url"] = public_url or public_url_for_path(normalized.get("local_path"))
    normalized["mime_type"] = mime_type or mime_type_for_asset_type(asset_type)
    normalized["filename"] = normalized.get("filename") or filename_from_asset(normalized)
    normalized["title"] = (
        normalized.get("title") or normalized.get("filename") or normalized.get("asset_id")
    )
    normalized["purpose"] = normalized.get("purpose") or normalized["role"]
    if not isinstance(normalized.get("metadata"), dict):
        normalized["metadata"] = {}
    normalized["prompt_usable"] = bool(
        normalized.get("prompt_usable", normalized.get("use_as_prompt", True))
    )
    normalized["use_as_prompt"] = bool(normalized.get("use_as_prompt", normalized["prompt_usable"]))
    return normalized


def filename_from_asset(asset: dict[str, Any]) -> str | None:
    for key in ("local_path", "public_url", "remote_url", "url"):
        value = asset.get(key)
        if not value:
            continue
        filename = str(value).rstrip("/").split("/")[-1]
        if filename:
            return filename
    return None


def append_asset(
    assets: list[dict[str, Any]],
    seen: set[str],
    asset: dict[str, Any],
) -> None:
    dedupe_key = asset_dedupe_key(asset)
    if dedupe_key and dedupe_key in seen:
        return
    if dedupe_key:
        seen.add(dedupe_key)
    assets.append(asset)


def asset_dedupe_key(asset: dict[str, Any]) -> str | None:
    for key in ("asset_id", "local_path", "public_url", "remote_url"):
        value = asset.get(key)
        if value:
            return f"{key}:{value}"
    return None


def merge_assets(
    existing_assets: list[dict[str, Any]],
    incoming_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in existing_assets:
        append_asset(merged, seen, asset)
    for asset in incoming_assets:
        append_asset(merged, seen, asset)
    return with_public_urls(merged)


def bgm_asset(active_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": "bgm-plan",
        "role": "audio",
        "asset_type": "audio",
        "type": "audio",
        "source_node_id": "bgm",
        "mime_type": "application/json",
        "metadata_path": active_payload.get("metadata_path") or active_payload.get("trace_path"),
        "status": active_payload.get("status", "completed"),
        "prompt_usable": True,
        "use_as_prompt": True,
    }


def role_for_asset(asset_role: Any) -> str:
    if asset_role == "product_image":
        return "product_image"
    if asset_role in {"product", "product_reference"}:
        return "product_reference"
    if asset_role in {"character", "character_reference"}:
        return "character_reference"
    if asset_role == "character_turnaround":
        return "character_turnaround"
    if asset_role in {"scene", "scene_reference"}:
        return "scene_reference"
    if asset_role in {"storyboard", "storyboard_image"}:
        return "storyboard"
    if asset_role in {"video", "video_segment"}:
        return "video_segment"
    if asset_role in {"audio", "bgm"}:
        return "audio"
    return "reference"


def asset_type_from_mime_or_path(
    mime_type: Any,
    local_path: Any,
    remote_url: Any,
) -> str:
    values = [str(value or "").lower().strip() for value in (mime_type, local_path, remote_url)]
    text = " ".join(values)
    if "audio" in text or any(value.endswith((".mp3", ".wav", ".aac", ".m4a")) for value in values):
        return "audio"
    if "video" in text or any(value.endswith((".mp4", ".mov", ".webm")) for value in values):
        return "video"
    if "image" in text or any(
        value.endswith((".png", ".jpg", ".jpeg", ".webp")) for value in values
    ):
        return "image"
    return "reference"


def mime_type_for_asset_type(asset_type: str) -> str:
    if asset_type == "image":
        return "image/png"
    if asset_type == "video":
        return "video/mp4"
    if asset_type == "audio":
        return "audio/mpeg"
    return "application/octet-stream"
