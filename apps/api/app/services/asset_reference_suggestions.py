from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.schemas.asset_references import (
    AssetReferencePreviewAsset,
    AssetReferenceSuggestResponse,
    AssetReferenceSuggestionItem,
)
from app.schemas.asset_library import LibraryAsset, LibraryEntity
from app.services.asset_library import AssetLibraryError, AssetLibraryService
from app.services.asset_library_references import DEFAULT_REFERENCE_ROLE_BY_ENTITY_TYPE
from app.services.asset_reference_sources import (
    canvas_asset_display_name,
    canvas_asset_entity_type,
    canvas_asset_preview,
    canvas_asset_semantic_types,
    canvas_asset_uri,
    load_canvas_assets,
)
from app.services.media_paths import public_url_for_path


class AssetReferenceSuggestionService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._library = AssetLibraryService(settings)

    def suggest(
        self,
        *,
        q: str | None = None,
        types: str | None = None,
        workflow_id: str | None = None,
        node_id: str | None = None,
        include_canvas_assets: bool = True,
        include_library_assets: bool = True,
        limit: int = 30,
    ) -> AssetReferenceSuggestResponse:
        type_filters = _parse_types(types)
        canvas_assets = (
            load_canvas_assets(self._data_dir, workflow_id) if include_canvas_assets else []
        )
        canvas_by_key = _canvas_assets_by_dedupe_key(canvas_assets)
        library_items: list[AssetReferenceSuggestionItem] = []
        linked_canvas_asset_ids: set[str] = set()
        linked_canvas_keys: set[str] = set()
        if include_library_assets:
            library_items = self._library_items(
                q=q,
                type_filters=type_filters,
                canvas_by_key=canvas_by_key,
                linked_canvas_asset_ids=linked_canvas_asset_ids,
                linked_canvas_keys=linked_canvas_keys,
            )
        canvas_items = (
            self._canvas_items(
                canvas_assets,
                q=q,
                type_filters=type_filters,
                workflow_id=workflow_id,
                linked_canvas_asset_ids=linked_canvas_asset_ids,
                linked_canvas_keys=linked_canvas_keys,
            )
            if include_canvas_assets
            else []
        )
        items = [*library_items, *canvas_items]
        items.sort(
            key=lambda item: _sort_key(
                item,
                query=q,
                type_filters=type_filters,
                workflow_id=workflow_id,
            )
        )
        return AssetReferenceSuggestResponse(items=items[: _normalized_limit(limit)])

    def _library_items(
        self,
        *,
        q: str | None,
        type_filters: set[str],
        canvas_by_key: dict[str, list[dict[str, Any]]],
        linked_canvas_asset_ids: set[str],
        linked_canvas_keys: set[str],
    ) -> list[AssetReferenceSuggestionItem]:
        try:
            summaries = self._library.list_entities(include_archived=False).entities
        except AssetLibraryError:
            return []
        items: list[AssetReferenceSuggestionItem] = []
        for summary in summaries:
            try:
                detail = self._library.get_entity(summary.entity_id, include_archived=False)
            except AssetLibraryError:
                continue
            entity = detail.entity
            assets = [asset for asset in detail.assets if not asset.is_archived]
            if not assets:
                continue
            semantic_types = _dedupe_strings([asset.semantic_type for asset in assets])
            if not _library_matches_type(entity, semantic_types, type_filters):
                continue
            search_values = [
                entity.display_name,
                entity.description,
                entity.entity_type,
                *entity.tags,
                *semantic_types,
                *[
                    str(asset.metadata.get("filename") or "")
                    for asset in assets
                    if isinstance(asset.metadata, dict)
                ],
            ]
            if not _matches_query(search_values, q):
                continue
            linked_ids, linked_keys = _linked_canvas_ids_for_library_assets(assets, canvas_by_key)
            linked_canvas_asset_ids.update(linked_ids)
            linked_canvas_keys.update(linked_keys)
            preview_asset = _library_preview_asset(assets[0])
            items.append(
                AssetReferenceSuggestionItem(
                    reference_source="asset_library",
                    entity_id=entity.entity_id,
                    asset_id=None,
                    display_name=entity.display_name,
                    entity_type=entity.entity_type,
                    semantic_types=semantic_types,
                    suggested_role=_suggested_role(entity.entity_type, assets[0].asset_type),
                    preview_asset=preview_asset,
                    linked_canvas_asset_ids=linked_ids,
                    scope=str(entity.metadata.get("scope") or "project"),
                    workspace_id=entity.metadata.get("workspace_id"),
                    owner_user_id=entity.metadata.get("owner_user_id"),
                    visibility=str(entity.metadata.get("visibility") or "private"),
                    metadata={
                        **dict(entity.metadata or {}),
                        "description": entity.description,
                        "tags": entity.tags,
                        "updated_at": entity.updated_at,
                    },
                )
            )
        return items

    def _canvas_items(
        self,
        canvas_assets: list[dict[str, Any]],
        *,
        q: str | None,
        type_filters: set[str],
        workflow_id: str | None,
        linked_canvas_asset_ids: set[str],
        linked_canvas_keys: set[str],
    ) -> list[AssetReferenceSuggestionItem]:
        items: list[AssetReferenceSuggestionItem] = []
        for asset in canvas_assets:
            asset_id = str(asset.get("asset_id") or "")
            if not asset_id or asset_id in linked_canvas_asset_ids:
                continue
            asset_keys = _dedupe_keys_for_canvas_asset(asset)
            if asset_keys & linked_canvas_keys:
                continue
            entity_type = canvas_asset_entity_type(asset)
            semantic_types = canvas_asset_semantic_types(asset)
            asset_type = str(asset.get("asset_type") or asset.get("type") or "")
            if not _canvas_matches_type(entity_type, semantic_types, asset_type, type_filters):
                continue
            display_name = canvas_asset_display_name(asset)
            search_values = [
                display_name,
                str(asset.get("filename") or ""),
                entity_type,
                asset_type,
                *semantic_types,
            ]
            metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
            search_values.extend(str(value) for value in metadata.values() if value)
            if not _matches_query(search_values, q):
                continue
            scope = "workflow" if asset.get("workflow_id") == workflow_id else "project"
            items.append(
                AssetReferenceSuggestionItem(
                    reference_source="canvas_asset",
                    entity_id=None,
                    asset_id=asset_id,
                    display_name=display_name,
                    entity_type=entity_type,
                    semantic_types=semantic_types,
                    suggested_role=_suggested_role(entity_type, asset_type),
                    preview_asset=AssetReferencePreviewAsset.model_validate(
                        canvas_asset_preview(asset)
                    )
                    if canvas_asset_preview(asset)
                    else None,
                    linked_canvas_asset_ids=[],
                    scope=scope,
                    workspace_id=asset.get("workspace_id"),
                    owner_user_id=asset.get("owner_user_id"),
                    visibility=str(asset.get("visibility") or "private"),
                    metadata={
                        **metadata,
                        "workflow_id": asset.get("workflow_id"),
                        "node_id": asset.get("node_id"),
                        "created_at": asset.get("created_at"),
                        "updated_at": asset.get("updated_at"),
                    },
                )
            )
        return items


def _parse_types(types: str | None) -> set[str]:
    if not types:
        return set()
    return {item.strip() for item in types.split(",") if item.strip()}


def _normalized_limit(limit: int) -> int:
    return max(1, min(int(limit or 30), 100))


def _matches_query(values: list[str], query: str | None) -> bool:
    needle = str(query or "").strip().casefold()
    if not needle:
        return True
    return any(needle in value.casefold() for value in values if value)


def _library_matches_type(
    entity: LibraryEntity,
    semantic_types: list[str],
    type_filters: set[str],
) -> bool:
    if not type_filters:
        return True
    return bool({entity.entity_type, *semantic_types, "asset_library"} & type_filters)


def _canvas_matches_type(
    entity_type: str,
    semantic_types: list[str],
    asset_type: str,
    type_filters: set[str],
) -> bool:
    if not type_filters:
        return True
    return bool({entity_type, *semantic_types, asset_type, "canvas_asset"} & type_filters)


def _library_preview_asset(asset: LibraryAsset) -> AssetReferencePreviewAsset:
    local_path = _local_path_for_uri(asset.uri)
    public_url = public_url_for_path(local_path) if local_path else None
    return AssetReferencePreviewAsset(
        asset_id=asset.asset_id,
        uri=public_url or asset.uri,
        local_path=local_path,
        public_url=public_url,
        mime_type=asset.mime_type,
    )


def _local_path_for_uri(uri: str | None) -> str | None:
    value = str(uri or "").strip()
    if not value or value.startswith(("http://", "https://", "/media/")):
        return None
    return value


def _suggested_role(entity_type: str, asset_type: str) -> str:
    if entity_type == "uploaded_reference":
        if asset_type == "video":
            return "video_reference"
        if asset_type == "audio":
            return "bgm_reference"
    return DEFAULT_REFERENCE_ROLE_BY_ENTITY_TYPE.get(entity_type, "general_reference")


def _canvas_assets_by_dedupe_key(
    canvas_assets: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for asset in canvas_assets:
        for key in _dedupe_keys_for_canvas_asset(asset):
            by_key.setdefault(key, []).append(asset)
    return by_key


def _linked_canvas_ids_for_library_assets(
    assets: list[LibraryAsset],
    canvas_by_key: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], set[str]]:
    linked_ids: list[str] = []
    linked_keys: set[str] = set()
    for asset in assets:
        for key in _dedupe_keys_for_library_asset(asset):
            matches = canvas_by_key.get(key, [])
            if not matches:
                continue
            linked_keys.add(key)
            linked_ids.extend(str(match.get("asset_id") or "") for match in matches)
    return _dedupe_strings(linked_ids), linked_keys


def _dedupe_keys_for_library_asset(asset: LibraryAsset) -> set[str]:
    keys = {
        str(asset.source.get("asset_id") or ""),
        str(asset.uri or ""),
        str(asset.metadata.get("public_url") or ""),
        str(asset.metadata.get("local_path") or ""),
    }
    return {key for key in keys if key}


def _dedupe_keys_for_canvas_asset(asset: dict[str, Any]) -> set[str]:
    keys = {
        str(asset.get("asset_id") or ""),
        str(asset.get("local_path") or ""),
        str(asset.get("public_url") or ""),
        str(asset.get("remote_url") or ""),
        str(asset.get("url") or ""),
        str(canvas_asset_uri(asset) or ""),
    }
    return {key for key in keys if key}


def _sort_key(
    item: AssetReferenceSuggestionItem,
    *,
    query: str | None,
    type_filters: set[str],
    workflow_id: str | None,
) -> tuple[Any, ...]:
    query_value = str(query or "").strip().casefold()
    display_name = item.display_name.casefold()
    if query_value and display_name == query_value:
        query_rank = 0
    elif query_value and display_name.startswith(query_value):
        query_rank = 1
    elif query_value:
        query_rank = 2
    else:
        query_rank = 3
    type_values = {item.entity_type, *item.semantic_types, item.reference_source}
    type_rank = 0 if not type_filters or type_values & type_filters else 1
    source_rank = 0 if item.reference_source == "asset_library" else 1
    scope_rank = 0 if item.scope == "workflow" and workflow_id else 1
    timestamp = _timestamp_sort_value(item.metadata)
    return (
        query_rank,
        type_rank,
        source_rank,
        scope_rank,
        -timestamp,
        item.display_name.casefold(),
        item.entity_id or item.asset_id or "",
    )


def _timestamp_sort_value(metadata: dict[str, Any]) -> float:
    for key in ("updated_at", "created_at"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def _dedupe_strings(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(item).strip() for item in values) if value]
