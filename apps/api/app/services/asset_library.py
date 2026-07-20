import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.asset_library import (
    SUPPORTED_LIBRARY_ENTITY_TYPES,
    SUPPORTED_LIBRARY_SEMANTIC_TYPES,
    AssetLibraryAssetSummary,
    AssetLibraryCreateEntityRequest,
    AssetLibraryCreateEntityResponse,
    AssetLibraryEntityDetailResponse,
    AssetLibraryEntitySummary,
    AssetLibraryListResponse,
    AssetLibraryPatchEntityRequest,
    LibraryAsset,
    LibraryEntity,
)
from app.services.agent_trace import utc_now
from app.services.canonical_assets import (
    canonical_media_type,
    canonical_semantic_type,
    normalize_canonical_asset,
)
from app.services.output_assets import dedupe_output_assets
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_asset_history import load_node_asset_history
from app.services.workflow_state import load_active_node_results


class AssetLibraryError(ValueError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _EntityListFilters:
    entity_type: str | None
    semantic_type: str | None
    tag: str | None
    q: str | None
    source_workflow_id: str | None
    include_archived: bool


class AssetLibraryService:
    def __init__(self, settings: Settings) -> None:
        self._data_dir = settings.media_data_dir

    def create_entity(
        self, request: AssetLibraryCreateEntityRequest
    ) -> AssetLibraryCreateEntityResponse:
        _validate_entity_type(request.entity_type)
        selected_assets = self._select_workflow_assets(request)
        now = utc_now().isoformat()
        entity_id = f"lib_ent_{uuid4().hex[:12]}"
        library_assets = [
            self._library_asset_from_workflow_asset(
                workflow_asset,
                entity_id=entity_id,
                entity_type=request.entity_type,
                created_at=now,
            )
            for workflow_asset in selected_assets
        ]
        entity = LibraryEntity(
            entity_id=entity_id,
            entity_type=request.entity_type,
            display_name=request.display_name,
            description=request.description,
            tags=_dedupe_strings(request.tags),
            source={
                "workflow_id": request.source_workflow_id,
                "node_id": request.source_node_id,
                "entity_id": request.source_entity_id,
                "run_id": _first_non_empty(selected_assets, "run_id"),
            },
            asset_ids=[asset.asset_id for asset in library_assets],
            reuse_policy=dict(request.reuse_policy or {}),
            is_archived=False,
            created_at=now,
            updated_at=now,
            metadata=dict(request.metadata or {}),
        )
        self._write_entity(entity)
        for asset in library_assets:
            self._write_asset(asset)
        self._write_index(self._upsert_index_entity(entity))
        return AssetLibraryCreateEntityResponse(
            entity_id=entity.entity_id,
            asset_ids=entity.asset_ids,
            entity=entity,
        )

    def create_entity_from_uploaded_assets(
        self,
        *,
        uploaded_assets: list[dict[str, Any]],
        entity_type: str,
        semantic_types: list[str],
        display_name: str,
        description: str = "",
        tags: list[str] | None = None,
        reuse_policy: dict[str, Any] | None = None,
    ) -> AssetLibraryEntityDetailResponse:
        _validate_entity_type(entity_type)
        if len(uploaded_assets) != len(semantic_types):
            raise AssetLibraryError("upload_asset_metadata_mismatch", 422)
        now = utc_now().isoformat()
        entity_id = f"lib_ent_{uuid4().hex[:12]}"
        library_assets: list[LibraryAsset] = []
        for uploaded_asset, semantic_type in zip(uploaded_assets, semantic_types):
            _validate_semantic_type(semantic_type)
            _validate_asset_file(self._data_dir, uploaded_asset)
            asset_type = canonical_media_type(uploaded_asset)
            asset_metadata = {
                "filename": uploaded_asset.get("filename"),
                "public_url": uploaded_asset.get("public_url"),
                "size_bytes": uploaded_asset.get("size_bytes"),
            }
            upload_metadata = uploaded_asset.get("metadata")
            if isinstance(upload_metadata, dict):
                asset_metadata.update(upload_metadata)
            library_assets.append(
                LibraryAsset(
                    asset_id=f"lib_asset_{uuid4().hex[:12]}",
                    entity_id=entity_id,
                    asset_type=asset_type,
                    media_type=asset_type,
                    type=asset_type,
                    kind=asset_type,
                    semantic_type=semantic_type,
                    uri=str(uploaded_asset.get("local_path") or uploaded_asset.get("uri") or ""),
                    mime_type=uploaded_asset.get("mime_type"),
                    width=_int_or_none(uploaded_asset.get("width")),
                    height=_int_or_none(uploaded_asset.get("height")),
                    duration_seconds=_float_or_none(uploaded_asset.get("duration_seconds")),
                    source={
                        "source_type": "upload",
                        "asset_id": uploaded_asset.get("asset_id"),
                    },
                    is_archived=False,
                    created_at=now,
                    metadata={
                        key: value
                        for key, value in asset_metadata.items()
                        if value not in (None, "", [], {})
                    },
                )
            )
        entity = LibraryEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            display_name=display_name,
            description=description,
            tags=_dedupe_strings(tags or []),
            source={
                "source_type": "upload",
                "asset_ids": [
                    str(asset.get("asset_id") or "")
                    for asset in uploaded_assets
                    if asset.get("asset_id")
                ],
                "workflow_id": None,
                "node_id": None,
                "run_id": None,
            },
            asset_ids=[asset.asset_id for asset in library_assets],
            reuse_policy=reuse_policy
            or {
                "use_as_prompt": True,
                "lock_identity": False,
                "allow_style_transfer": False,
            },
            is_archived=False,
            created_at=now,
            updated_at=now,
            metadata={"created_from": "upload"},
        )
        written_paths: list[Path] = []
        try:
            self._write_entity(entity)
            written_paths.append(_entity_path(self._data_dir, entity.entity_id))
            for asset in library_assets:
                self._write_asset(asset)
                written_paths.append(_asset_path(self._data_dir, asset.asset_id))
            self._write_index(self._upsert_index_entity(entity))
        except OSError as exc:
            _rollback_written_paths(written_paths)
            raise AssetLibraryError("asset_library_write_failed", 400) from exc
        return AssetLibraryEntityDetailResponse(entity=entity, assets=library_assets)

    def list_entities(
        self,
        *,
        entity_type: str | None = None,
        semantic_type: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        source_workflow_id: str | None = None,
        include_archived: bool = False,
    ) -> AssetLibraryListResponse:
        filters = _EntityListFilters(
            entity_type=entity_type,
            semantic_type=semantic_type,
            tag=tag,
            q=q,
            source_workflow_id=source_workflow_id,
            include_archived=include_archived,
        )
        _validate_entity_list_filters(filters)
        summaries = []
        for item in self._read_index().get("entities", []):
            if not _index_entity_matches_filters(item, filters):
                continue
            entity = self._load_entity(str(item.get("entity_id") or ""))
            if entity is None:
                continue
            assets = self._load_entity_assets(entity)
            if not _loaded_entity_matches_filters(entity, filters):
                continue
            visible_assets = _visible_entity_assets(assets, filters.include_archived)
            if not _visible_assets_match_semantic(visible_assets, filters.semantic_type):
                continue
            summaries.append(_entity_summary(entity, visible_assets))
        summaries.sort(key=lambda entity: entity.updated_at, reverse=True)
        return AssetLibraryListResponse(entities=summaries)

    def get_entity(
        self,
        entity_id: str,
        *,
        include_archived: bool = True,
    ) -> AssetLibraryEntityDetailResponse:
        entity = self._load_entity(entity_id)
        if entity is None:
            raise AssetLibraryError("asset_library_entity_not_found", 404)
        assets = self._load_entity_assets(entity)
        if not include_archived:
            assets = [asset for asset in assets if not asset.is_archived]
        return AssetLibraryEntityDetailResponse(entity=entity, assets=assets)

    def patch_entity(
        self,
        entity_id: str,
        request: AssetLibraryPatchEntityRequest,
    ) -> AssetLibraryEntityDetailResponse:
        entity = self._load_entity(entity_id)
        if entity is None:
            raise AssetLibraryError("asset_library_entity_not_found", 404)
        updates = request.model_dump(exclude_unset=True)
        if "display_name" in updates and updates["display_name"] is not None:
            entity.display_name = str(updates["display_name"])
        if "description" in updates and updates["description"] is not None:
            entity.description = str(updates["description"])
        if "tags" in updates and updates["tags"] is not None:
            entity.tags = _dedupe_strings(updates["tags"])
        if "reuse_policy" in updates and updates["reuse_policy"] is not None:
            entity.reuse_policy = dict(updates["reuse_policy"])
        if "is_archived" in updates and updates["is_archived"] is not None:
            entity.is_archived = bool(updates["is_archived"])
        entity.updated_at = utc_now().isoformat()
        self._write_entity(entity)
        self._write_index(self._upsert_index_entity(entity))
        return self.get_entity(entity_id)

    def _select_workflow_assets(
        self,
        request: AssetLibraryCreateEntityRequest,
    ) -> list[dict[str, Any]]:
        active = load_active_node_results(self._data_dir, request.source_workflow_id)
        active_payload = active.get(request.source_node_id)
        candidates = []
        if isinstance(active_payload, dict):
            candidates.extend(_assets_from_active_payload(active_payload))
        candidates.extend(
            asset
            for asset in load_node_asset_history(
                self._data_dir,
                request.source_workflow_id,
                request.source_node_id,
            )
            if asset.get("is_active") is True
        )
        candidates = dedupe_output_assets(candidates)
        requested_asset_ids = _dedupe_strings(request.asset_ids)
        if requested_asset_ids:
            selected = [
                asset
                for asset_id in requested_asset_ids
                for asset in candidates
                if asset.get("asset_id") == asset_id
                and _asset_entity_id(asset) == request.source_entity_id
            ]
            if len(selected) != len(requested_asset_ids):
                raise AssetLibraryError("workflow_asset_not_found", 404)
        else:
            selected = [
                asset
                for asset in candidates
                if _asset_entity_id(asset) == request.source_entity_id
                and asset.get("is_active") is not False
                and asset.get("is_archived") is not True
            ]
            if not selected:
                raise AssetLibraryError("no_active_assets_for_entity", 422)

        for asset in selected:
            _validate_semantic_type(_asset_semantic_type(asset))
            _validate_asset_file(self._data_dir, asset)
        return dedupe_output_assets(selected)

    def _library_asset_from_workflow_asset(
        self,
        workflow_asset: dict[str, Any],
        *,
        entity_id: str,
        entity_type: str,
        created_at: str,
    ) -> LibraryAsset:
        source = {
            "workflow_id": workflow_asset.get("workflow_id"),
            "node_id": workflow_asset.get("node_id") or workflow_asset.get("source_node_id"),
            "asset_id": workflow_asset.get("asset_id"),
            "run_id": workflow_asset.get("run_id"),
            "entity_id": _asset_entity_id(workflow_asset),
        }
        normalized = normalize_canonical_asset(
            workflow_asset,
            source_node_id=source.get("node_id"),
            entity_type=entity_type,
        )
        asset_type = canonical_media_type(normalized)
        semantic_type = canonical_semantic_type(
            normalized,
            entity_type=entity_type,
            media_type=asset_type,
        )
        return LibraryAsset(
            asset_id=f"lib_asset_{uuid4().hex[:12]}",
            entity_id=entity_id,
            asset_type=asset_type,
            media_type=asset_type,
            type=asset_type,
            kind=asset_type,
            semantic_type=semantic_type,
            uri=_asset_uri(workflow_asset),
            mime_type=workflow_asset.get("mime_type"),
            width=_int_or_none(workflow_asset.get("width")),
            height=_int_or_none(workflow_asset.get("height")),
            duration_seconds=_float_or_none(workflow_asset.get("duration_seconds")),
            source={key: value for key, value in source.items() if value not in (None, "")},
            is_archived=bool(workflow_asset.get("is_archived", False)),
            created_at=created_at,
            metadata=dict(workflow_asset.get("metadata") or {}),
        )

    def _load_entity(self, entity_id: str) -> LibraryEntity | None:
        path = _entity_path(self._data_dir, entity_id)
        if not path.exists():
            return None
        return LibraryEntity.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_asset(self, asset_id: str) -> LibraryAsset | None:
        path = _asset_path(self._data_dir, asset_id)
        if not path.exists():
            return None
        return LibraryAsset.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_entity_assets(self, entity: LibraryEntity) -> list[LibraryAsset]:
        return [
            asset
            for asset_id in entity.asset_ids
            for asset in [self._load_asset(asset_id)]
            if asset is not None
        ]

    def _write_entity(self, entity: LibraryEntity) -> None:
        _write_json_atomic(
            _entity_path(self._data_dir, entity.entity_id), entity.model_dump(mode="json")
        )

    def _write_asset(self, asset: LibraryAsset) -> None:
        _write_json_atomic(
            _asset_path(self._data_dir, asset.asset_id), asset.model_dump(mode="json")
        )

    def _read_index(self) -> dict[str, Any]:
        path = _index_path(self._data_dir)
        if not path.exists():
            return {"entities": []}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"entities": []}

    def _write_index(self, payload: dict[str, Any]) -> None:
        _write_json_atomic(_index_path(self._data_dir), payload)

    def _upsert_index_entity(self, entity: LibraryEntity) -> dict[str, Any]:
        index = self._read_index()
        entities = [item for item in index.get("entities", []) if isinstance(item, dict)]
        summary = {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "display_name": entity.display_name,
            "tags": entity.tags,
            "asset_ids": entity.asset_ids,
            "source_workflow_id": entity.source.get("workflow_id"),
            "is_archived": entity.is_archived,
            "updated_at": entity.updated_at,
        }
        replaced = False
        for idx, item in enumerate(entities):
            if item.get("entity_id") == entity.entity_id:
                entities[idx] = summary
                replaced = True
                break
        if not replaced:
            entities.append(summary)
        return {"entities": entities}


def _index_path(data_dir: Path) -> Path:
    return data_dir / "asset_library" / "index.json"


def _entity_path(data_dir: Path, entity_id: str) -> Path:
    return data_dir / "asset_library" / "entities" / f"{entity_id}.json"


def _asset_path(data_dir: Path, asset_id: str) -> Path:
    return data_dir / "asset_library" / "assets" / f"{asset_id}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _rollback_written_paths(paths: list[Path]) -> None:
    for path in reversed(paths):
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in SUPPORTED_LIBRARY_ENTITY_TYPES:
        raise AssetLibraryError("invalid_entity_type", 422)


def _validate_semantic_type(semantic_type: str) -> None:
    if semantic_type not in SUPPORTED_LIBRARY_SEMANTIC_TYPES:
        raise AssetLibraryError("invalid_semantic_type", 422)


def _validate_entity_list_filters(filters: _EntityListFilters) -> None:
    if filters.entity_type:
        _validate_entity_type(filters.entity_type)
    if filters.semantic_type:
        _validate_semantic_type(filters.semantic_type)


def _index_entity_matches_filters(item: object, filters: _EntityListFilters) -> bool:
    if not isinstance(item, dict):
        return False
    if not filters.include_archived and item.get("is_archived") is True:
        return False
    if filters.entity_type and item.get("entity_type") != filters.entity_type:
        return False
    if filters.tag and filters.tag not in _list_or_empty(item.get("tags")):
        return False
    indexed_workflow_id = item.get("source_workflow_id")
    if (
        filters.source_workflow_id
        and indexed_workflow_id not in (None, "")
        and indexed_workflow_id != filters.source_workflow_id
    ):
        return False
    return True


def _loaded_entity_matches_filters(entity: LibraryEntity, filters: _EntityListFilters) -> bool:
    if not filters.include_archived and entity.is_archived:
        return False
    if filters.entity_type and entity.entity_type != filters.entity_type:
        return False
    if filters.tag and filters.tag not in entity.tags:
        return False
    if filters.q and not _matches_query(entity, filters.q):
        return False
    return not (
        filters.source_workflow_id
        and entity.source.get("workflow_id") != filters.source_workflow_id
    )


def _visible_entity_assets(
    assets: list[LibraryAsset], include_archived: bool
) -> list[LibraryAsset]:
    return [asset for asset in assets if include_archived or not asset.is_archived]


def _visible_assets_match_semantic(assets: list[LibraryAsset], semantic_type: str | None) -> bool:
    return not semantic_type or any(asset.semantic_type == semantic_type for asset in assets)


def _validate_asset_file(data_dir: Path, asset: dict[str, Any]) -> None:
    local_path = _local_file_reference(asset)
    if local_path and not (data_dir / local_path).exists():
        raise AssetLibraryError("asset_file_missing", 422)


def _assets_from_active_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets = legacy_output_assets_from_payload(payload)
    run_id = str(payload.get("node_run_id") or "")
    workflow_id = str(payload.get("workflow_id") or "")
    node_id = str(payload.get("node_id") or payload.get("node_type") or "")
    enriched = []
    for asset in dedupe_output_assets(assets):
        item = dict(asset)
        item.setdefault("workflow_id", workflow_id)
        item.setdefault("node_id", node_id)
        item.setdefault("run_id", run_id)
        item.setdefault("is_active", True)
        enriched.append(item)
    return enriched


def _asset_semantic_type(asset: dict[str, Any]) -> str:
    return str(asset.get("semantic_type") or asset.get("role") or asset.get("kind") or "")


def _asset_entity_id(asset: dict[str, Any]) -> str:
    for key in (
        "entity_id",
        "roleId",
        "role_id",
        "characterId",
        "character_id",
        "sceneId",
        "scene_id",
        "shotId",
        "shot_id",
        "id",
    ):
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _asset_uri(asset: dict[str, Any]) -> str:
    for key in ("uri", "local_path", "public_url", "remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise AssetLibraryError("workflow_asset_not_found", 404)


def _local_file_reference(asset: dict[str, Any]) -> str | None:
    for key in ("local_path", "uri"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip() and not _is_external_uri(value.strip()):
            return value.strip()
    return None


def _is_external_uri(value: str) -> bool:
    return value.startswith(("http://", "https://", "/media/"))


def _entity_summary(
    entity: LibraryEntity,
    assets: list[LibraryAsset],
) -> AssetLibraryEntitySummary:
    asset_summaries = []
    for asset in assets:
        asset_payload = asset.model_dump(mode="json")
        media_type = canonical_media_type(asset_payload)
        asset_summaries.append(
            AssetLibraryAssetSummary(
                asset_id=asset.asset_id,
                asset_type=media_type,
                media_type=media_type,
                type=media_type,
                kind=media_type,
                semantic_type=asset.semantic_type,
                uri=asset.uri,
                mime_type=asset.mime_type,
                is_archived=asset.is_archived,
            )
        )
    return AssetLibraryEntitySummary(
        entity_id=entity.entity_id,
        entity_type=entity.entity_type,
        display_name=entity.display_name,
        description=entity.description,
        tags=entity.tags,
        asset_ids=[asset.asset_id for asset in assets],
        assets=asset_summaries,
        is_archived=entity.is_archived,
        updated_at=entity.updated_at,
    )


def _matches_query(entity: LibraryEntity, query: str) -> bool:
    needle = query.casefold()
    values = [entity.display_name, entity.description, *entity.tags]
    return any(needle in value.casefold() for value in values if value)


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_strings(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(item).strip() for item in values) if value]


def _first_non_empty(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
