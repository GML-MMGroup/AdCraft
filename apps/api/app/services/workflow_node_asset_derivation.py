from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.asset_library_references import library_reference_derivation_metadata


def _trace_asset_reference_usage(
    settings: Settings,
    workflow_id: str,
    target_node_id: str,
    references: list[dict[str, Any]],
) -> None:
    if not references:
        return
    writer = AgentTraceWriter(settings.media_data_dir, workflow_id)
    now = utc_now()
    for reference in references:
        source_type = str(reference.get("source_type") or "asset_library")
        asset_ids = _dedupe_strings(reference.get("asset_ids") or [])
        if not asset_ids and reference.get("asset_id"):
            asset_ids = [str(reference.get("asset_id"))]
        for asset_id in asset_ids or [""]:
            writer.append(
                agent="Asset Reference",
                model=None,
                prompt=str(reference.get("mention_text") or reference.get("display_name") or ""),
                output=reference,
                error=None,
                started_at=now,
                finished_at=now,
                duration_ms=0,
                metadata={
                    "trace_role": "asset_reference",
                    "reference_source": source_type,
                    "entity_id": reference.get("entity_id"),
                    "asset_id": asset_id or reference.get("asset_id"),
                    "mention_text": reference.get("mention_text"),
                    "display_name": reference.get("display_name"),
                    "role": reference.get("role"),
                    "target_node_id": target_node_id,
                    "workflow_id": workflow_id,
                },
            )


def _dedupe_strings(values: list[Any]) -> list[str]:
    return [value for value in dict.fromkeys(str(item).strip() for item in values) if value]


def _apply_library_derivation_metadata(
    output: dict[str, Any],
    input_context: dict[str, Any],
    *,
    target_entity_id: str | None = None,
    target_asset_id: str | None = None,
) -> dict[str, Any]:
    derivation = library_reference_derivation_metadata(input_context)
    reference_policy = input_context.get("reference_policy")
    if not isinstance(reference_policy, dict):
        reference_policy = output.get("reference_policy")
    if not isinstance(reference_policy, dict):
        reference_policy = None
    if not any(derivation.values()) and reference_policy is None:
        return output
    updated = json.loads(json.dumps(output, ensure_ascii=False))
    _apply_derivation_to_output_assets(
        updated,
        derivation,
        reference_policy=reference_policy,
        target_entity_id=target_entity_id,
        target_asset_id=target_asset_id,
    )
    structured = updated.get("structured_output")
    if isinstance(structured, dict):
        _apply_derivation_to_structured_items(
            structured,
            derivation,
            reference_policy=reference_policy,
            target_entity_id=target_entity_id,
        )
    return updated


def _apply_derivation_to_output_assets(
    output: dict[str, Any],
    derivation: dict[str, list[str]],
    *,
    reference_policy: dict[str, Any] | None,
    target_entity_id: str | None,
    target_asset_id: str | None,
) -> None:
    for key in ("assets", "output_assets", "segments", "images", "videos", "audio"):
        value = output.get(key)
        if isinstance(value, list):
            for asset in value:
                if isinstance(asset, dict) and _derivation_asset_matches(
                    asset,
                    target_entity_id=target_entity_id,
                    target_asset_id=target_asset_id,
                ):
                    _merge_derivation_metadata(asset, derivation, reference_policy)
        elif isinstance(value, dict) and _derivation_asset_matches(
            value,
            target_entity_id=target_entity_id,
            target_asset_id=target_asset_id,
        ):
            _merge_derivation_metadata(value, derivation, reference_policy)
    if output.get("asset_id") and _derivation_asset_matches(
        output,
        target_entity_id=target_entity_id,
        target_asset_id=target_asset_id,
    ):
        _merge_derivation_metadata(output, derivation, reference_policy)


def _apply_derivation_to_structured_items(
    container: dict[str, Any],
    derivation: dict[str, list[str]],
    *,
    reference_policy: dict[str, Any] | None,
    target_entity_id: str | None,
) -> None:
    for value in container.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _derivation_item_matches(
                    item,
                    target_entity_id=target_entity_id,
                ):
                    _merge_derivation_metadata(item, derivation, reference_policy)
        elif isinstance(value, dict):
            _apply_derivation_to_structured_items(
                value,
                derivation,
                reference_policy=reference_policy,
                target_entity_id=target_entity_id,
            )


def _derivation_asset_matches(
    asset: dict[str, Any],
    *,
    target_entity_id: str | None,
    target_asset_id: str | None,
) -> bool:
    if target_asset_id and asset.get("asset_id") != target_asset_id:
        return False
    if target_entity_id and _metadata_entity_id(asset) != target_entity_id:
        return False
    return True


def _derivation_item_matches(item: dict[str, Any], *, target_entity_id: str | None) -> bool:
    if not target_entity_id:
        return True
    return _metadata_entity_id(item) == target_entity_id


def _metadata_entity_id(value: dict[str, Any]) -> str:
    for key in (
        "entity_id",
        "shotId",
        "shot_id",
        "sceneId",
        "scene_id",
        "roleId",
        "role_id",
        "characterId",
        "character_id",
        "id",
    ):
        item = value.get(key)
        if item not in (None, ""):
            return str(item)
    return ""


def _merge_derivation_metadata(
    item: dict[str, Any],
    derivation: dict[str, list[str]],
    reference_policy: dict[str, Any] | None,
) -> None:
    metadata = item.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        item["metadata"] = metadata
    for key, values in derivation.items():
        if not values:
            continue
        existing = metadata.get(key)
        existing_values = existing if isinstance(existing, list) else []
        metadata[key] = list(dict.fromkeys([*existing_values, *values]))
    if reference_policy is not None:
        metadata["reference_policy"] = reference_policy
