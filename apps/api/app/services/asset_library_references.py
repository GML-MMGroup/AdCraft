from pathlib import Path
from typing import Any

from app.schemas.asset_library import (
    SUPPORTED_ASSET_REFERENCE_ROLES,
    AssetReference,
    LibraryAsset,
    LibraryEntity,
)
from app.services.asset_library import AssetLibraryError
from app.services.asset_reference_sources import (
    canvas_asset_display_name,
    canvas_asset_entity_type,
    canvas_asset_semantic_types,
    canvas_asset_uri,
    find_canvas_asset,
)
from app.services.asset_bindings import asset_bindings_from_references
from app.services.canonical_assets import (
    canonical_media_type,
    canonical_reference_role,
    node_accepts_media_type,
    normalize_canonical_asset,
)
from app.services.media_paths import public_url_for_path, with_public_urls
from app.services.output_assets import dedupe_output_assets


DEFAULT_REFERENCE_ROLE_BY_ENTITY_TYPE = {
    "character": "character_reference",
    "scene": "scene_reference",
    "style_reference": "style_reference",
    "bgm": "bgm_reference",
    "video_clip": "video_reference",
    "storyboard_shot": "storyboard_reference",
    "product": "product_reference",
    "uploaded_reference": "general_reference",
}

COMPATIBLE_REFERENCE_ROLES_BY_ENTITY_TYPE = {
    "character": {"character_reference", "style_reference", "general_reference"},
    "scene": {"scene_reference", "style_reference", "general_reference"},
    "style_reference": {"style_reference", "general_reference"},
    "bgm": {"bgm_reference", "general_reference"},
    "video_clip": {"video_reference", "storyboard_reference", "general_reference"},
    "storyboard_shot": {"storyboard_reference", "video_reference", "general_reference"},
    "product": {"product_reference", "general_reference"},
    "uploaded_reference": set(SUPPORTED_ASSET_REFERENCE_ROLES),
}

VISIBLE_REFERENCE_NODE_IDS = {
    "script",
    "product-generation",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
    "final-composition",
}

REFERENCE_TARGETS_BY_ROLE = {
    "character_reference": {
        "character-generation",
        "storyboard",
        "storyboard-video-generation",
    },
    "scene_reference": {
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
    },
    "style_reference": {
        "character-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
    },
    "bgm_reference": {"bgm", "final-composition"},
    "video_reference": {"storyboard-video-generation", "final-composition"},
    "storyboard_reference": {"storyboard", "storyboard-video-generation"},
    "product_reference": {
        "script",
        "product-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
        "final-composition",
    },
    "general_reference": {
        "product-generation",
        "character-generation",
        "scene-generation",
        "storyboard",
        "storyboard-video-generation",
        "bgm",
        "final-composition",
    },
}


def normalize_library_entity_ids(
    data_dir: Path,
    library_entity_ids: list[str],
    *,
    available_node_ids: set[str] | None = None,
    workflow_id: str | None = None,
) -> list[dict[str, Any]]:
    return normalize_asset_references(
        data_dir,
        [],
        library_entity_ids=library_entity_ids,
        available_node_ids=available_node_ids,
        workflow_id=workflow_id,
    )


def normalize_asset_references(
    data_dir: Path,
    asset_references: list[AssetReference | dict[str, Any]],
    *,
    library_entity_ids: list[str] | None = None,
    available_node_ids: set[str] | None = None,
    workflow_id: str | None = None,
) -> list[dict[str, Any]]:
    available_node_ids = available_node_ids or VISIBLE_REFERENCE_NODE_IDS
    requests = [
        _coerce_asset_reference(reference)
        for reference in asset_references
        if reference is not None
    ]
    for entity_id in _dedupe_strings(library_entity_ids or []):
        requests.append(AssetReference(entity_id=entity_id))
    normalized = [
        _normalize_single_reference(
            data_dir,
            request,
            available_node_ids=available_node_ids,
            workflow_id=workflow_id,
        )
        for request in requests
    ]
    return _dedupe_references(normalized)


def validate_reference_role(entity_type: str, role: str) -> None:
    compatible = COMPATIBLE_REFERENCE_ROLES_BY_ENTITY_TYPE.get(entity_type, set())
    if role not in compatible:
        raise AssetLibraryError("asset_reference_type_mismatch", 422)


def references_for_node(
    references: list[dict[str, Any]],
    node_id: str,
) -> list[dict[str, Any]]:
    applicable = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        target_node_ids = _dedupe_strings(reference.get("target_node_ids") or [])
        role = str(reference.get("role") or "")
        if target_node_ids:
            if node_id in target_node_ids:
                applicable.append(reference)
            continue
        if role == "general_reference" and _reference_has_media_for_node(reference, node_id):
            applicable.append(reference)
            continue
        if node_id in REFERENCE_TARGETS_BY_ROLE.get(role, set()):
            applicable.append(reference)
    return applicable


def reference_context_for_node(
    references: list[dict[str, Any]],
    node_id: str,
) -> dict[str, Any]:
    node_references = references_for_node(references, node_id)
    asset_bindings = [
        binding.model_dump(mode="json")
        for binding in asset_bindings_from_references(node_references)
    ]
    prompt_assets = library_reference_assets(node_references, node_id, prompt_only=True)
    provider_references = [
        reference
        for reference in node_references
        if str(reference.get("role") or "") != "general_reference"
    ]
    provider_assets = [
        {
            **asset,
            "provider_reference_supported": False,
            "provider_reference_unsupported": True,
        }
        for asset in library_reference_assets(provider_references, node_id)
    ]
    display_assets = library_reference_assets(node_references, node_id)
    return {
        "asset_references": node_references,
        "asset_bindings": asset_bindings,
        "prompt_context_assets": prompt_assets,
        "provider_reference_assets": provider_assets,
        "display_input_assets": display_assets,
        "source_mappings": library_reference_source_mappings(node_references, node_id),
    }


def library_reference_assets(
    references: list[dict[str, Any]],
    node_id: str,
    *,
    prompt_only: bool = False,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for reference in references:
        if prompt_only and reference.get("use_as_prompt") is False:
            continue
        source_type = str(reference.get("source_type") or "asset_library")
        source_node_id = source_type
        for asset in reference.get("assets", []):
            if not isinstance(asset, dict):
                continue
            assets.append(
                with_public_urls(
                    normalize_canonical_asset(
                        {
                            **asset,
                            "source_type": source_type,
                            "source_node_id": source_node_id,
                            "source": source_type,
                            "entity_id": reference.get("entity_id"),
                            "source_id": _reference_source_id(reference),
                            "entity_type": reference.get("entity_type"),
                            "display_name": reference.get("display_name"),
                            "role": reference.get("role"),
                            "is_primary": reference.get("is_primary"),
                            "reference_mode": reference.get("reference_mode"),
                            "target_node_id": node_id,
                            "use_as_prompt": bool(reference.get("use_as_prompt", True)),
                            "lock_identity": bool(reference.get("lock_identity", False)),
                            "allow_style_transfer": bool(
                                reference.get("allow_style_transfer", False)
                            ),
                        },
                        source_node_id=source_node_id,
                        role=str(reference.get("role") or "general_reference"),
                        entity_type=str(reference.get("entity_type") or "uploaded_reference"),
                    )
                )
            )
    return dedupe_output_assets(assets)


def library_reference_source_mappings(
    references: list[dict[str, Any]],
    node_id: str,
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for reference in references:
        source_type = str(reference.get("source_type") or "asset_library")
        source_id = _reference_source_id(reference)
        for asset_id in reference.get("asset_ids", []):
            key = (source_type, source_id, str(asset_id), node_id)
            if key in seen:
                continue
            seen.add(key)
            mappings.append(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_node_id": source_type,
                    "entity_id": reference.get("entity_id"),
                    "asset_id": asset_id,
                    "mention_text": reference.get("mention_text"),
                    "role": reference.get("role"),
                    "is_primary": reference.get("is_primary"),
                    "reference_mode": reference.get("reference_mode"),
                    "target_node_id": node_id,
                    "use_as_prompt": bool(reference.get("use_as_prompt", True)),
                    "lock_identity": bool(reference.get("lock_identity", False)),
                    "allow_style_transfer": bool(reference.get("allow_style_transfer", False)),
                    "from": f"{source_type}.{source_id}.{asset_id}",
                    "to": "asset_references",
                }
            )
    return mappings


def library_reference_derivation_metadata(
    context: dict[str, Any],
) -> dict[str, list[str]]:
    references = context.get("asset_references")
    if not isinstance(references, list):
        return {
            "derived_from_library_entities": [],
            "derived_from_library_assets": [],
            "reference_roles": [],
        }
    return {
        "derived_from_library_entities": _dedupe_strings(
            [reference.get("entity_id") for reference in references if isinstance(reference, dict)]
        ),
        "derived_from_library_assets": _dedupe_strings(
            [
                asset_id
                for reference in references
                if isinstance(reference, dict)
                for asset_id in reference.get("asset_ids", [])
            ]
        ),
        "reference_roles": _dedupe_strings(
            [reference.get("role") for reference in references if isinstance(reference, dict)]
        ),
    }


def _normalize_single_reference(
    data_dir: Path,
    request: AssetReference,
    *,
    available_node_ids: set[str],
    workflow_id: str | None,
) -> dict[str, Any]:
    if request.reference_source == "canvas_asset":
        return _normalize_canvas_reference(
            data_dir,
            request,
            available_node_ids=available_node_ids,
            workflow_id=workflow_id,
        )
    entity = _load_entity(data_dir, request.entity_id)
    if entity is None:
        raise AssetLibraryError("asset_reference_entity_not_found", 404)
    if entity.is_archived:
        raise AssetLibraryError("asset_reference_entity_archived", 422)
    target_node_ids = _dedupe_strings(request.target_node_ids)
    assets = _resolve_reference_assets(data_dir, entity, request.asset_ids)
    role = _reference_role(entity.entity_type, request.role, assets)
    role, warnings = _normalize_role_and_targets_for_media(
        entity_type=entity.entity_type,
        role=role,
        target_node_ids=target_node_ids,
        assets=assets,
        available_node_ids=available_node_ids,
    )
    metadata = dict(request.metadata or {})
    _append_metadata_warnings(metadata, warnings)
    return {
        "source_type": "asset_library",
        "reference_source": "asset_library",
        "entity_id": entity.entity_id,
        "asset_id": request.asset_id,
        "entity_type": entity.entity_type,
        "display_name": entity.display_name,
        "asset_ids": [asset["asset_id"] for asset in assets],
        "assets": assets,
        "mention_text": request.mention_text,
        "role": role,
        "use_as_prompt": bool(request.use_as_prompt),
        "lock_identity": bool(request.lock_identity),
        "allow_style_transfer": bool(request.allow_style_transfer),
        "is_primary": request.is_primary,
        "reference_mode": request.reference_mode or "strict",
        "target_node_ids": target_node_ids,
        "metadata": metadata,
    }


def _normalize_canvas_reference(
    data_dir: Path,
    request: AssetReference,
    *,
    available_node_ids: set[str],
    workflow_id: str | None,
) -> dict[str, Any]:
    if not workflow_id:
        raise AssetLibraryError("asset_reference_workflow_id_required", 422)
    if not request.asset_id:
        raise AssetLibraryError("asset_reference_canvas_asset_not_found", 404)
    asset = find_canvas_asset(data_dir, request.asset_id, workflow_id=workflow_id)
    if asset is None:
        raise AssetLibraryError("asset_reference_canvas_asset_not_found", 404)
    target_node_ids = _dedupe_strings(request.target_node_ids)
    _validate_canvas_asset_file(data_dir, asset)
    asset_summary = _canvas_asset_summary(asset)
    display_name = request.display_name or canvas_asset_display_name(asset)
    entity_type = canvas_asset_entity_type(asset)
    role = _reference_role_for_canvas_asset(asset, request.role)
    role, warnings = _normalize_role_and_targets_for_media(
        entity_type=entity_type,
        role=role,
        target_node_ids=target_node_ids,
        assets=[asset_summary],
        available_node_ids=available_node_ids,
    )
    metadata = {
        **dict(request.metadata or {}),
        "scope": asset.get("scope") or "project",
        "workflow_id": asset.get("workflow_id"),
        "node_id": asset.get("node_id"),
    }
    _append_metadata_warnings(metadata, warnings)
    return {
        "source_type": "canvas_asset",
        "reference_source": "canvas_asset",
        "entity_id": None,
        "asset_id": request.asset_id,
        "entity_type": entity_type,
        "display_name": display_name,
        "asset_ids": [request.asset_id],
        "assets": [asset_summary],
        "mention_text": request.mention_text,
        "role": role,
        "semantic_types": canvas_asset_semantic_types(asset),
        "use_as_prompt": bool(request.use_as_prompt),
        "lock_identity": bool(request.lock_identity),
        "allow_style_transfer": bool(request.allow_style_transfer),
        "is_primary": request.is_primary,
        "reference_mode": request.reference_mode or "strict",
        "target_node_ids": target_node_ids,
        "metadata": metadata,
    }


def _coerce_asset_reference(reference: AssetReference | dict[str, Any]) -> AssetReference:
    if isinstance(reference, AssetReference):
        return reference
    return AssetReference.model_validate(reference)


def _reference_role(
    entity_type: str,
    explicit_role: str | None,
    assets: list[dict[str, Any]] | None = None,
) -> str:
    role = (
        explicit_role
        or canonical_reference_role(
            {"entity_type": entity_type, "assets": assets or []},
            entity_type=entity_type,
            media_type=_first_media_type(assets or []),
        )
        or DEFAULT_REFERENCE_ROLE_BY_ENTITY_TYPE.get(entity_type)
        or ""
    ).strip()
    if role not in SUPPORTED_ASSET_REFERENCE_ROLES:
        raise AssetLibraryError("asset_reference_type_mismatch", 422)
    return role


def _reference_role_for_canvas_asset(
    asset: dict[str, Any],
    explicit_role: str | None,
) -> str:
    if explicit_role:
        role = explicit_role.strip()
        if role not in SUPPORTED_ASSET_REFERENCE_ROLES:
            raise AssetLibraryError("asset_reference_type_mismatch", 422)
        return role
    asset_type = canonical_media_type(asset)
    if asset_type == "video":
        return "video_reference"
    if asset_type == "audio":
        return "bgm_reference"
    return DEFAULT_REFERENCE_ROLE_BY_ENTITY_TYPE.get(
        canvas_asset_entity_type(asset),
        "general_reference",
    )


def _validate_target_node_ids(
    target_node_ids: list[str],
    role: str,
    available_node_ids: set[str],
) -> None:
    supported = REFERENCE_TARGETS_BY_ROLE.get(role, set())
    for target_node_id in target_node_ids:
        if target_node_id not in available_node_ids or target_node_id not in supported:
            raise AssetLibraryError("asset_reference_target_node_mismatch", 422)


def _normalize_role_and_targets_for_media(
    *,
    entity_type: str,
    role: str,
    target_node_ids: list[str],
    assets: list[dict[str, Any]],
    available_node_ids: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    normalized_role = role
    if role not in COMPATIBLE_REFERENCE_ROLES_BY_ENTITY_TYPE.get(entity_type, set()):
        if not _role_media_compatible(role, assets):
            raise AssetLibraryError("asset_reference_type_mismatch", 422)
        warnings.append(
            {
                "code": "reference_role_normalized",
                "from": role,
                "to": "general_reference",
                "entity_type": entity_type,
                "media_type": _first_media_type(assets),
            }
        )
        normalized_role = "general_reference"
    for target_node_id in target_node_ids:
        if target_node_id not in available_node_ids:
            raise AssetLibraryError("asset_reference_target_node_mismatch", 422)
        role_targets = REFERENCE_TARGETS_BY_ROLE.get(normalized_role, set())
        if target_node_id in role_targets and _target_media_compatible(target_node_id, assets):
            continue
        if _target_media_compatible(target_node_id, assets):
            warnings.append(
                {
                    "code": "reference_target_role_mismatch_degraded",
                    "target_node_id": target_node_id,
                    "role": normalized_role,
                    "media_type": _first_media_type(assets),
                }
            )
            normalized_role = "general_reference"
            continue
        raise AssetLibraryError("asset_reference_target_node_mismatch", 422)
    return normalized_role, warnings


def _resolve_reference_assets(
    data_dir: Path,
    entity: LibraryEntity,
    requested_asset_ids: list[str],
) -> list[dict[str, Any]]:
    requested = _dedupe_strings(requested_asset_ids)
    if requested:
        assets = []
        for asset_id in requested:
            asset = _load_asset(data_dir, asset_id)
            if asset is None or asset.entity_id != entity.entity_id:
                raise AssetLibraryError("asset_reference_asset_not_found", 404)
            if asset.is_archived:
                raise AssetLibraryError("asset_reference_no_usable_assets", 422)
            assets.append(asset)
    else:
        assets = [
            asset
            for asset_id in entity.asset_ids
            for asset in [_load_asset(data_dir, asset_id)]
            if asset is not None and not asset.is_archived
        ]
    if not assets:
        raise AssetLibraryError("asset_reference_no_usable_assets", 422)
    summaries = []
    for asset in assets:
        _validate_reference_asset_file(data_dir, asset)
        summaries.append(_asset_summary(asset))
    return summaries


def _asset_summary(asset: LibraryAsset) -> dict[str, Any]:
    local_path = _local_path_for_uri(asset.uri)
    asset_payload = asset.model_dump(mode="json")
    asset_type = canonical_media_type({**asset_payload, "local_path": local_path})
    summary = normalize_canonical_asset(
        {
            "asset_id": asset.asset_id,
            "entity_id": asset.entity_id,
            "asset_type": asset_type,
            "type": asset_type,
            "media_type": asset_type,
            "kind": asset_type,
            "semantic_type": asset.semantic_type,
            "uri": asset.uri,
            "local_path": local_path,
            "public_url": public_url_for_path(local_path) if local_path else None,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "duration_seconds": asset.duration_seconds,
            "metadata": dict(asset.metadata or {}),
        },
        entity_type="uploaded_reference",
    )
    summary["semantic_type"] = asset.semantic_type
    return {key: value for key, value in summary.items() if value is not None}


def _canvas_asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    uri = canvas_asset_uri(asset)
    local_path = _local_path_for_uri(str(asset.get("local_path") or uri or ""))
    asset_type = canonical_media_type({**asset, "uri": uri})
    summary = normalize_canonical_asset(
        {
            **asset,
            "asset_id": str(asset.get("asset_id") or ""),
            "asset_type": asset_type,
            "type": asset_type,
            "media_type": asset_type,
            "kind": asset_type,
            "semantic_type": str((canvas_asset_semantic_types(asset) or ["uploaded_reference"])[0]),
            "uri": uri,
            "local_path": local_path,
            "public_url": asset.get("public_url") or public_url_for_path(local_path),
            "mime_type": asset.get("mime_type"),
            "metadata": dict(asset.get("metadata") or {}),
        },
        entity_type=canvas_asset_entity_type(asset),
    )
    summary["semantic_type"] = str(
        (canvas_asset_semantic_types(asset) or ["uploaded_reference"])[0]
    )
    return {key: value for key, value in summary.items() if value is not None}


def _append_metadata_warnings(
    metadata: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    if not warnings:
        return
    existing = metadata.get("warnings")
    metadata["warnings"] = [
        *(existing if isinstance(existing, list) else []),
        *warnings,
    ]


def _reference_has_media_for_node(reference: dict[str, Any], node_id: str) -> bool:
    return any(
        node_accepts_media_type(node_id, canonical_media_type(asset))
        for asset in reference.get("assets", [])
        if isinstance(asset, dict)
    )


def _target_media_compatible(target_node_id: str, assets: list[dict[str, Any]]) -> bool:
    return any(
        node_accepts_media_type(target_node_id, canonical_media_type(asset)) for asset in assets
    )


def _role_media_compatible(role: str, assets: list[dict[str, Any]]) -> bool:
    role_targets = REFERENCE_TARGETS_BY_ROLE.get(role, set())
    return any(
        node_accepts_media_type(target_node_id, canonical_media_type(asset))
        for target_node_id in role_targets
        for asset in assets
    )


def _first_media_type(assets: list[dict[str, Any]]) -> str:
    for asset in assets:
        media_type = canonical_media_type(asset)
        if media_type:
            return media_type
    return ""


def _validate_canvas_asset_file(data_dir: Path, asset: dict[str, Any]) -> None:
    local_path = _local_path_for_uri(str(asset.get("local_path") or asset.get("uri") or ""))
    if local_path is None:
        return
    path = Path(local_path)
    exists = path.exists() if path.is_absolute() else (data_dir / local_path).exists()
    if not exists:
        raise AssetLibraryError("asset_reference_canvas_asset_not_found", 404)


def _load_entity(data_dir: Path, entity_id: str) -> LibraryEntity | None:
    path = data_dir / "asset_library" / "entities" / f"{entity_id}.json"
    if not path.exists():
        return None
    return LibraryEntity.model_validate_json(path.read_text(encoding="utf-8"))


def _load_asset(data_dir: Path, asset_id: str) -> LibraryAsset | None:
    path = data_dir / "asset_library" / "assets" / f"{asset_id}.json"
    if not path.exists():
        return None
    return LibraryAsset.model_validate_json(path.read_text(encoding="utf-8"))


def _validate_reference_asset_file(data_dir: Path, asset: LibraryAsset) -> None:
    local_path = _local_path_for_uri(asset.uri)
    if local_path is None:
        return
    path = Path(local_path)
    if path.is_absolute():
        exists = path.exists()
    else:
        exists = (data_dir / local_path).exists()
    if not exists:
        raise AssetLibraryError("asset_reference_file_missing", 422)


def _local_path_for_uri(uri: str) -> str | None:
    value = str(uri or "").strip()
    if not value or value.startswith(("http://", "https://", "/media/")):
        return None
    return value


def _asset_type_from_uri(uri: str) -> str:
    value = str(uri or "").lower()
    if value.endswith((".mp4", ".mov", ".webm")):
        return "video"
    if value.endswith((".mp3", ".wav", ".aac", ".m4a")):
        return "audio"
    if value.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    return "reference"


def _dedupe_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...], str, tuple[str, ...]]] = set()
    for reference in references:
        key = (
            str(reference.get("source_type") or "asset_library"),
            str(reference.get("entity_id") or ""),
            tuple(_dedupe_strings(reference.get("asset_ids") or [])),
            str(reference.get("role") or ""),
            tuple(_dedupe_strings(reference.get("target_node_ids") or [])),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reference)
    return deduped


def _reference_source_id(reference: dict[str, Any]) -> str:
    if reference.get("source_type") == "canvas_asset":
        return str(reference.get("asset_id") or "")
    return str(reference.get("entity_id") or "")


def _dedupe_strings(values: list[Any]) -> list[str]:
    return [value for value in dict.fromkeys(str(item).strip() for item in values) if value]
