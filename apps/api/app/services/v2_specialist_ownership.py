from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.workflow_v2 import V2GenerationTarget
from app.schemas.workflow_v2_specialist_ownership import (
    V2SpecialistOwnedPlan,
    V2SpecialistOwnershipScope,
    V2SpecialistOwnershipValidationResult,
    V2SpecialistSlotPlan,
)


@dataclass(frozen=True)
class _ScopeDefinition:
    specialist: str
    node_types: tuple[str, ...] = ()
    item_types: tuple[str, ...] = ()
    slot_types: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    is_llm_specialist: bool = True
    free_output_media_types: tuple[str, ...] = ()

    @property
    def ownership_scope_id(self) -> str:
        if self.node_types and self.item_types:
            return f"{self.specialist}:{self.node_types[0]}:{self.item_types[0]}"
        return self.specialist


COMMON_PROMPT_ACTIONS = ("materialize_item_slots", "revise_prompt", "revise_and_generate")

_SCOPES: dict[str, _ScopeDefinition] = {
    "product_designer": _ScopeDefinition(
        specialist="product_designer",
        node_types=("product-generation",),
        item_types=("product",),
        slot_types=("product_main_image", "product_multi_view_grid"),
        actions=COMMON_PROMPT_ACTIONS,
    ),
    "character_designer": _ScopeDefinition(
        specialist="character_designer",
        node_types=("character-generation",),
        item_types=("character",),
        slot_types=("character_main_image", "character_three_view"),
        actions=COMMON_PROMPT_ACTIONS,
    ),
    "scene_designer": _ScopeDefinition(
        specialist="scene_designer",
        node_types=("scene-generation",),
        item_types=("scene",),
        slot_types=("scene_main_image", "scene_multi_view_grid"),
        actions=COMMON_PROMPT_ACTIONS,
    ),
    "storyboard_artist": _ScopeDefinition(
        specialist="storyboard_artist",
        node_types=("storyboard",),
        item_types=("shot",),
        slot_types=("shot_cell_1", "shot_cell_2", "shot_cell_3", "shot_cell_4"),
        actions=(
            "update_shot_summary",
            "materialize_shot_cells",
            "revise_prompt",
            "revise_and_generate",
            "materialize_item_slots",
        ),
    ),
    "video_director": _ScopeDefinition(
        specialist="video_director",
        node_types=("storyboard",),
        item_types=("shot",),
        slot_types=("shot_video_segment",),
        actions=("materialize_shot_video", "revise_prompt", "revise_and_generate"),
    ),
    "sound_director": _ScopeDefinition(
        specialist="sound_director",
        node_types=("bgm",),
        item_types=("bgm",),
        slot_types=("bgm_audio",),
        actions=COMMON_PROMPT_ACTIONS,
    ),
    "composition_tool": _ScopeDefinition(
        specialist="composition_tool",
        node_types=("final-composition",),
        item_types=("final_composition",),
        slot_types=("final_video",),
        actions=("build_timeline", "revise_timeline", "revise_prompt", "revise_and_generate"),
        is_llm_specialist=False,
    ),
    "quick_image_generator": _ScopeDefinition(
        specialist="quick_image_generator",
        slot_types=("free_output",),
        actions=("free_generate", "revise_prompt", "revise_and_generate"),
        free_output_media_types=("image",),
    ),
    "quick_video_generator": _ScopeDefinition(
        specialist="quick_video_generator",
        slot_types=("free_output",),
        actions=("free_generate", "revise_prompt", "revise_and_generate"),
        free_output_media_types=("video",),
    ),
    "quick_audio_generator": _ScopeDefinition(
        specialist="quick_audio_generator",
        slot_types=("free_output",),
        actions=("free_generate", "revise_prompt", "revise_and_generate"),
        free_output_media_types=("audio",),
    ),
}


def ownership_scope_for(specialist: str) -> V2SpecialistOwnershipScope | None:
    definition = _SCOPES.get(specialist)
    if definition is None:
        return None
    return V2SpecialistOwnershipScope(
        ownership_scope_id=definition.ownership_scope_id,
        specialist=definition.specialist,  # type: ignore[arg-type]
        node_types=list(definition.node_types),
        item_types=list(definition.item_types),
        slot_types=list(definition.slot_types),
        actions=list(definition.actions),
        is_llm_specialist=definition.is_llm_specialist,
        free_output_media_types=list(definition.free_output_media_types),
    )


def validate_specialist_slot_target(
    *,
    specialist: str,
    target: V2GenerationTarget,
    action: str | None = None,
    asset_owner_relation: dict[str, Any] | None = None,
) -> V2SpecialistOwnershipValidationResult:
    scope = ownership_scope_for(specialist)
    if scope is None:
        return _invalid(
            specialist,
            None,
            "agent_route_not_found",
            f"Specialist {specialist or '<missing>'} is not registered.",
        )
    violations = _target_violations(scope, target, action)
    violations.extend(_asset_owner_violations(target, asset_owner_relation))
    if violations:
        return _invalid(
            specialist,
            scope.ownership_scope_id,
            "specialist_ownership_violation",
            "; ".join(violations),
            violations=violations,
        )
    return V2SpecialistOwnershipValidationResult(
        valid=True,
        specialist=specialist,
        ownership_scope_id=scope.ownership_scope_id,
    )


def validate_specialist_owned_plan(
    plan: V2SpecialistOwnedPlan,
) -> V2SpecialistOwnershipValidationResult:
    scope = ownership_scope_for(plan.specialist)
    if scope is None:
        return _invalid(
            plan.specialist,
            None,
            "agent_route_not_found",
            f"Specialist {plan.specialist} is not registered.",
        )
    violations: list[str] = []
    if plan.action not in scope.actions:
        violations.append(f"action {plan.action} is not allowed for {plan.specialist}")
    if scope.node_types and plan.target_node_id and plan.target_node_id not in scope.node_types:
        violations.append(
            f"target node {plan.target_node_id} is outside {plan.specialist} ownership"
        )
    for slot_plan in plan.slot_plans:
        violations.extend(_slot_plan_violations(scope, plan, slot_plan))
    if violations:
        return _invalid(
            plan.specialist,
            scope.ownership_scope_id,
            "specialist_ownership_violation",
            "; ".join(violations),
            violations=violations,
        )
    return V2SpecialistOwnershipValidationResult(
        valid=True,
        specialist=plan.specialist,
        ownership_scope_id=scope.ownership_scope_id,
    )


def _target_violations(
    scope: V2SpecialistOwnershipScope,
    target: V2GenerationTarget,
    action: str | None,
) -> list[str]:
    violations: list[str] = []
    node_type = target.node_type or target.node_id
    item_type = target.item_type
    slot_type = target.slot_type
    if action and action not in scope.actions:
        if action == "materialize_item_slots" and scope.specialist == "video_director":
            action = "materialize_shot_video"
        else:
            violations.append(f"action {action} is not allowed for {scope.specialist}")
    if scope.free_output_media_types:
        if slot_type != "free_output":
            violations.append(f"slot {slot_type or '<missing>'} is not free_output")
        if target.media_type not in scope.free_output_media_types:
            violations.append(f"media_type {target.media_type or '<missing>'} is not allowed")
        return violations
    if scope.node_types and node_type and node_type not in scope.node_types:
        violations.append(
            f"node {node_type or '<missing>'} is outside {scope.specialist} ownership"
        )
    if scope.item_types and item_type and item_type not in scope.item_types:
        violations.append(
            f"item {item_type or '<missing>'} is outside {scope.specialist} ownership"
        )
    if scope.slot_types and slot_type and slot_type not in scope.slot_types:
        violations.append(
            f"slot {slot_type or '<missing>'} is outside {scope.specialist} ownership"
        )
    return violations


def _slot_plan_violations(
    scope: V2SpecialistOwnershipScope,
    plan: V2SpecialistOwnedPlan,
    slot_plan: V2SpecialistSlotPlan,
) -> list[str]:
    violations: list[str] = []
    if slot_plan.slot_type not in scope.slot_types:
        violations.append(
            f"slot plan {slot_plan.slot_id} has unsupported slot_type {slot_plan.slot_type}"
        )
    if slot_plan.item_id != plan.target_item_id:
        violations.append(
            f"slot plan {slot_plan.slot_id} belongs to {slot_plan.item_id}, expected {plan.target_item_id}"
        )
    if not slot_plan.slot_id.startswith(f"{slot_plan.item_id}:"):
        violations.append(
            f"slot plan {slot_plan.slot_id} does not belong to item {slot_plan.item_id}"
        )
    return violations


def _asset_owner_violations(
    target: V2GenerationTarget,
    relation: dict[str, Any] | None,
) -> list[str]:
    if target.target_type != "asset" or relation is None:
        return []
    checks = (
        ("target_node_id", target.node_id),
        ("target_item_id", target.item_id),
        ("target_slot_id", target.slot_id),
    )
    violations: list[str] = []
    for key, expected in checks:
        actual = relation.get(key)
        if expected and actual and actual != expected:
            violations.append(f"asset owner relation {key}={actual} does not match {expected}")
    return violations


def _invalid(
    specialist: str | None,
    ownership_scope_id: str | None,
    code: str,
    message: str,
    *,
    violations: list[str] | None = None,
) -> V2SpecialistOwnershipValidationResult:
    return V2SpecialistOwnershipValidationResult(
        valid=False,
        specialist=specialist,
        ownership_scope_id=ownership_scope_id,
        error_code=code,
        error_message=message,
        violations=list(violations or [message]),
    )
