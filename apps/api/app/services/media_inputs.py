import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.schemas.assets import WorkflowAssetReference

MODEL_INPUT_ROLES = {
    "product_reference",
    "character_turnaround",
    "scene_reference",
    "storyboard",
}


def role_for_workflow_asset(asset_role: str | None) -> str:
    if asset_role == "product":
        return "product_reference"
    if asset_role == "character":
        return "character_turnaround"
    if asset_role == "scene":
        return "scene_reference"
    return "product_reference" if asset_role == "reference" else str(asset_role or "reference")


class MediaInputConverter:
    def __init__(
        self,
        data_dir: Path,
        *,
        url_validator: Callable[[str], bool] | None = None,
        supports_data_url: bool = True,
    ) -> None:
        self._data_dir = data_dir
        self._url_validator = url_validator or _url_is_reachable
        self._supports_data_url = supports_data_url

    def convert_many(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.convert(asset) for asset in assets]

    def convert(self, asset: WorkflowAssetReference | dict[str, Any]) -> dict[str, Any]:
        raw_asset = asset.model_dump() if isinstance(asset, WorkflowAssetReference) else asset
        role = _normalized_role(raw_asset)
        remote_url = _remote_url(raw_asset)
        local_path = raw_asset.get("local_path")
        source_node = raw_asset.get("source_node") or raw_asset.get("source")
        base = {
            "asset_id": raw_asset.get("asset_id"),
            "asset_type": raw_asset.get("asset_type") or "image",
            "role": role,
            "local_path": local_path,
            "remote_url": remote_url,
            "url": remote_url,
            "mime_type": raw_asset.get("mime_type") or "image/png",
            "source": raw_asset.get("source") or source_node or "unknown",
            "source_node": source_node,
            "download_status": raw_asset.get("download_status"),
        }
        for key in (
            "source_type",
            "source_node_id",
            "entity_id",
            "entity_type",
            "semantic_type",
            "display_name",
            "is_primary",
            "reference_mode",
            "use_as_prompt",
            "lock_identity",
            "allow_style_transfer",
        ):
            if key in raw_asset:
                base[key] = raw_asset.get(key)

        if isinstance(remote_url, str) and remote_url.strip():
            if self._url_validator(remote_url):
                return {
                    **base,
                    "model_input_type": "image_url",
                    "model_input_value": remote_url,
                    "conversion_status": "ready",
                }
            base["conversion_warning"] = "remote_url_unreachable"

        if isinstance(local_path, str) and local_path.strip():
            resolved_path = self._resolve_local_path(local_path)
            if resolved_path.exists() and self._supports_data_url:
                return {
                    **base,
                    "model_input_type": "data_url",
                    "model_input_value": _data_url(resolved_path, str(base["mime_type"])),
                    "conversion_status": "ready",
                }
            if resolved_path.exists():
                return {
                    **base,
                    "model_input_type": "local_file",
                    "model_input_value": resolved_path.as_posix(),
                    "conversion_status": "unavailable",
                    "conversion_error": "model_does_not_support_local_file_input",
                }
            base["conversion_warning"] = "local_path_missing"

        return {
            **base,
            "model_input_type": "unavailable",
            "model_input_value": None,
            "conversion_status": "unavailable",
            "conversion_error": "no_reachable_remote_url_or_local_file",
        }

    def _resolve_local_path(self, local_path: str) -> Path:
        path = Path(local_path)
        return path if path.is_absolute() else self._data_dir / path


def convert_assets_for_model_input(
    data_dir: Path, assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return MediaInputConverter(data_dir).convert_many(assets)


def _normalized_role(asset: dict[str, Any]) -> str:
    role = asset.get("role")
    if isinstance(role, str) and role in MODEL_INPUT_ROLES:
        return role
    asset_role = asset.get("asset_role")
    return role_for_workflow_asset(str(asset_role)) if asset_role else str(role or "reference")


def _remote_url(asset: dict[str, Any]) -> str | None:
    for key in ("remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _data_url(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _url_is_reachable(url: str) -> bool:
    request = urllib_request.Request(url, method="HEAD")
    try:
        with urllib_request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 400
    except urllib_error.HTTPError as exc:
        if exc.code == 405:
            return _get_url_is_reachable(url)
        return False
    except Exception:
        return False


def _get_url_is_reachable(url: str) -> bool:
    request = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 400
    except Exception:
        return False
