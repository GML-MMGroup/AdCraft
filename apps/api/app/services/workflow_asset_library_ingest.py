from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.agent_trace import utc_now
from app.services.workflow_asset_history import load_node_asset_history, write_node_asset_history
from app.services.workflow_asset_prompts import asset_slot_id


class WorkflowAssetLibraryIngestService:
    def __init__(self, data_dir: Path, events: Any | None = None) -> None:
        self._data_dir = data_dir
        self._events = events

    def ingest_ready_assets(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        item_id: str,
        assets: list[dict[str, Any]],
        version_id: str | None,
        workflow_selection_state: str,
    ) -> list[dict[str, Any]]:
        ready_assets = [asset for asset in assets if _asset_has_ready_media(self._data_dir, asset)]
        if not ready_assets:
            return assets
        entity_id = _stable_library_entity_id(workflow_id, node_id, item_id)
        now = utc_now().isoformat()
        entity = self._load_entity(entity_id) or {
            "entity_id": entity_id,
            "entity_type": _entity_type_for_node(node_type),
            "display_name": _display_name(item_id, node_type),
            "description": "",
            "tags": [],
            "source": {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "entity_id": item_id,
                "run_id": version_id,
            },
            "asset_ids": [],
            "reuse_policy": {
                "use_as_prompt": True,
                "lock_identity": node_type == "character-generation",
                "allow_style_transfer": True,
            },
            "is_archived": False,
            "created_at": now,
            "updated_at": now,
            "metadata": {
                "created_from": "workflow_generated_media",
                "idempotency_key": _stable_key(workflow_id, node_id, item_id),
            },
        }
        created_entity = not self._entity_path(entity_id).exists()
        linked_assets: list[dict[str, Any]] = []
        for asset in ready_assets:
            library_asset_id = _stable_library_asset_id(
                workflow_id,
                node_id,
                item_id,
                asset_slot_id(asset),
                version_id,
                str(asset.get("asset_id") or ""),
            )
            if library_asset_id not in entity["asset_ids"]:
                entity["asset_ids"].append(library_asset_id)
            self._write_asset(
                library_asset_id,
                entity_id=entity_id,
                entity_type=entity["entity_type"],
                workflow_asset=asset,
                created_at=now,
                workflow_selection_state=workflow_selection_state,
            )
            linked = {
                **asset,
                "library_state": "linked",
                "library_entity_id": entity_id,
                "library_asset_id": library_asset_id,
                "library_suggested": False,
                "workflow_selection_state": workflow_selection_state,
            }
            linked_assets.append(linked)
            self._append_event(
                workflow_id,
                "asset_library_asset_linked",
                node_id=node_id,
                node_type=node_type,
                resource_id=str(asset.get("asset_id") or ""),
                payload={
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "node_type": node_type,
                    "item_id": item_id,
                    "asset_id": asset.get("asset_id"),
                    "asset_slot_id": asset_slot_id(asset),
                    "library_entity_id": entity_id,
                    "library_asset_id": library_asset_id,
                    "refresh": ["asset_library", "workflow_nodes"],
                },
            )
        entity["updated_at"] = now
        self._write_entity(entity)
        self._upsert_index(entity)
        self._sync_history(
            workflow_id=workflow_id,
            node_id=node_id,
            linked_assets=linked_assets,
        )
        self._append_event(
            workflow_id,
            "asset_library_entity_created" if created_entity else "asset_library_entity_linked",
            node_id=node_id,
            node_type=node_type,
            resource_id=entity_id,
            payload={
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": node_type,
                "item_id": item_id,
                "library_entity_id": entity_id,
                "library_asset_ids": [asset["library_asset_id"] for asset in linked_assets],
                "refresh": ["asset_library"],
            },
        )
        linked_by_id = {str(asset.get("asset_id") or ""): asset for asset in linked_assets}
        return [
            {**asset, **linked_by_id.get(str(asset.get("asset_id") or ""), {})} for asset in assets
        ]

    def _sync_history(
        self,
        *,
        workflow_id: str,
        node_id: str,
        linked_assets: list[dict[str, Any]],
    ) -> None:
        history = load_node_asset_history(self._data_dir, workflow_id, node_id)
        linked_by_id = {str(asset.get("asset_id") or ""): asset for asset in linked_assets}
        updated = []
        for asset in history:
            updated.append({**asset, **linked_by_id.get(str(asset.get("asset_id") or ""), {})})
        write_node_asset_history(self._data_dir, workflow_id, node_id, updated)

    def _write_entity(self, entity: dict[str, Any]) -> None:
        _write_json_atomic(self._entity_path(str(entity["entity_id"])), entity)

    def _write_asset(
        self,
        asset_id: str,
        *,
        entity_id: str,
        entity_type: str,
        workflow_asset: dict[str, Any],
        created_at: str,
        workflow_selection_state: str,
    ) -> None:
        media_type = _media_type(workflow_asset)
        payload = {
            "asset_id": asset_id,
            "entity_id": entity_id,
            "asset_type": media_type,
            "media_type": media_type,
            "type": media_type,
            "kind": media_type,
            "semantic_type": str(workflow_asset.get("semantic_type") or ""),
            "uri": _asset_uri(workflow_asset),
            "mime_type": workflow_asset.get("mime_type"),
            "width": workflow_asset.get("width"),
            "height": workflow_asset.get("height"),
            "duration_seconds": workflow_asset.get("duration_seconds"),
            "source": {
                "workflow_id": workflow_asset.get("workflow_id"),
                "node_id": workflow_asset.get("node_id") or workflow_asset.get("source_node_id"),
                "asset_id": workflow_asset.get("asset_id"),
                "run_id": workflow_asset.get("run_id"),
                "entity_id": workflow_asset.get("entity_id") or workflow_asset.get("item_id"),
                "asset_slot_id": asset_slot_id(workflow_asset),
            },
            "is_archived": bool(workflow_asset.get("is_archived", False)),
            "created_at": created_at,
            "metadata": {
                **(
                    workflow_asset.get("metadata")
                    if isinstance(workflow_asset.get("metadata"), dict)
                    else {}
                ),
                "quality_status": workflow_asset.get("quality_status"),
                "quality_issues": workflow_asset.get("quality_issues") or [],
                "workflow_selection_state": workflow_selection_state,
                "entity_type": entity_type,
            },
        }
        _write_json_atomic(self._asset_path(asset_id), payload)

    def _upsert_index(self, entity: dict[str, Any]) -> None:
        path = self._data_dir / "asset_library" / "index.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {"entities": []}
        entities = [item for item in payload.get("entities", []) if isinstance(item, dict)]
        summary = {
            "entity_id": entity["entity_id"],
            "entity_type": entity["entity_type"],
            "display_name": entity["display_name"],
            "tags": entity.get("tags", []),
            "asset_ids": entity.get("asset_ids", []),
            "source_workflow_id": entity.get("source", {}).get("workflow_id"),
            "is_archived": bool(entity.get("is_archived", False)),
            "updated_at": entity["updated_at"],
        }
        entities = [item for item in entities if item.get("entity_id") != entity["entity_id"]]
        entities.append(summary)
        _write_json_atomic(path, {"entities": entities})

    def _load_entity(self, entity_id: str) -> dict[str, Any] | None:
        path = self._entity_path(entity_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def _entity_path(self, entity_id: str) -> Path:
        return self._data_dir / "asset_library" / "entities" / f"{entity_id}.json"

    def _asset_path(self, asset_id: str) -> Path:
        return self._data_dir / "asset_library" / "assets" / f"{asset_id}.json"

    def _append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        node_id: str,
        node_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self._events is None:
            return
        self._events.append_event(
            workflow_id,
            event_type,
            node_id=node_id,
            node_type=node_type,
            resource_type="asset_library",
            resource_id=resource_id,
            payload=payload,
        )


def _asset_has_ready_media(data_dir: Path, asset: dict[str, Any]) -> bool:
    local_path = asset.get("local_path") or asset.get("uri")
    if not isinstance(local_path, str) or not local_path.strip():
        return False
    if local_path.startswith(("http://", "https://", "/media/")):
        return True
    return (data_dir / local_path).exists()


def _entity_type_for_node(node_type: str) -> str:
    return {
        "product-generation": "product",
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard_shot",
        "storyboard-video-generation": "video_clip",
        "bgm": "bgm",
        "final-composition": "video_clip",
    }.get(node_type, "style_reference")


def _display_name(item_id: str, node_type: str) -> str:
    return f"{_entity_type_for_node(node_type).replace('_', ' ').title()} {item_id}"


def _media_type(asset: dict[str, Any]) -> str:
    for key in ("media_type", "asset_type", "type", "kind"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "video" if str(asset.get("semantic_type") or "").endswith("video") else "image"


def _asset_uri(asset: dict[str, Any]) -> str:
    for key in ("uri", "local_path", "public_url", "remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _stable_library_entity_id(workflow_id: str, node_id: str, item_id: str) -> str:
    return f"lib_ent_{_stable_key(workflow_id, node_id, item_id)[:12]}"


def _stable_library_asset_id(
    workflow_id: str,
    node_id: str,
    item_id: str,
    slot_id: str,
    version_id: str | None,
    asset_id: str,
) -> str:
    return f"lib_asset_{_stable_key(workflow_id, node_id, item_id, slot_id, version_id, asset_id)[:12]}"


def _stable_key(*parts: object) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
