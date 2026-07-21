from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_creative_inventory import CreativeInventorySpec
from app.schemas.workflow_v2_intent import (
    V2_MAX_INTENT_INVENTORY_ITEMS,
    V2ExplicitCharacterConstraint,
    V2ExplicitConstraints,
    V2ExplicitSceneConstraint,
    V2IntentCharacter,
    V2IntentPlan,
    V2IntentProduct,
    V2IntentScene,
    V2IntentStoryboard,
)
from app.services.v2_creative_inventory import creative_inventory_from_intent
from app.services.v2_storyboard_planning import (
    V2_MAX_SHOT_DURATION_SECONDS,
    V2_MAX_STORYBOARD_SHOT_COUNT,
    V2_MIN_SHOT_DURATION_SECONDS,
    V2StoryboardPlanningResult,
)


InventorySource = Literal["explicit", "inferred", "default"]
TInventoryFact = TypeVar("TInventoryFact", bound=BaseModel)


class V2CreativeInventoryReconciliationError(RuntimeError):
    def __init__(
        self,
        message: str = "V2 creative inventory reconciliation failed.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = "v2_intent_reconciliation_failed"
        self.details = details or {}


@dataclass(frozen=True)
class V2CreativeInventoryReconciliationResult:
    intent_plan: V2IntentPlan
    creative_inventory: CreativeInventorySpec
    audit_metadata: dict[str, Any]
    clarification: V2StoryboardPlanningResult | None = None


class V2CreativeInventoryReconciler:
    def reconcile(
        self,
        request: WorkflowV2PlanFromPromptRequest,
        *,
        explicit_constraints: V2ExplicitConstraints,
        intent_plan: V2IntentPlan,
    ) -> V2CreativeInventoryReconciliationResult:
        repair_categories: list[str] = []
        default_categories: list[str] = []

        products, product_source, product_repaired = _reconcile_products(
            request,
            explicit_constraints,
            intent_plan.products,
        )
        if product_repaired:
            repair_categories.append("products")

        characters, character_source, character_repaired = _reconcile_characters(
            explicit_constraints,
            intent_plan,
        )
        if character_repaired:
            repair_categories.append("characters")
        if character_source == "default":
            default_categories.append("characters")

        storyboard, storyboard_source, storyboard_repaired = _reconcile_storyboard(
            request,
            explicit_constraints,
            intent_plan.storyboard,
        )
        if storyboard_repaired:
            repair_categories.append("storyboard_shots")
        if storyboard_source == "default":
            default_categories.append("storyboard_shots")

        scenes, scene_source, scene_repaired = _reconcile_scenes(
            explicit_constraints,
            intent_plan.scenes,
            shot_count=storyboard.shot_count,
        )
        if scene_repaired:
            repair_categories.append("scenes")
        if scene_source == "default":
            default_categories.append("scenes")

        storyboard, feasibility_repaired, clarification = _normalize_storyboard_feasibility(
            request,
            explicit_constraints,
            storyboard,
            scene_count=len(scenes),
        )
        if feasibility_repaired and "storyboard_shots" not in repair_categories:
            repair_categories.append("storyboard_shots")

        reconciled_intent = intent_plan.model_copy(
            update={
                "products": products,
                "characters": characters,
                "scenes": scenes,
                "storyboard": storyboard,
            },
            deep=True,
        )
        try:
            creative_inventory = creative_inventory_from_intent(reconciled_intent, request)
        except Exception as exc:
            raise V2CreativeInventoryReconciliationError(
                details={"stage": "creative_inventory_serialization"}
            ) from exc

        audit_metadata = {
            "reconciliation_version": "v2-creative-inventory-reconciliation-1",
            "category_sources": {
                "products": product_source,
                "characters": character_source,
                "scenes": scene_source,
                "storyboard_shots": storyboard_source,
            },
            "explicit_facts_applied": {
                "character_count": explicit_constraints.character_count,
                "character_fact_count": len(explicit_constraints.characters),
                "scene_count": explicit_constraints.scene_count,
                "scene_fact_count": len(explicit_constraints.scenes),
                "storyboard_shot_count": explicit_constraints.storyboard_shot_count,
            },
            "inferred_facts_retained": {
                "product_count": sum(item.source == "inferred" for item in products),
                "character_count": sum(item.source == "inferred" for item in characters),
                "scene_count": sum(item.source == "inferred" for item in scenes),
            },
            "defaults_used": default_categories,
            "repair_used": bool(repair_categories),
            "repaired_categories": repair_categories,
            "fallback_used": bool(default_categories),
            "canonical_storyboard_shot_count": storyboard.shot_count,
            "shot_count_clarification": (
                clarification.model_dump(mode="json") if clarification is not None else None
            ),
        }
        return V2CreativeInventoryReconciliationResult(
            intent_plan=reconciled_intent,
            creative_inventory=creative_inventory,
            audit_metadata=audit_metadata,
            clarification=clarification,
        )


def _reconcile_products(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
    products: list[V2IntentProduct],
) -> tuple[list[V2IntentProduct], InventorySource, bool]:
    valid_products = _valid_unique_items(products, "product_id")
    product_name = explicit_constraints.product_name or request.product_name
    if valid_products:
        product = valid_products[0]
        repaired = len(valid_products) != len(products) or len(valid_products) > 1
        if product_name and product.display_name != product_name:
            source_span = explicit_constraints.product_source_span
            product = product.model_copy(
                update={
                    "display_name": product_name,
                    "source": "explicit" if source_span else product.source,
                    "source_span": source_span or product.source_span,
                    "confidence": 0.98 if source_span else product.confidence,
                    "reason": (
                        "The product identity is grounded in the planning request."
                        if source_span
                        else product.reason
                    ),
                },
                deep=True,
            )
            repaired = True
        return [product], _fact_source(product), repaired

    if not product_name:
        raise V2CreativeInventoryReconciliationError(
            "A product identity is required for creative inventory reconciliation.",
            details={"missing_fields": ["product_name"]},
        )
    source_span = explicit_constraints.product_source_span
    product = V2IntentProduct(
        product_id="product-1",
        display_name=product_name,
        source="explicit" if source_span else "default",
        source_span=source_span,
        confidence=0.98 if source_span else 0.7,
        reason=(
            "The product identity is grounded in the planning request."
            if source_span
            else "The primary product is required by the workflow contract."
        ),
    )
    return [product], _fact_source(product), True


def _reconcile_characters(
    explicit_constraints: V2ExplicitConstraints,
    intent_plan: V2IntentPlan,
) -> tuple[list[V2IntentCharacter], InventorySource, bool]:
    original = list(intent_plan.characters)
    inferred = _valid_unique_items(original, "character_id")
    exact_count = explicit_constraints.character_count
    explicit_facts = list(explicit_constraints.characters)

    if exact_count is not None:
        characters = _characters_for_exact_count(inferred, explicit_facts, exact_count)
        return (
            characters,
            "explicit",
            _character_signature(characters) != _character_signature(original),
        )

    if inferred:
        characters = _merge_character_facts(inferred, explicit_facts)
        source: InventorySource = (
            "explicit"
            if characters and all(item.source == "explicit" for item in characters)
            else "inferred"
        )
        return (
            characters,
            source,
            _character_signature(characters) != _character_signature(original),
        )

    default_count = {
        "product_only": 0,
        "spokesperson_demo": 1,
        "lifestyle_narrative": 2,
        "unclassified": 1,
    }[intent_plan.concept_mode]
    count = max(default_count, len(explicit_facts))
    characters = [
        _default_character(
            index, explicit_facts[index - 1] if index <= len(explicit_facts) else None
        )
        for index in range(1, count + 1)
    ]
    return characters, "default", bool(original)


def _characters_for_exact_count(
    candidates: list[V2IntentCharacter],
    explicit_facts: list[V2ExplicitCharacterConstraint],
    count: int,
) -> list[V2IntentCharacter]:
    if count < 0 or count > V2_MAX_INTENT_INVENTORY_ITEMS:
        raise V2CreativeInventoryReconciliationError(
            details={"field": "character_count", "actual": count}
        )
    remaining = list(candidates)
    result: list[V2IntentCharacter] = []
    for index in range(1, count + 1):
        fact = explicit_facts[index - 1] if index <= len(explicit_facts) else None
        candidate = _take_matching_character(remaining, fact)
        result.append(_reconciled_character(candidate, fact, index, force_explicit=True))
    return _ensure_stable_character_ids(result)


def _merge_character_facts(
    candidates: list[V2IntentCharacter],
    explicit_facts: list[V2ExplicitCharacterConstraint],
) -> list[V2IntentCharacter]:
    result = list(candidates)
    used_indexes: set[int] = set()
    for fact in explicit_facts:
        match_index = next(
            (
                index
                for index, item in enumerate(result)
                if index not in used_indexes and (not fact.gender or item.gender == fact.gender)
            ),
            None,
        )
        if match_index is None:
            match_index = next(
                (index for index in range(len(result)) if index not in used_indexes),
                None,
            )
        if match_index is None:
            result.append(_default_character(len(result) + 1, fact))
            used_indexes.add(len(result) - 1)
            continue
        result[match_index] = _reconciled_character(
            result[match_index],
            fact,
            match_index + 1,
            force_explicit=False,
        )
        used_indexes.add(match_index)
    return _ensure_stable_character_ids(result)


def _take_matching_character(
    candidates: list[V2IntentCharacter],
    fact: V2ExplicitCharacterConstraint | None,
) -> V2IntentCharacter | None:
    if fact and fact.gender:
        for index, candidate in enumerate(candidates):
            if candidate.gender == fact.gender:
                return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _reconciled_character(
    candidate: V2IntentCharacter | None,
    fact: V2ExplicitCharacterConstraint | None,
    index: int,
    *,
    force_explicit: bool,
) -> V2IntentCharacter:
    if candidate is None:
        return _default_character(index, fact, force_explicit=force_explicit)
    if fact is None:
        if force_explicit and candidate.source != "explicit":
            return candidate.model_copy(
                update={
                    "source": "inferred",
                    "source_span": None,
                    "reason": "The character fills an explicit aggregate count.",
                },
                deep=True,
            )
        return candidate
    return candidate.model_copy(
        update={
            "gender": fact.gender or candidate.gender,
            "source": "explicit" if fact.source_span else candidate.source,
            "source_span": fact.source_span or candidate.source_span,
            "confidence": 0.98 if fact.source_span else candidate.confidence,
            "reason": (
                "The character attributes are grounded in the planning request."
                if fact.source_span
                else candidate.reason
            ),
        },
        deep=True,
    )


def _default_character(
    index: int,
    fact: V2ExplicitCharacterConstraint | None,
    *,
    force_explicit: bool = False,
) -> V2IntentCharacter:
    gender = fact.gender if fact else None
    source_span = fact.source_span if fact else None
    source: InventorySource = "explicit" if source_span else "default"
    if force_explicit and not source_span:
        source = "inferred"
    display_name = (
        "Male character"
        if gender == "male"
        else "Female character"
        if gender == "female"
        else f"Character {index}"
    )
    return V2IntentCharacter(
        character_id=f"character-{index}",
        display_name=display_name,
        gender=gender,
        role="lead" if index == 1 else "supporting",
        source=source,
        source_span=source_span,
        confidence=0.98 if source_span else 0.7,
        reason=(
            "The character is grounded in the planning request."
            if source_span
            else "The character follows the concept-mode fallback policy."
        ),
    )


def _ensure_stable_character_ids(
    characters: list[V2IntentCharacter],
) -> list[V2IntentCharacter]:
    seen: set[str] = set()
    result: list[V2IntentCharacter] = []
    for index, character in enumerate(characters, start=1):
        character_id = character.character_id
        if character_id in seen:
            character_id = _next_available_id("character", seen, index)
        seen.add(character_id)
        result.append(character.model_copy(update={"character_id": character_id}, deep=True))
    return result


def _reconcile_scenes(
    explicit_constraints: V2ExplicitConstraints,
    scenes: list[V2IntentScene],
    *,
    shot_count: int,
) -> tuple[list[V2IntentScene], InventorySource, bool]:
    original = list(scenes)
    inferred = _valid_unique_items(original, "scene_id")
    exact_count = explicit_constraints.scene_count
    explicit_facts = list(explicit_constraints.scenes)
    if exact_count is not None:
        result = _scenes_for_exact_count(inferred, explicit_facts, exact_count)
        return result, "explicit", _scene_signature(result) != _scene_signature(original)
    if inferred:
        result = _merge_scene_facts(inferred, explicit_facts)
        source: InventorySource = (
            "explicit"
            if result and all(item.source == "explicit" for item in result)
            else "inferred"
        )
        return result, source, _scene_signature(result) != _scene_signature(original)

    count = max(1, min(2, shot_count), len(explicit_facts))
    result = [
        _default_scene(index, explicit_facts[index - 1] if index <= len(explicit_facts) else None)
        for index in range(1, count + 1)
    ]
    return result, "default", bool(original)


def _scenes_for_exact_count(
    candidates: list[V2IntentScene],
    explicit_facts: list[V2ExplicitSceneConstraint],
    count: int,
) -> list[V2IntentScene]:
    if count < 1 or count > V2_MAX_INTENT_INVENTORY_ITEMS:
        raise V2CreativeInventoryReconciliationError(
            details={"field": "scene_count", "actual": count}
        )
    remaining = list(candidates)
    result: list[V2IntentScene] = []
    for index in range(1, count + 1):
        fact = explicit_facts[index - 1] if index <= len(explicit_facts) else None
        candidate = _take_matching_scene(remaining, fact)
        result.append(_reconciled_scene(candidate, fact, index, force_explicit=True))
    return _ensure_stable_scene_ids(result)


def _merge_scene_facts(
    candidates: list[V2IntentScene],
    explicit_facts: list[V2ExplicitSceneConstraint],
) -> list[V2IntentScene]:
    result = list(candidates)
    for fact in explicit_facts:
        match_index = next(
            (index for index, item in enumerate(result) if item.kind == fact.kind),
            None,
        )
        if match_index is None:
            result.append(_default_scene(len(result) + 1, fact))
            continue
        result[match_index] = _reconciled_scene(
            result[match_index], fact, match_index + 1, force_explicit=False
        )
    return _ensure_stable_scene_ids(result)


def _take_matching_scene(
    candidates: list[V2IntentScene],
    fact: V2ExplicitSceneConstraint | None,
) -> V2IntentScene | None:
    if fact:
        for index, candidate in enumerate(candidates):
            if candidate.kind == fact.kind:
                return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _reconciled_scene(
    candidate: V2IntentScene | None,
    fact: V2ExplicitSceneConstraint | None,
    index: int,
    *,
    force_explicit: bool,
) -> V2IntentScene:
    if candidate is None:
        return _default_scene(index, fact, force_explicit=force_explicit)
    if fact is None:
        if force_explicit and candidate.source != "explicit":
            return candidate.model_copy(
                update={
                    "source": "inferred",
                    "source_span": None,
                    "reason": "The scene fills an explicit aggregate count.",
                },
                deep=True,
            )
        return candidate
    return candidate.model_copy(
        update={
            "kind": fact.kind,
            "time_of_day": fact.time_of_day or candidate.time_of_day,
            "setting_type": fact.setting_type or candidate.setting_type,
            "source": "explicit",
            "source_span": fact.source_span,
            "confidence": 0.98,
            "reason": "The scene attributes are grounded in the planning request.",
        },
        deep=True,
    )


def _default_scene(
    index: int,
    fact: V2ExplicitSceneConstraint | None,
    *,
    force_explicit: bool = False,
) -> V2IntentScene:
    if fact:
        return V2IntentScene(
            scene_id=f"scene-{index}",
            display_name=_scene_display_name(fact.kind),
            kind=fact.kind,
            time_of_day=fact.time_of_day,
            setting_type=fact.setting_type,
            source="explicit",
            source_span=fact.source_span,
            confidence=0.98,
            reason="The scene is grounded in the planning request.",
        )
    kind = "product_lifestyle" if index == 1 else "urban_lifestyle"
    return V2IntentScene(
        scene_id=f"scene-{index}",
        display_name=_scene_display_name(kind),
        kind=kind,
        source="inferred" if force_explicit else "default",
        confidence=0.7,
        reason=(
            "The scene fills an explicit aggregate count."
            if force_explicit
            else "The scene count follows the storyboard fallback policy."
        ),
    )


def _ensure_stable_scene_ids(scenes: list[V2IntentScene]) -> list[V2IntentScene]:
    seen: set[str] = set()
    result: list[V2IntentScene] = []
    for index, scene in enumerate(scenes, start=1):
        scene_id = scene.scene_id
        if scene_id in seen:
            scene_id = _next_available_id("scene", seen, index)
        seen.add(scene_id)
        result.append(scene.model_copy(update={"scene_id": scene_id}, deep=True))
    return result


def _reconcile_storyboard(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
    storyboard: V2IntentStoryboard,
) -> tuple[V2IntentStoryboard, InventorySource, bool]:
    explicit_count = explicit_constraints.storyboard_shot_count
    if explicit_count is not None:
        source_span = explicit_constraints.storyboard_shot_count_span
        result = storyboard.model_copy(
            update={
                "shot_count": explicit_count,
                "source": "explicit" if source_span else "inferred",
                "source_span": source_span,
                "confidence": 0.98 if source_span else storyboard.confidence,
                "reason": "The storyboard shot count is grounded in the planning request.",
            },
            deep=True,
        )
        return result, "explicit", result != storyboard

    if (
        storyboard.source != "default"
        and 1 <= storyboard.shot_count <= V2_MAX_STORYBOARD_SHOT_COUNT
    ):
        return storyboard, _fact_source(storyboard), False

    shot_count = max(1, ceil(request.duration_seconds / V2_MAX_SHOT_DURATION_SECONDS))
    if shot_count > V2_MAX_STORYBOARD_SHOT_COUNT:
        raise V2CreativeInventoryReconciliationError(
            details={"field": "storyboard_shot_count", "actual": shot_count}
        )
    result = V2IntentStoryboard(
        shot_count=shot_count,
        source="default",
        confidence=0.7,
        reason="The storyboard count follows the requested duration and provider limit.",
    )
    return result, "default", result.shot_count != storyboard.shot_count


def _normalize_storyboard_feasibility(
    request: WorkflowV2PlanFromPromptRequest,
    explicit_constraints: V2ExplicitConstraints,
    storyboard: V2IntentStoryboard,
    *,
    scene_count: int,
) -> tuple[V2IntentStoryboard, bool, V2StoryboardPlanningResult | None]:
    shot_count = storyboard.shot_count
    explicit_shot_count = explicit_constraints.storyboard_shot_count is not None
    if explicit_shot_count:
        if shot_count < scene_count:
            return (
                storyboard,
                False,
                _shot_scene_coverage_clarification(shot_count, scene_count),
            )
        return storyboard, False, None

    minimum_for_duration = max(
        1,
        ceil(request.duration_seconds / V2_MAX_SHOT_DURATION_SECONDS),
    )
    maximum_for_duration = min(
        V2_MAX_STORYBOARD_SHOT_COUNT,
        max(1, request.duration_seconds // V2_MIN_SHOT_DURATION_SECONDS),
    )
    required_count = max(minimum_for_duration, scene_count)
    if required_count > maximum_for_duration:
        return (
            storyboard,
            False,
            _scene_duration_coverage_clarification(
                duration_seconds=request.duration_seconds,
                scene_count=scene_count,
                maximum_shot_count=maximum_for_duration,
            ),
        )
    applied_count = min(max(shot_count, required_count), maximum_for_duration)
    if applied_count == shot_count:
        return storyboard, False, None
    return (
        storyboard.model_copy(
            update={
                "shot_count": applied_count,
                "reason": (
                    "The inferred storyboard count was normalized for scene coverage "
                    "and provider duration limits."
                ),
            },
            deep=True,
        ),
        True,
        None,
    )


def _shot_scene_coverage_clarification(
    requested_shot_count: int,
    required_scene_count: int,
) -> V2StoryboardPlanningResult:
    return V2StoryboardPlanningResult(
        status="needs_clarification",
        error_code="storyboard_shot_count_not_supported",
        message=(
            "Each explicit scene requires at least one primary storyboard shot. "
            "Please increase the shot count or reduce the scene count."
        ),
        details={
            "reason": "storyboard_shot_count_below_scene_count",
            "requested_shot_count": requested_shot_count,
            "required_scene_count": required_scene_count,
        },
        suggested_actions=[
            {
                "action": "use_suggested_shot_count",
                "shot_count": required_scene_count,
                "label": f"Use {required_scene_count} shots",
            }
        ],
    )


def _scene_duration_coverage_clarification(
    *,
    duration_seconds: int,
    scene_count: int,
    maximum_shot_count: int,
) -> V2StoryboardPlanningResult:
    return V2StoryboardPlanningResult(
        status="needs_clarification",
        error_code="storyboard_shot_count_not_supported",
        message=(
            "The requested scene inventory cannot fit the storyboard duration limits. "
            "Please reduce the scene count or increase the duration."
        ),
        details={
            "reason": "storyboard_scene_duration_conflict",
            "requested_duration_seconds": duration_seconds,
            "required_scene_count": scene_count,
            "max_supported_shot_count": maximum_shot_count,
        },
        suggested_actions=[
            {
                "action": "reduce_scene_count",
                "scene_count": maximum_shot_count,
                "label": f"Use at most {maximum_shot_count} scenes",
            }
        ],
    )


def _valid_unique_items(
    items: list[TInventoryFact],
    id_field: str,
) -> list[TInventoryFact]:
    if not items or len(items) > V2_MAX_INTENT_INVENTORY_ITEMS:
        return []
    seen: set[str] = set()
    for item in items:
        item_id = str(getattr(item, id_field, "")).strip()
        display_name = str(getattr(item, "display_name", "")).strip()
        if not item_id or not display_name or item_id in seen:
            return []
        seen.add(item_id)
    return list(items)


def _fact_source(item: Any) -> InventorySource:
    source = getattr(item, "source", None)
    return source if source in {"explicit", "inferred", "default"} else "default"


def _next_available_id(prefix: str, seen: set[str], start: int) -> str:
    index = start
    while f"{prefix}-{index}" in seen:
        index += 1
    return f"{prefix}-{index}"


def _scene_display_name(kind: str) -> str:
    return f"{kind.replace('_', ' ').title()} Scene"


def _character_signature(items: list[V2IntentCharacter]) -> list[tuple[Any, ...]]:
    return [
        (
            item.character_id,
            item.display_name,
            item.gender,
            item.role,
            item.source,
            item.source_span,
        )
        for item in items
    ]


def _scene_signature(items: list[V2IntentScene]) -> list[tuple[Any, ...]]:
    return [
        (
            item.scene_id,
            item.display_name,
            item.kind,
            item.time_of_day,
            item.setting_type,
            item.source,
            item.source_span,
        )
        for item in items
    ]
