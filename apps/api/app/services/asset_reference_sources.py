import json
from pathlib import Path
from typing import Any

from app.services.media_paths import public_url_for_path, with_public_urls
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_asset_history import load_node_asset_history
from app.services.workflow_state import load_active_node_results


HIDDEN_CANVAS_NODE_IDS = {
    "requirements-analysis",
    "product-design",
    "creative-direction",
    "character-design",
    "scene-design",
}


def load_canvas_assets(
    data_dir: Path,
    workflow_id: str | None = None,
    *,
    include_uploaded_assets: bool = True,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    if workflow_id:
        assets.extend(_workflow_active_assets(data_dir, workflow_id))
        assets.extend(_workflow_history_assets(data_dir, workflow_id))
    if include_uploaded_assets:
        assets.extend(load_uploaded_canvas_assets(data_dir))
    return dedupe_output_assets([with_public_urls(asset) for asset in assets])


def load_uploaded_canvas_assets(data_dir: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for metadata_path in sorted((data_dir / "assets").glob("*/*/metadata.json")):
        payload = _read_json(metadata_path)
        if not isinstance(payload, dict):
            continue
        asset = dict(payload)
        asset.setdefault("asset_id", metadata_path.parent.name)
        asset.setdefault("source_type", "canvas_asset")
        asset.setdefault("source_node_id", "uploaded_assets")
        asset.setdefault("source", "uploaded_assets")
        asset.setdefault("scope", "project")
        asset.setdefault("semantic_type", _semantic_type_for_canvas_asset(asset))
        asset.setdefault("entity_type", "uploaded_reference")
        asset.setdefault("display_name", _display_name_for_canvas_asset(asset))
        assets.append(_with_canvas_asset_defaults(asset))
    return assets


def find_canvas_asset(
    data_dir: Path,
    asset_id: str,
    *,
    workflow_id: str | None = None,
) -> dict[str, Any] | None:
    for asset in load_canvas_assets(data_dir, workflow_id):
        if str(asset.get("asset_id") or "") == asset_id:
            return asset
    return None


def canvas_asset_entity_type(asset: dict[str, Any]) -> str:
    semantic_type = str(asset.get("semantic_type") or "")
    if semantic_type in {
        "character_main",
        "character_face_id",
        "character_three_view",
        "character_concept",
    }:
        return "character"
    if semantic_type in {"scene_main", "scene_multi_view"}:
        return "scene"
    if semantic_type in {"storyboard_image", "storyboard_video"}:
        return "storyboard_shot"
    if semantic_type == "bgm":
        return "bgm"
    if semantic_type == "final_video":
        return "video_clip"
    if semantic_type == "style_reference":
        return "style_reference"
    return str(asset.get("entity_type") or "uploaded_reference")


def canvas_asset_semantic_types(asset: dict[str, Any]) -> list[str]:
    semantic_type = str(asset.get("semantic_type") or "").strip()
    if semantic_type:
        return [semantic_type]
    role = str(asset.get("role") or asset.get("asset_role") or "").strip()
    return [role] if role else ["uploaded_reference"]


def canvas_asset_display_name(asset: dict[str, Any]) -> str:
    return _display_name_for_canvas_asset(asset)


def canvas_asset_uri(asset: dict[str, Any]) -> str | None:
    for key in ("uri", "public_url", "local_path", "remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def canvas_asset_preview(asset: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = str(asset.get("asset_id") or "")
    if not asset_id:
        return None
    return {
        "asset_id": asset_id,
        "uri": canvas_asset_uri(asset),
        "local_path": asset.get("local_path"),
        "public_url": asset.get("public_url")
        or public_url_for_path(str(asset.get("local_path") or "")),
        "mime_type": asset.get("mime_type"),
    }


def _workflow_active_assets(data_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for node_id, payload in load_active_node_results(data_dir, workflow_id).items():
        if _is_hidden_canvas_node(node_id):
            continue
        for asset in _assets_from_payload(payload):
            item = dict(asset)
            item.setdefault("workflow_id", workflow_id)
            item.setdefault("node_id", node_id)
            item.setdefault("source_node_id", node_id)
            item.setdefault("source", node_id)
            item.setdefault("scope", "workflow")
            item.setdefault("is_active", True)
            item.setdefault("semantic_type", _semantic_type_for_canvas_asset(item))
            item.setdefault("entity_type", canvas_asset_entity_type(item))
            item.setdefault("display_name", _display_name_for_canvas_asset(item))
            assets.append(_with_canvas_asset_defaults(item))
    return assets


def _workflow_history_assets(data_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    nodes_dir = data_dir / "workflows" / workflow_id / "nodes"
    if not nodes_dir.exists():
        return []
    assets: list[dict[str, Any]] = []
    for node_dir in sorted(path for path in nodes_dir.iterdir() if path.is_dir()):
        node_id = node_dir.name
        if _is_hidden_canvas_node(node_id):
            continue
        for asset in load_node_asset_history(data_dir, workflow_id, node_id):
            if asset.get("is_archived") is True:
                continue
            item = dict(asset)
            item.setdefault("workflow_id", workflow_id)
            item.setdefault("node_id", node_id)
            item.setdefault("source_node_id", node_id)
            item.setdefault("source", node_id)
            item.setdefault("scope", "workflow")
            item.setdefault("semantic_type", _semantic_type_for_canvas_asset(item))
            item.setdefault("entity_type", canvas_asset_entity_type(item))
            item.setdefault("display_name", _display_name_for_canvas_asset(item))
            assets.append(_with_canvas_asset_defaults(item))
    return assets


def _assets_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return legacy_output_assets_from_payload(payload)


def _with_canvas_asset_defaults(asset: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(
        asset.get("asset_type")
        or asset.get("type")
        or asset.get("media_type")
        or _asset_type_from_path(str(canvas_asset_uri(asset) or ""))
        or "reference"
    )
    local_path = asset.get("local_path")
    if not local_path and _is_local_uri(asset.get("uri")):
        local_path = asset.get("uri")
    return with_public_urls(
        {
            **asset,
            "asset_type": asset_type,
            "type": asset_type,
            "media_type": asset_type,
            "kind": asset_type,
            "local_path": local_path,
        }
    )


def _semantic_type_for_canvas_asset(asset: dict[str, Any]) -> str:
    for key in ("semantic_type", "role", "kind", "asset_role"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized == "reference":
                return "uploaded_reference"
            return normalized
    return "uploaded_reference"


def _display_name_for_canvas_asset(asset: dict[str, Any]) -> str:
    for key in ("display_name", "title", "name", "filename"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return _title_from_text(value)
    local_path = asset.get("local_path") or asset.get("uri") or asset.get("url")
    if isinstance(local_path, str) and local_path.strip():
        return _title_from_text(Path(local_path).name)
    asset_id = str(asset.get("asset_id") or "canvas asset")
    return _title_from_text(asset_id)


def _title_from_text(value: str) -> str:
    stem = Path(value).stem if "." in Path(value).name else value
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    return normalized.title() if normalized.islower() else normalized


def _asset_type_from_path(value: str) -> str:
    lowered = value.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if lowered.endswith((".mp4", ".mov", ".webm")):
        return "video"
    if lowered.endswith((".mp3", ".wav", ".aac", ".m4a")):
        return "audio"
    return ""


def _is_local_uri(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not value.startswith(("http://", "https://", "/media/"))
    )


def _is_hidden_canvas_node(node_id: str) -> bool:
    return node_id in HIDDEN_CANVAS_NODE_IDS


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
