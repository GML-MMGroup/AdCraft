import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas.workflow_v2 import (
    WorkflowAssetRelationTypeV2,
    WorkflowAssetRelationV2,
    WorkflowAssetVersionV2,
)
from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import (
    validate_v2_data_path,
    validate_v2_relative_path,
)


ASSET_STORE_DIRS = (
    "originals",
    "generated",
    "thumbnails",
    "proxies",
    "renditions",
    "metadata",
)


class V2AssetStoreService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._asset_root = data_dir / "assets"

    def ensure_directories(self) -> None:
        for directory in ASSET_STORE_DIRS:
            validate_v2_data_path(
                self._data_dir,
                self._asset_root / directory,
                operation="v2-asset-store-ensure-directories",
            ).mkdir(parents=True, exist_ok=True)

    def save_asset_version(self, record: WorkflowAssetVersionV2) -> WorkflowAssetVersionV2:
        self.ensure_directories()
        if record.created_at is None:
            record = record.model_copy(update={"created_at": utc_now().isoformat()})
        validate_v2_relative_path(record.file_path, operation="v2-save-asset-version")
        path = self._asset_metadata_path(record.asset_id, record.version_id)
        validate_v2_data_path(self._data_dir, path, operation="v2-save-asset-version")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record

    def register_external_asset(
        self,
        asset: dict[str, Any],
        *,
        workflow_id: str,
        node_id: str,
        item_id: str,
        semantic_type: str,
        source_type: str | None = None,
    ) -> WorkflowAssetVersionV2:
        self.ensure_directories()
        asset_id = _first_string(asset, "asset_id") or f"asset_{uuid4().hex[:12]}"
        version_id = _first_string(asset, "version_id", "v2_version_id") or f"ver_{asset_id}"
        existing = self.load_asset_version(asset_id, version_id) or self.find_asset_version(
            asset_id=asset_id
        )
        if existing is not None:
            return existing
        file_path = _external_file_path(self._data_dir, asset_id, asset)
        validate_v2_relative_path(file_path, operation="v2-register-external-asset")
        resolved_source_type = source_type or _external_source_type(file_path)
        record = WorkflowAssetVersionV2(
            asset_id=asset_id,
            version_id=version_id,
            media_type=_media_type(asset),
            source_type=resolved_source_type,
            file_path=file_path,
            public_url=_first_string(asset, "public_url", "url") or f"/media/{file_path}",
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            slot_id=None,
            semantic_type=semantic_type,
            created_by="v2-prompt-to-workflow",
            metadata={
                "original_filename": _first_string(asset, "filename", "display_name"),
                "content_type": _first_string(asset, "mime_type", "content_type"),
                "display_name": _first_string(asset, "display_name", "filename"),
                "source_asset": asset,
            },
        )
        return self.save_asset_version(record)

    def load_asset_version(
        self,
        asset_id: str,
        version_id: str,
    ) -> WorkflowAssetVersionV2 | None:
        path = self._asset_metadata_path(asset_id, version_id)
        if not path.exists():
            return None
        return WorkflowAssetVersionV2.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def find_asset_version(
        self,
        *,
        slot_id: str | None = None,
        version_id: str | None = None,
        asset_id: str | None = None,
    ) -> WorkflowAssetVersionV2 | None:
        metadata_root = self._asset_root / "metadata"
        if not metadata_root.exists():
            return None
        if asset_id and version_id:
            return self.load_asset_version(asset_id, version_id)
        for path in sorted(metadata_root.glob("*/*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if slot_id is not None and payload.get("slot_id") != slot_id:
                continue
            if version_id is not None and payload.get("version_id") != version_id:
                continue
            if asset_id is not None and payload.get("asset_id") != asset_id:
                continue
            return WorkflowAssetVersionV2.model_validate(payload)
        return None

    def asset_exists(self, asset_id: str) -> bool:
        metadata_root = self._asset_root / "metadata" / asset_id
        if not metadata_root.exists():
            return False
        for path in metadata_root.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            file_path = payload.get("file_path")
            if isinstance(file_path, str) and (self._data_dir / file_path).exists():
                return True
        return False

    def save_relation(
        self,
        relation: WorkflowAssetRelationV2,
    ) -> WorkflowAssetRelationV2:
        self.ensure_directories()
        path = self._relation_metadata_path(relation.relation_id)
        validate_v2_data_path(self._data_dir, path, operation="v2-save-asset-relation")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(relation.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return relation

    def load_relation(self, relation_id: str) -> WorkflowAssetRelationV2 | None:
        path = self._relation_metadata_path(relation_id)
        if not path.exists():
            return None
        return WorkflowAssetRelationV2.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def delete_relation(self, relation_id: str) -> WorkflowAssetRelationV2 | None:
        relation = self.load_relation(relation_id)
        if relation is None:
            return None
        self._relation_metadata_path(relation_id).unlink(missing_ok=True)
        return relation

    def list_relations(
        self,
        *,
        target_workflow_id: str | None = None,
        target_slot_id: str | None = None,
        source_asset_id: str | None = None,
        relation_type: WorkflowAssetRelationTypeV2 | None = None,
    ) -> list[WorkflowAssetRelationV2]:
        relations_root = self._asset_root / "metadata" / "relations"
        if not relations_root.exists():
            return []
        relations: list[WorkflowAssetRelationV2] = []
        for path in sorted(relations_root.glob("*.json")):
            relation = WorkflowAssetRelationV2.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if target_workflow_id is not None and relation.target_workflow_id != target_workflow_id:
                continue
            if target_slot_id is not None and relation.target_slot_id != target_slot_id:
                continue
            if source_asset_id is not None and relation.source_asset_id != source_asset_id:
                continue
            if relation_type is not None and relation.relation_type != relation_type:
                continue
            relations.append(relation)
        return relations

    def delete_slot_relations(
        self,
        *,
        target_workflow_id: str,
        target_slot_id: str,
        relation_type: WorkflowAssetRelationTypeV2,
        keep_relation_id: str | None = None,
    ) -> list[WorkflowAssetRelationV2]:
        deleted: list[WorkflowAssetRelationV2] = []
        relations = self.list_relations(
            target_workflow_id=target_workflow_id,
            target_slot_id=target_slot_id,
            relation_type=relation_type,
        )
        for relation in relations:
            if relation.relation_id == keep_relation_id:
                continue
            removed = self.delete_relation(relation.relation_id)
            if removed is not None:
                deleted.append(removed)
        return deleted

    def create_relation(
        self,
        *,
        relation_type: WorkflowAssetRelationTypeV2,
        source_asset_id: str,
        target_workflow_id: str | None = None,
        target_node_id: str | None = None,
        target_item_id: str | None = None,
        target_slot_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WorkflowAssetRelationV2:
        relation = WorkflowAssetRelationV2(
            relation_id=f"rel_{uuid4().hex}",
            relation_type=relation_type,
            source_asset_id=source_asset_id,
            target_workflow_id=target_workflow_id,
            target_node_id=target_node_id,
            target_item_id=target_item_id,
            target_slot_id=target_slot_id,
            created_at=utc_now().isoformat(),
            metadata=dict(metadata or {}),
        )
        return self.save_relation(relation)

    def _asset_metadata_path(self, asset_id: str, version_id: str) -> Path:
        return self._asset_root / "metadata" / asset_id / f"{version_id}.json"

    def _relation_metadata_path(self, relation_id: str) -> Path:
        return self._asset_root / "metadata" / "relations" / f"{relation_id}.json"


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _external_file_path(data_dir: Path, asset_id: str, asset: dict[str, Any]) -> str:
    raw_path = _first_string(asset, "file_path", "local_path", "uri")
    if raw_path:
        path = Path(raw_path)
        if path.is_absolute():
            try:
                return path.relative_to(data_dir).as_posix()
            except ValueError:
                return path.as_posix()
        return path.as_posix()
    filename = _first_string(asset, "filename", "display_name") or f"{asset_id}.bin"
    return (Path("assets") / "originals" / asset_id / filename).as_posix()


def _external_source_type(file_path: str) -> str:
    if file_path.startswith("assets/originals/"):
        return "upload"
    return "imported"


def _media_type(asset: dict[str, Any]) -> str:
    for key in ("media_type", "asset_type", "type", "kind"):
        value = asset.get(key)
        if value in {"image", "video", "audio", "text"}:
            return value
    mime_type = _first_string(asset, "mime_type", "content_type")
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "image"
