from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workflow_v2_creative_inventory import CreativeInventorySpec
from app.schemas.workflow_v2_planning import V2ScriptPlan
from app.schemas.workflow_v2_screenplay import V2ScriptPlanV2
from app.services.v2_creative_inventory import (
    apply_creative_inventory_to_script_plan,
    creative_inventory_lineage,
)
from app.services.v2_storyboard_planning import apply_storyboard_config_to_script_plan
from app.services.v2_screenplay_renderer import V2ScreenplayRenderer


class V2ScriptReconciliationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_version: Literal["v2-script-reconciliation-1"] = "v2-script-reconciliation-1"
    repair_used: bool
    fallback_used: bool
    original_error_code: str | None = None
    repair_codes: list[str] = Field(default_factory=list)
    dropped_reference_count: int = 0
    coverage_repairs: list[dict[str, Any]] = Field(default_factory=list)
    authoritative_inventory_lineage: dict[str, Any] = Field(default_factory=dict)


class V2ScriptReconciliationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_plan: V2ScriptPlan | V2ScriptPlanV2
    audit: V2ScriptReconciliationAudit
    warnings: list[dict[str, Any]] = Field(default_factory=list)


def reconcile_script_plan(
    draft: V2ScriptPlan | V2ScriptPlanV2,
    *,
    inventory: CreativeInventorySpec,
    storyboard_config: Mapping[str, Any],
) -> V2ScriptReconciliationResult:
    config = dict(storyboard_config)
    timed = apply_storyboard_config_to_script_plan(draft, config)
    preferred_scene_ids = _preferred_scene_ids(timed, inventory)
    reconciled = apply_creative_inventory_to_script_plan(timed, inventory)
    reconciled, coverage_repairs = _repair_primary_scene_coverage(
        reconciled,
        inventory,
        preferred_scene_ids=preferred_scene_ids,
    )

    dropped_reference_count = _unknown_reference_count(draft, inventory)
    repair_codes = _repair_codes(
        draft,
        reconciled,
        inventory=inventory,
        storyboard_config=config,
        dropped_reference_count=dropped_reference_count,
        coverage_repairs=coverage_repairs,
    )
    fallback_used = _fallback_used(draft)
    original_error_code = _fallback_error_code(draft) if fallback_used else None
    audit = V2ScriptReconciliationAudit(
        repair_used=bool(repair_codes),
        fallback_used=fallback_used,
        original_error_code=original_error_code,
        repair_codes=repair_codes,
        dropped_reference_count=dropped_reference_count,
        coverage_repairs=coverage_repairs,
        authoritative_inventory_lineage=creative_inventory_lineage(inventory),
    )
    warnings = []
    if dropped_reference_count:
        warnings.append(
            {
                "code": "script_unknown_reference_ids_removed",
                "count": dropped_reference_count,
            }
        )
    reconciled = reconciled.model_copy(
        update={
            "metadata": {
                **reconciled.metadata,
                "script_reconciliation": audit.model_dump(mode="json"),
            },
            "warnings": [*reconciled.warnings, *warnings],
        },
        deep=True,
    )
    if isinstance(reconciled, V2ScriptPlanV2):
        reconciled = V2ScreenplayRenderer().rendered_plan(reconciled)
    return V2ScriptReconciliationResult(
        script_plan=reconciled,
        audit=audit,
        warnings=warnings,
    )


def _preferred_scene_ids(
    plan: V2ScriptPlan | V2ScriptPlanV2,
    inventory: CreativeInventorySpec,
) -> list[str | None]:
    allowed = {item.item_id for item in inventory.scenes}
    return [shot.scene_id if shot.scene_id in allowed else None for shot in plan.shots]


def _repair_primary_scene_coverage(
    plan: V2ScriptPlan | V2ScriptPlanV2,
    inventory: CreativeInventorySpec,
    *,
    preferred_scene_ids: list[str | None],
) -> tuple[V2ScriptPlan | V2ScriptPlanV2, list[dict[str, Any]]]:
    authoritative_scene_ids = [item.item_id for item in inventory.scenes]
    if not authoritative_scene_ids:
        return plan, []

    assignments = [
        preferred_scene_ids[index]
        if index < len(preferred_scene_ids) and preferred_scene_ids[index]
        else shot.scene_id
        for index, shot in enumerate(plan.shots)
    ]
    assignments = [
        scene_id if scene_id in authoritative_scene_ids else authoritative_scene_ids[0]
        for scene_id in assignments
    ]
    counts = Counter(assignments)
    repairs: list[dict[str, Any]] = []
    for missing_scene_id in (
        scene_id for scene_id in authoritative_scene_ids if counts[scene_id] == 0
    ):
        target_index = next(
            (
                index
                for index in range(len(assignments) - 1, -1, -1)
                if counts[assignments[index]] > 1
            ),
            None,
        )
        if target_index is None:
            break
        previous_scene_id = assignments[target_index]
        assignments[target_index] = missing_scene_id
        counts[previous_scene_id] -= 1
        counts[missing_scene_id] += 1
        repairs.append(
            {
                "code": "scene_coverage_reassigned",
                "shot_id": plan.shots[target_index].shot_id,
                "scene_id": missing_scene_id,
            }
        )

    normalized_shots = []
    for shot, scene_id in zip(plan.shots, assignments, strict=True):
        references = list(dict.fromkeys([*shot.product_ids, *shot.character_ids, scene_id]))
        normalized_shots.append(
            shot.model_copy(
                update={
                    "scene_id": scene_id,
                    "scene_ids": [scene_id],
                    "reference_item_ids": references,
                },
                deep=True,
            )
        )
    normalized_scenes = [
        scene.model_copy(
            update={
                "shot_ids": [
                    shot.shot_id for shot in normalized_shots if shot.scene_id == scene.scene_id
                ],
                "duration_seconds": max(
                    1,
                    sum(
                        shot.duration_seconds
                        for shot in normalized_shots
                        if shot.scene_id == scene.scene_id
                    ),
                ),
            },
            deep=True,
        )
        for scene in plan.scenes
    ]
    return (
        plan.model_copy(
            update={
                "shots": normalized_shots,
                "scenes": normalized_scenes,
                "duration_seconds": sum(shot.duration_seconds for shot in normalized_shots),
            },
            deep=True,
        ),
        repairs,
    )


def _unknown_reference_count(
    draft: V2ScriptPlan | V2ScriptPlanV2,
    inventory: CreativeInventorySpec,
) -> int:
    allowed = {
        *(item.item_id for item in inventory.products),
        *(item.item_id for item in inventory.characters),
        *(item.item_id for item in inventory.scenes),
    }
    candidates = {
        *(item.character_id for item in draft.characters),
        *(item.scene_id for item in draft.scenes),
        *(item.location_id for item in draft.locations),
    }
    for shot in draft.shots:
        candidates.update(
            {
                shot.scene_id,
                *shot.product_ids,
                *shot.character_ids,
                *shot.scene_ids,
                *shot.reference_item_ids,
            }
        )
    return len({item for item in candidates if item and item not in allowed})


def _repair_codes(
    draft: V2ScriptPlan | V2ScriptPlanV2,
    reconciled: V2ScriptPlan | V2ScriptPlanV2,
    *,
    inventory: CreativeInventorySpec,
    storyboard_config: dict[str, Any],
    dropped_reference_count: int,
    coverage_repairs: list[dict[str, Any]],
) -> list[str]:
    codes: list[str] = []
    applied_shot_count = int(storyboard_config.get("applied_shot_count") or len(reconciled.shots))
    if len(draft.shots) != applied_shot_count:
        codes.append("shot_count_reconciled")
    if [shot.shot_id for shot in draft.shots] != [shot.shot_id for shot in reconciled.shots]:
        codes.append("shot_order_reconciled")
    if [shot.duration_seconds for shot in draft.shots] != [
        shot.duration_seconds for shot in reconciled.shots
    ]:
        codes.append("shot_duration_reconciled")
    if [item.character_id for item in draft.characters] != [
        item.item_id for item in inventory.characters
    ]:
        codes.append("character_ids_reconciled")
    if [item.scene_id for item in draft.scenes] != [item.item_id for item in inventory.scenes]:
        codes.append("scene_ids_reconciled")
    if [item.location_id for item in draft.locations] != [
        item.item_id for item in inventory.scenes
    ]:
        codes.append("location_ids_reconciled")
    if dropped_reference_count:
        codes.append("unknown_reference_ids_removed")
    if coverage_repairs:
        codes.append("scene_coverage_reconciled")
    if any(
        set(shot.reference_item_ids) != {*shot.product_ids, *shot.character_ids, *shot.scene_ids}
        for shot in draft.shots
    ):
        codes.append("reference_unions_rebuilt")
    return codes


def _fallback_used(draft: V2ScriptPlan | V2ScriptPlanV2) -> bool:
    return any(
        isinstance(warning, dict)
        and str(warning.get("code") or "")
        in {"script_writer_fallback_used", "structured_generation_fallback_used"}
        for warning in draft.warnings
    )


def _fallback_error_code(draft: V2ScriptPlan | V2ScriptPlanV2) -> str | None:
    for warning in draft.warnings:
        if not isinstance(warning, dict):
            continue
        value = str(warning.get("original_error_code") or "").strip()
        if value:
            return value
    return None
