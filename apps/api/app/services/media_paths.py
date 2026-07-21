from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.services.workflow_asset_contract import extract_provider_output_assets

PUBLIC_MEDIA_PREFIX = "/media"


def public_url_for_path(local_path: str | None, prefix: str = PUBLIC_MEDIA_PREFIX) -> str | None:
    if not local_path:
        return None
    normalized = str(local_path).replace("\\", "/").lstrip("/")
    if not normalized:
        return None
    return f"{prefix.rstrip('/')}/{quote(normalized, safe='/._-')}"


def with_public_urls(value: Any, prefix: str = PUBLIC_MEDIA_PREFIX) -> Any:
    if isinstance(value, list):
        return [with_public_urls(item, prefix) for item in value]
    if not isinstance(value, dict):
        return value

    enriched = {key: with_public_urls(item, prefix) for key, item in value.items()}
    local_path = enriched.get("local_path")
    if isinstance(local_path, str) and local_path.strip():
        enriched.setdefault("public_url", public_url_for_path(local_path, prefix))
    elif "local_path" in enriched:
        enriched.setdefault("public_url", None)

    metadata_path = enriched.get("metadata_path")
    if isinstance(metadata_path, str) and metadata_path.strip():
        enriched.setdefault("metadata_public_url", public_url_for_path(metadata_path, prefix))
    return enriched


def output_assets_from_content(content: dict[str, Any]) -> list[dict[str, Any]]:
    assets = extract_provider_output_assets(content)
    if not assets and content.get("asset_id"):
        assets = [dict(content)]
    return [with_public_urls(asset) for asset in assets]


def input_assets_from_content(content: dict[str, Any]) -> list[dict[str, Any]]:
    value = content.get("input_assets")
    if isinstance(value, list):
        return [with_public_urls(asset) for asset in value if isinstance(asset, dict)]
    return []


def relative_path_exists(data_dir: Path, local_path: str | None) -> bool:
    return bool(local_path) and (data_dir / str(local_path)).exists()
