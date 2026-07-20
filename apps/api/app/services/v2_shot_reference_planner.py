from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowV2
from app.services.v2_creative_inventory import creative_inventory_from_metadata


SHOT_REFERENCE_PLAN_VERSION = "v2-shot-reference-plan-1"
ShotReferenceSource = Literal["llm_structured", "repaired", "deterministic_fallback"]


@dataclass(frozen=True)
class V2ResolvedShotReferences:
    shot: dict[str, Any]
    reference_source: ShotReferenceSource
    warnings: list[dict[str, Any]]


def resolve_storyboard_shot_references(
    workflow: WorkflowV2,
    script_shots: list[dict[str, Any]],
) -> list[V2ResolvedShotReferences]:
    inventory = _reference_inventory(workflow)
    total = max(1, len(script_shots))
    resolved: list[V2ResolvedShotReferences] = []
    all_warnings = _inventory_count_warnings(
        workflow,
        inventory,
        shot_count=len(script_shots),
    )
    for index, source_shot in enumerate(script_shots, start=1):
        result = _resolve_one_shot(
            source_shot,
            index=index,
            total=total,
            inventory=inventory,
        )
        resolved.append(result)
        all_warnings.extend(result.warnings)
    workflow.metadata["shot_reference_plan"] = {
        "reference_plan_version": SHOT_REFERENCE_PLAN_VERSION,
        "workflow_id": workflow.workflow_id,
        "shot_count": len(resolved),
        "shots": [
            {
                "shot_id": result.shot.get("shot_id"),
                "shot_index": result.shot.get("shot_index"),
                "scene_id": result.shot.get("scene_id"),
                "product_ids": result.shot.get("product_ids", []),
                "character_ids": result.shot.get("character_ids", []),
                "scene_ids": result.shot.get("scene_ids", []),
                "reference_item_ids": result.shot.get("reference_item_ids", []),
                "reference_source": result.reference_source,
            }
            for result in resolved
        ],
        "warnings": _dedupe_warnings(all_warnings),
    }
    _sync_script_plan_metadata(workflow, [result.shot for result in resolved])
    return resolved


def reference_dependency_slot_ids(workflow: WorkflowV2, reference_item_ids: list[str]) -> list[str]:
    slots: list[str] = []
    for item_id in reference_item_ids:
        item = _find_item_by_id(workflow, item_id)
        if item is None:
            continue
        slot_type = _main_slot_type_for_item(item)
        if slot_type is None:
            continue
        slots.append(f"{item.item_id}:{slot_type}")
    return list(dict.fromkeys(slots))


def _resolve_one_shot(
    source_shot: dict[str, Any],
    *,
    index: int,
    total: int,
    inventory: dict[str, list[str]],
) -> V2ResolvedShotReferences:
    shot = dict(source_shot)
    warnings: list[dict[str, Any]] = []
    requested_scene_id = str(shot.get("scene_id") or "").strip()
    valid_ids = {item_id for ids in inventory.values() for item_id in ids}
    explicit_unknowns: list[str] = []
    product_ids = _valid_ids(
        [*_string_list(shot.get("product_ids")), *_refs_by_prefix(shot, "product-")],
        inventory["products"],
        unknowns=explicit_unknowns,
        valid_ids=valid_ids,
    )
    character_ids = _valid_ids(
        [*_string_list(shot.get("character_ids")), *_refs_by_prefix(shot, "character-")],
        inventory["characters"],
        unknowns=explicit_unknowns,
        valid_ids=valid_ids,
    )
    scene_ids = _valid_ids(
        [
            *_string_list(shot.get("scene_ids")),
            *([str(shot["scene_id"]).strip()] if str(shot.get("scene_id") or "").strip() else []),
            *_refs_by_prefix(shot, "scene-"),
        ],
        inventory["scenes"],
        unknowns=explicit_unknowns,
        valid_ids=valid_ids,
    )
    had_valid_structured = bool(product_ids or character_ids or scene_ids)
    used_fallback = False
    if not product_ids and inventory["products"] and not _shot_is_product_free(shot):
        product_ids = list(inventory["products"])
        used_fallback = True
    if not character_ids and inventory["characters"]:
        character_ids = _fallback_character_ids(inventory["characters"], index=index, total=total)
        used_fallback = True
    if not scene_ids and inventory["scenes"]:
        scene_ids = [inventory["scenes"][(index - 1) % len(inventory["scenes"])]]
        used_fallback = True
    if explicit_unknowns:
        warnings.append(
            {
                "code": "shot_reference_unknown_item_repaired",
                "shot_id": str(shot.get("shot_id") or f"shot-{index}"),
                "unknown_item_ids": list(dict.fromkeys(explicit_unknowns)),
                "message": "Unknown storyboard reference item ids were replaced with valid inventory ids.",
            }
        )
    if used_fallback:
        warnings.append(
            {
                "code": "shot_reference_fallback_used",
                "shot_id": str(shot.get("shot_id") or f"shot-{index}"),
                "message": "Storyboard shot references were completed from deterministic inventory fallback.",
            }
        )
    reference_source: ShotReferenceSource
    if explicit_unknowns or (used_fallback and had_valid_structured):
        reference_source = "repaired"
    elif used_fallback:
        reference_source = "deterministic_fallback"
    else:
        reference_source = "llm_structured"
    scene_id = (
        requested_scene_id
        if requested_scene_id in inventory["scenes"]
        else (scene_ids[0] if scene_ids else requested_scene_id)
    )
    if scene_id and scene_ids != [scene_id]:
        warnings.append(
            {
                "code": "shot_scene_reference_normalized",
                "shot_id": str(shot.get("shot_id") or f"shot-{index}"),
                "primary_scene_item_id": scene_id,
                "removed_scene_ids": [item_id for item_id in scene_ids if item_id != scene_id],
                "message": "Storyboard shot scene references were normalized to one primary scene.",
            }
        )
    scene_ids = [scene_id] if scene_id else []
    shot.update(
        {
            "scene_id": scene_id,
            "product_ids": list(dict.fromkeys(product_ids)),
            "character_ids": list(dict.fromkeys(character_ids)),
            "scene_ids": scene_ids,
            "reference_item_ids": list(dict.fromkeys([*product_ids, *character_ids, *scene_ids])),
            "reference_source": reference_source,
            "reference_warnings": warnings,
        }
    )
    return V2ResolvedShotReferences(
        shot=shot,
        reference_source=reference_source,
        warnings=warnings,
    )


def _reference_inventory(workflow: WorkflowV2) -> dict[str, list[str]]:
    canonical = creative_inventory_from_metadata(workflow.metadata)
    if canonical is not None:
        return {
            "products": [item.item_id for item in canonical.products],
            "characters": [item.item_id for item in canonical.characters],
            "scenes": [item.item_id for item in canonical.scenes],
        }
    return {
        "products": _item_ids(workflow, "product-generation", "product"),
        "characters": _item_ids(workflow, "character-generation", "character"),
        "scenes": _item_ids(workflow, "scene-generation", "scene"),
    }


def _inventory_count_warnings(
    workflow: WorkflowV2,
    inventory: dict[str, list[str]],
    *,
    shot_count: int,
) -> list[dict[str, Any]]:
    constraints = workflow.metadata.get("planning_constraints")
    if not isinstance(constraints, dict):
        return []
    expected_by_type = {
        "products": _optional_int(constraints.get("requested_product_count")),
        "characters": _optional_int(constraints.get("requested_character_count")),
        "scenes": _optional_int(constraints.get("requested_scene_count")),
        "shots": _optional_int(constraints.get("requested_shot_count")),
    }
    actual_by_type = {
        "products": len(inventory["products"]),
        "characters": len(inventory["characters"]),
        "scenes": len(inventory["scenes"]),
        "shots": shot_count,
    }
    warnings: list[dict[str, Any]] = []
    for inventory_type, expected in expected_by_type.items():
        if expected is None:
            continue
        actual = actual_by_type[inventory_type]
        if expected == actual:
            continue
        warnings.append(
            {
                "code": "shot_reference_inventory_count_mismatch",
                "inventory_type": inventory_type,
                "expected_count": expected,
                "actual_count": actual,
                "message": "Storyboard reference inventory count does not match planning constraints.",
            }
        )
    return warnings


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _item_ids(workflow: WorkflowV2, node_id: str, item_type: str) -> list[str]:
    node = next((node for node in workflow.nodes if node.node_id == node_id), None)
    if node is None:
        return []
    return [
        item.item_id
        for item in node.items
        if item.lifecycle_state == "active" and item.item_type == item_type
    ]


def _find_item_by_id(workflow: WorkflowV2, item_id: str) -> WorkflowItemV2 | None:
    for node in workflow.nodes:
        for item in node.items:
            if item.lifecycle_state == "active" and item.item_id == item_id:
                return item
    return None


def _main_slot_type_for_item(item: WorkflowItemV2) -> str | None:
    if item.item_type == "product":
        return "product_main_image"
    if item.item_type == "character":
        return "character_main_image"
    if item.item_type == "scene":
        return "scene_main_image"
    return None


def _refs_by_prefix(shot: dict[str, Any], prefix: str) -> list[str]:
    return [
        item_id
        for item_id in _string_list(shot.get("reference_item_ids"))
        if item_id.startswith(prefix)
    ]


def _valid_ids(
    values: list[str],
    allowed: list[str],
    *,
    unknowns: list[str],
    valid_ids: set[str],
) -> list[str]:
    allowed_set = set(allowed)
    result: list[str] = []
    for value in values:
        if value in allowed_set:
            result.append(value)
        elif value and value not in valid_ids:
            unknowns.append(value)
    return list(dict.fromkeys(result))


def _fallback_character_ids(characters: list[str], *, index: int, total: int) -> list[str]:
    if len(characters) <= 1:
        return list(characters)
    if total > len(characters) and index == total:
        return list(characters)
    return [characters[(index - 1) % len(characters)]]


def _shot_is_product_free(shot: dict[str, Any]) -> bool:
    value = shot.get("product_free") or shot.get("is_product_free")
    if isinstance(value, bool):
        return value
    text = " ".join(str(shot.get(key) or "") for key in ("description", "visual_prompt")).lower()
    return "product-free" in text or "no product" in text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(item).strip() for item in value) if item]


def _sync_script_plan_metadata(workflow: WorkflowV2, shots: list[dict[str, Any]]) -> None:
    script_plan = workflow.metadata.get("script_plan")
    if not isinstance(script_plan, dict):
        return
    canonical_fields = {
        "shot_id",
        "scene_id",
        "shot_index",
        "product_ids",
        "character_ids",
        "scene_ids",
        "reference_item_ids",
        "description",
        "dialogue",
        "narration",
        "visual_prompt",
        "duration_seconds",
    }
    workflow.metadata["script_plan"] = {
        **script_plan,
        "shots": [
            {key: value for key, value in shot.items() if key in canonical_fields} for shot in shots
        ],
    }


def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in warnings:
        key = repr(sorted(warning.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(warning)
    return result
