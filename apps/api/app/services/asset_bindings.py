from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.canonical_assets import (
    canonical_media_type,
    canonical_reference_role,
    normalize_canonical_asset,
)


AssetBindingScope = Literal["global", "node", "item", "shot", "final_composition"]


class AssetBinding(BaseModel):
    binding_id: str
    asset_id: str = ""
    entity_id: str = ""
    scope_type: AssetBindingScope = "global"
    scope_id: str = ""
    role: str = "general_reference"
    media_type: str = ""
    use_as_prompt: bool = True
    reference_mode: str | None = None
    lock_identity: bool = False
    binding_source: str = ""
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


def asset_bindings_from_references(
    references: list[dict[str, Any]],
) -> list[AssetBinding]:
    bindings: list[AssetBinding] = []
    for reference_index, reference in enumerate(references):
        if not isinstance(reference, dict):
            continue
        scope_type, scope_ids = _binding_scopes(reference)
        assets = _reference_assets(reference)
        if not assets:
            assets = [_reference_as_asset(reference)]
        for asset_index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            normalized = normalize_canonical_asset(
                {
                    **asset,
                    "entity_id": reference.get("entity_id") or asset.get("entity_id"),
                    "role": reference.get("role") or asset.get("role"),
                    "metadata": asset.get("metadata")
                    if isinstance(asset.get("metadata"), dict)
                    else {},
                },
                role=str(reference.get("role") or asset.get("role") or ""),
                entity_type=str(reference.get("entity_type") or asset.get("entity_type") or ""),
            )
            for scope_id in scope_ids:
                bindings.append(
                    AssetBinding(
                        binding_id=_binding_id(
                            normalized,
                            scope_type,
                            scope_id,
                            reference_index,
                            asset_index,
                        ),
                        asset_id=str(normalized.get("asset_id") or ""),
                        entity_id=str(
                            reference.get("entity_id") or normalized.get("entity_id") or ""
                        ),
                        scope_type=scope_type,
                        scope_id=scope_id,
                        role=str(
                            reference.get("role")
                            or normalized.get("role")
                            or canonical_reference_role(normalized)
                        ),
                        media_type=canonical_media_type(normalized),
                        use_as_prompt=bool(reference.get("use_as_prompt", True)),
                        reference_mode=reference.get("reference_mode"),
                        lock_identity=bool(reference.get("lock_identity", False)),
                        binding_source=str(
                            reference.get("reference_source")
                            or reference.get("source_type")
                            or reference.get("source")
                            or ""
                        ),
                        priority=int(reference.get("priority") or reference_index),
                        metadata={
                            **(
                                reference.get("metadata")
                                if isinstance(reference.get("metadata"), dict)
                                else {}
                            ),
                            "reference_index": reference_index,
                            "asset_index": asset_index,
                        },
                    )
                )
    return bindings


def asset_bindings_for_node(
    bindings: list[AssetBinding],
    *,
    node_id: str,
    node_type: str,
    item_id: str | None = None,
    shot_id: str | None = None,
) -> list[AssetBinding]:
    scoped: list[AssetBinding] = []
    for binding in bindings:
        if binding.scope_type == "global":
            scoped.append(binding)
        elif binding.scope_type == "node" and binding.scope_id in {node_id, node_type}:
            scoped.append(binding)
        elif binding.scope_type == "item" and item_id and binding.scope_id == item_id:
            scoped.append(binding)
        elif binding.scope_type == "shot" and shot_id and binding.scope_id == shot_id:
            scoped.append(binding)
        elif binding.scope_type == "final_composition" and node_type == "final-composition":
            scoped.append(binding)
    return sorted(scoped, key=lambda binding: (binding.priority, binding.binding_id))


def binding_dicts_for_node(
    references: list[dict[str, Any]],
    *,
    node_id: str,
    node_type: str,
    item_id: str | None = None,
    shot_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        binding.model_dump(mode="json")
        for binding in asset_bindings_for_node(
            asset_bindings_from_references(references),
            node_id=node_id,
            node_type=node_type,
            item_id=item_id,
            shot_id=shot_id,
        )
    ]


def _binding_scopes(reference: dict[str, Any]) -> tuple[AssetBindingScope, list[str]]:
    metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
    shot_id = _first_text(
        reference,
        metadata,
        "target_shot_id",
        "shot_id",
        "storyboard_shot_id",
    )
    if shot_id:
        return "shot", [shot_id]
    item_id = _first_text(reference, metadata, "target_entity_id", "item_id", "target_item_id")
    if item_id:
        return "item", [item_id]
    final_id = _first_text(reference, metadata, "final_composition_id")
    if final_id or reference.get("target_node_id") == "final-composition":
        return "final_composition", [final_id or "final-composition"]
    node_ids = _target_node_ids(reference)
    if node_ids:
        return "node", node_ids
    return "global", [""]


def _target_node_ids(reference: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("target_node_id", "target_node_type"):
        value = reference.get(key)
        if isinstance(value, str) and value.strip():
            ids.append(value.strip())
    value = reference.get("target_node_ids")
    if isinstance(value, list):
        ids.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(ids))


def _reference_assets(reference: dict[str, Any]) -> list[dict[str, Any]]:
    assets = reference.get("assets")
    if isinstance(assets, list):
        return [asset for asset in assets if isinstance(asset, dict)]
    return []


def _reference_as_asset(reference: dict[str, Any]) -> dict[str, Any]:
    asset_ids = reference.get("asset_ids")
    asset_id = reference.get("asset_id")
    if not asset_id and isinstance(asset_ids, list) and asset_ids:
        asset_id = asset_ids[0]
    return {
        "asset_id": asset_id or "",
        "entity_id": reference.get("entity_id") or "",
        "media_type": reference.get("media_type") or reference.get("asset_type") or "",
        "asset_type": reference.get("asset_type") or reference.get("media_type") or "",
        "semantic_type": reference.get("semantic_type") or "",
        "local_path": reference.get("local_path") or reference.get("uri") or "",
        "metadata": reference.get("metadata")
        if isinstance(reference.get("metadata"), dict)
        else {},
    }


def _first_text(
    reference: dict[str, Any],
    metadata: dict[str, Any],
    *keys: str,
) -> str:
    for key in keys:
        for payload in (reference, metadata):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _binding_id(
    asset: dict[str, Any],
    scope_type: str,
    scope_id: str,
    reference_index: int,
    asset_index: int,
) -> str:
    asset_id = str(asset.get("asset_id") or f"asset-{reference_index}-{asset_index}")
    scope = scope_id or "global"
    return _slug(f"bind_{scope_type}_{scope}_{asset_id}")


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
