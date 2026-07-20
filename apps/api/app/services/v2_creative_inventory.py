from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_creative_inventory import (
    CreativeCharacterInventoryItem,
    CreativeInventorySpec,
    CreativeProductInventoryItem,
    CreativeSceneInventoryItem,
)
from app.schemas.workflow_v2_intent import V2IntentPlan
from app.schemas.workflow_v2_planning import (
    V2CharacterBrief,
    V2ExpertBriefPlan,
    V2ProductBrief,
    V2SceneBrief,
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptPlan,
    V2ScriptScene,
)


def creative_inventory_from_intent(
    intent: V2IntentPlan,
    request: WorkflowV2PlanFromPromptRequest,
) -> CreativeInventorySpec:
    products = [
        CreativeProductInventoryItem(
            item_id=product.product_id,
            display_name=product.display_name,
            category=product.category or _product_category(product.display_name),
            source=product.source,
            source_text=product.source_span,
            confidence=product.confidence,
        )
        for product in intent.products
    ]
    characters = [
        CreativeCharacterInventoryItem(
            item_id=character.character_id,
            display_name=character.display_name,
            gender=character.gender,
            role=character.role,
            source=character.source,
            source_text=character.source_span,
            confidence=character.confidence,
        )
        for character in intent.characters
    ]
    scenes = [
        CreativeSceneInventoryItem(
            item_id=scene.scene_id,
            display_name=scene.display_name,
            location_type=_inventory_location_type(scene.kind),
            time_of_day=scene.time_of_day,
            setting_type=scene.setting_type,
            source=scene.source,
            source_text=scene.source_span,
            confidence=scene.confidence,
        )
        for scene in intent.scenes
    ]
    source_map = {
        "products": _intent_source_map(intent.products),
        "characters": _intent_source_map(intent.characters),
        "scenes": _intent_source_map(intent.scenes),
        "storyboard_shot_count": _intent_source_map([intent.storyboard]),
    }
    inventory = CreativeInventorySpec(
        inventory_id="inv_pending",
        products=products,
        characters=characters,
        scenes=scenes,
        storyboard_shot_count=intent.storyboard.shot_count,
        duration_seconds=request.duration_seconds,
        aspect_ratio=request.aspect_ratio,
        source_map=source_map,
        warnings=list(intent.warnings),
    )
    return inventory.model_copy(
        update={"inventory_id": _inventory_id(inventory)},
        deep=True,
    )


def creative_inventory_hash(inventory: CreativeInventorySpec) -> str:
    payload = inventory.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def creative_inventory_lineage(inventory: CreativeInventorySpec) -> dict[str, str]:
    return {
        "creative_inventory_id": inventory.inventory_id,
        "creative_inventory_hash": creative_inventory_hash(inventory),
        "creative_inventory_version": inventory.inventory_version,
    }


def creative_inventory_has_explicit_constraints(inventory: CreativeInventorySpec) -> bool:
    return any(
        (entry or {}).get("source") in {"explicit_user_prompt", "explicit"}
        for key, entry in inventory.source_map.items()
        if key in {"characters", "scenes", "storyboard_shot_count"}
    )


def creative_inventory_from_metadata(
    metadata: dict[str, Any] | None,
) -> CreativeInventorySpec | None:
    raw = (metadata or {}).get("creative_inventory_spec")
    if not isinstance(raw, dict):
        return None
    try:
        return CreativeInventorySpec.model_validate(raw)
    except Exception:
        return None


def apply_creative_inventory_to_script_plan(
    script_plan: V2ScriptPlan,
    inventory: CreativeInventorySpec,
) -> V2ScriptPlan:
    characters = _reconcile_script_characters(script_plan.characters, inventory.characters)
    scenes = _reconcile_script_scenes(script_plan.scenes, inventory.scenes)
    locations = _reconcile_script_locations(script_plan.locations, inventory.scenes)
    shots, coverage_repairs = _reconcile_script_shot_coverage(
        script_plan.shots,
        inventory,
        character_display_names={item.character_id: item.display_name for item in characters},
    )
    scenes = _apply_scene_shot_membership(scenes, shots)
    lineage = creative_inventory_lineage(inventory)
    repair_used = bool(coverage_repairs) or any(
        (
            [item.character_id for item in characters]
            != [item.character_id for item in script_plan.characters],
            [item.scene_id for item in scenes] != [item.scene_id for item in script_plan.scenes],
            [item.location_id for item in locations]
            != [item.location_id for item in script_plan.locations],
        )
    )
    fallback_used = any(
        isinstance(warning, dict) and warning.get("code") == "script_writer_fallback_used"
        for warning in script_plan.warnings
    )
    return script_plan.model_copy(
        update={
            "characters": characters,
            "scenes": scenes,
            "locations": locations,
            "shots": shots,
            "metadata": {
                **script_plan.metadata,
                **lineage,
                "creative_inventory_product_ids": [item.item_id for item in inventory.products],
                "creative_inventory_character_ids": [item.item_id for item in inventory.characters],
                "creative_inventory_scene_ids": [item.item_id for item in inventory.scenes],
                "script_inventory_reconciliation": {
                    "repair_used": repair_used,
                    "fallback_used": fallback_used,
                    "coverage_repairs": coverage_repairs,
                },
            },
        },
        deep=True,
    )


def apply_creative_inventory_to_expert_brief_plan(
    plan: V2ExpertBriefPlan,
    inventory: CreativeInventorySpec,
) -> V2ExpertBriefPlan:
    lineage = creative_inventory_lineage(inventory)
    product_briefs = _reconcile_product_briefs(plan.product_briefs, inventory.products, lineage)
    character_briefs = _reconcile_character_briefs(
        plan.character_briefs,
        inventory.characters,
        lineage,
    )
    scene_briefs = _reconcile_scene_briefs(plan.scene_briefs, inventory.scenes, lineage)
    return plan.model_copy(
        update={
            "metadata": {**plan.metadata, **lineage},
            "product_briefs": product_briefs,
            "character_briefs": character_briefs,
            "scene_briefs": scene_briefs,
            "bgm_brief": plan.bgm_brief.model_copy(
                update={"metadata": {**plan.bgm_brief.metadata, **lineage}},
                deep=True,
            ),
        },
        deep=True,
    )


def _reconcile_script_characters(
    candidates: list[V2ScriptCharacter],
    inventory: list[CreativeCharacterInventoryItem],
) -> list[V2ScriptCharacter]:
    unused = list(candidates)
    result: list[V2ScriptCharacter] = []
    for item in inventory:
        candidate = _take_character_candidate(unused, item)
        if candidate is None:
            result.append(_script_character_from_inventory(item))
            continue
        result.append(
            candidate.model_copy(
                update={
                    "character_id": item.item_id,
                    "gender": item.gender,
                    "description": _with_character_constraints(
                        candidate.description,
                        item,
                        field="description",
                    ),
                    "visual_notes": _with_character_constraints(
                        candidate.visual_notes,
                        item,
                        field="visual_notes",
                    ),
                },
                deep=True,
            )
        )
    return result


def _with_character_constraints(
    text: str,
    character: CreativeCharacterInventoryItem,
    *,
    field: str,
) -> str:
    if not character.gender or character.gender.casefold() in text.casefold():
        return text
    profile = _gender_profile(character.gender)[field]
    return f"{text} Authoritative gender: {character.gender}. {profile}"


def _take_character_candidate(
    candidates: list[V2ScriptCharacter],
    item: CreativeCharacterInventoryItem,
) -> V2ScriptCharacter | None:
    for index, candidate in enumerate(candidates):
        if candidate.character_id == item.item_id:
            return candidates.pop(index)
    normalized_name = item.display_name.casefold()
    for index, candidate in enumerate(candidates):
        if candidate.display_name.casefold() == normalized_name:
            return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _reconcile_script_scenes(
    candidates: list[V2ScriptScene],
    inventory: list[CreativeSceneInventoryItem],
) -> list[V2ScriptScene]:
    unused = list(candidates)
    result: list[V2ScriptScene] = []
    for item in inventory:
        candidate = _take_scene_candidate(unused, item)
        if candidate is None:
            result.append(
                V2ScriptScene(
                    scene_id=item.item_id,
                    title=item.display_name,
                    description=_scene_description(item),
                    location_id=item.item_id,
                    shot_ids=[],
                    duration_seconds=1,
                    location_type=item.location_type,
                    time_of_day=item.time_of_day,
                    setting_type=item.setting_type,
                )
            )
            continue
        result.append(
            candidate.model_copy(
                update={
                    "scene_id": item.item_id,
                    "location_id": item.item_id,
                    "description": _with_scene_constraints(candidate.description, item),
                    "location_type": item.location_type,
                    "time_of_day": item.time_of_day,
                    "setting_type": item.setting_type,
                },
                deep=True,
            )
        )
    return result


def _take_scene_candidate(
    candidates: list[V2ScriptScene],
    item: CreativeSceneInventoryItem,
) -> V2ScriptScene | None:
    for index, candidate in enumerate(candidates):
        if candidate.scene_id == item.item_id:
            return candidates.pop(index)
    normalized_name = item.display_name.casefold()
    for index, candidate in enumerate(candidates):
        if candidate.title.casefold() == normalized_name:
            return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _reconcile_script_locations(
    candidates: list[V2ScriptLocation],
    inventory: list[CreativeSceneInventoryItem],
) -> list[V2ScriptLocation]:
    unused = list(candidates)
    result: list[V2ScriptLocation] = []
    for item in inventory:
        candidate = _take_location_candidate(unused, item)
        if candidate is None:
            result.append(
                V2ScriptLocation(
                    location_id=item.item_id,
                    display_name=item.display_name,
                    description=_scene_description(item),
                    visual_notes=(
                        f"Preserve the {item.location_type} setting and its spatial identity."
                    ),
                    location_type=item.location_type,
                    time_of_day=item.time_of_day,
                    setting_type=item.setting_type,
                )
            )
            continue
        result.append(
            candidate.model_copy(
                update={
                    "location_id": item.item_id,
                    "description": _with_scene_constraints(candidate.description, item),
                    "visual_notes": _with_scene_constraints(candidate.visual_notes, item),
                    "location_type": item.location_type,
                    "time_of_day": item.time_of_day,
                    "setting_type": item.setting_type,
                },
                deep=True,
            )
        )
    return result


def _take_location_candidate(
    candidates: list[V2ScriptLocation],
    item: CreativeSceneInventoryItem,
) -> V2ScriptLocation | None:
    for index, candidate in enumerate(candidates):
        if candidate.location_id == item.item_id:
            return candidates.pop(index)
    normalized_name = item.display_name.casefold()
    for index, candidate in enumerate(candidates):
        if candidate.display_name.casefold() == normalized_name:
            return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _reconcile_script_shot_coverage(
    candidates: list[Any],
    inventory: CreativeInventorySpec,
    *,
    character_display_names: dict[str, str],
) -> tuple[list[Any], list[dict[str, Any]]]:
    product_ids = [item.item_id for item in inventory.products]
    character_ids = [item.item_id for item in inventory.characters]
    scene_ids = [item.item_id for item in inventory.scenes]
    allowed_products = set(product_ids)
    allowed_characters = set(character_ids)
    allowed_scenes = set(scene_ids)
    shots = []
    for index, shot in enumerate(candidates):
        selected_scene_ids = [item for item in shot.scene_ids if item in allowed_scenes]
        scene_id = shot.scene_id if shot.scene_id in allowed_scenes else None
        if scene_id is None:
            scene_id = (
                selected_scene_ids[0] if selected_scene_ids else scene_ids[index % len(scene_ids)]
            )
        shots.append(
            shot.model_copy(
                update={
                    "scene_id": scene_id,
                    "scene_ids": [scene_id],
                    "product_ids": [item for item in shot.product_ids if item in allowed_products],
                    "character_ids": [
                        item for item in shot.character_ids if item in allowed_characters
                    ],
                },
                deep=True,
            )
        )

    additions: dict[int, list[str]] = {}
    repairs: list[dict[str, Any]] = []
    _assign_missing_references(
        shots,
        field="product_ids",
        authoritative_ids=product_ids,
        display_names={item.item_id: item.display_name for item in inventory.products},
        additions=additions,
        repairs=repairs,
    )
    _assign_missing_references(
        shots,
        field="character_ids",
        authoritative_ids=character_ids,
        display_names=character_display_names,
        additions=additions,
        repairs=repairs,
    )
    _assign_missing_scenes(
        shots,
        scene_ids=scene_ids,
        display_names={item.item_id: item.display_name for item in inventory.scenes},
        additions=additions,
        repairs=repairs,
    )
    normalized = []
    for index, shot in enumerate(shots):
        added_names = additions.get(index, [])
        description = shot.description
        visual_prompt = shot.visual_prompt
        if added_names:
            joined = ", ".join(added_names)
            description = f"{description} Integrate {joined} into this complete story beat."
            visual_prompt = f"{visual_prompt} Show {joined} as part of the same coherent shot."
        references = list(dict.fromkeys([*shot.product_ids, *shot.character_ids, *shot.scene_ids]))
        normalized.append(
            shot.model_copy(
                update={
                    "description": description,
                    "visual_prompt": visual_prompt,
                    "reference_item_ids": references,
                },
                deep=True,
            )
        )
    return normalized, repairs


def _assign_missing_references(
    shots: list[Any],
    *,
    field: str,
    authoritative_ids: list[str],
    display_names: dict[str, str],
    additions: dict[int, list[str]],
    repairs: list[dict[str, Any]],
) -> None:
    used = {item for shot in shots for item in getattr(shot, field)}
    for item_id in [item for item in authoritative_ids if item not in used]:
        target_index = authoritative_ids.index(item_id) % len(shots)
        values = list(getattr(shots[target_index], field))
        values.append(item_id)
        shots[target_index] = shots[target_index].model_copy(
            update={field: list(dict.fromkeys(values))},
            deep=True,
        )
        additions.setdefault(target_index, []).append(display_names[item_id])
        repairs.append({"field": field, "item_id": item_id, "shot_id": shots[target_index].shot_id})


def _assign_missing_scenes(
    shots: list[Any],
    *,
    scene_ids: list[str],
    display_names: dict[str, str],
    additions: dict[int, list[str]],
    repairs: list[dict[str, Any]],
) -> None:
    used = {item for shot in shots for item in shot.scene_ids}
    for scene_id in [item for item in scene_ids if item not in used]:
        target_index = scene_ids.index(scene_id) % len(shots)
        shots[target_index] = shots[target_index].model_copy(
            update={"scene_id": scene_id, "scene_ids": [scene_id]},
            deep=True,
        )
        additions.setdefault(target_index, []).append(display_names[scene_id])
        repairs.append(
            {"field": "scene_ids", "item_id": scene_id, "shot_id": shots[target_index].shot_id}
        )


def _apply_scene_shot_membership(
    scenes: list[V2ScriptScene],
    shots: list[Any],
) -> list[V2ScriptScene]:
    return [
        scene.model_copy(
            update={
                "shot_ids": [shot.shot_id for shot in shots if scene.scene_id in shot.scene_ids],
                "duration_seconds": max(
                    1,
                    sum(
                        shot.duration_seconds for shot in shots if scene.scene_id in shot.scene_ids
                    ),
                ),
            },
            deep=True,
        )
        for scene in scenes
    ]


def _with_scene_constraints(text: str, scene: CreativeSceneInventoryItem) -> str:
    values = [scene.location_type, scene.time_of_day, scene.setting_type]
    required = [str(value) for value in values if value]
    normalized = text.casefold()
    missing = [value for value in required if value.casefold() not in normalized]
    if not missing:
        return text
    return f"{text} Authoritative setting: {', '.join(required)}."


def _reconcile_product_briefs(
    candidates: list[V2ProductBrief],
    inventory: list[CreativeProductInventoryItem],
    lineage: dict[str, str],
) -> list[V2ProductBrief]:
    unused = list(candidates)
    result: list[V2ProductBrief] = []
    for item in inventory:
        candidate = _take_brief_candidate(unused, item.item_id, item.display_name)
        if candidate is None:
            prompt = f"Define reusable product identity and selling-point references for {item.display_name}."
            candidate = V2ProductBrief(
                item_id=item.item_id,
                display_name=item.display_name,
                description=f"Authoritative product brief for {item.display_name}.",
                item_prompt=prompt,
                slot_prompts={
                    "product_main_image": (
                        f"Create one product-only main reference image for {item.display_name}."
                    ),
                    "product_multi_view_grid": (
                        f"Create one 2x2 multi-view product reference grid for {item.display_name}."
                    ),
                },
            )
        result.append(_brief_with_inventory(candidate, item.item_id, lineage))
    return result


def _reconcile_character_briefs(
    candidates: list[V2CharacterBrief],
    inventory: list[CreativeCharacterInventoryItem],
    lineage: dict[str, str],
) -> list[V2CharacterBrief]:
    unused = list(candidates)
    result: list[V2CharacterBrief] = []
    for item in inventory:
        candidate = _take_brief_candidate(unused, item.item_id, item.display_name)
        if candidate is None:
            prompt = (
                f"Define identity, wardrobe, silhouette, performance role, and emotion arc for "
                f"{item.display_name}."
            )
            candidate = V2CharacterBrief(
                item_id=item.item_id,
                display_name=item.display_name,
                description=f"Authoritative character brief for {item.display_name}.",
                item_prompt=prompt,
                slot_prompts={
                    "character_main_image": (
                        f"Create one full-frame character main reference for {item.display_name}."
                    ),
                    "character_three_view": (
                        f"Create a front, side, and back character reference for {item.display_name}."
                    ),
                },
            )
        result.append(_brief_with_inventory(candidate, item.item_id, lineage))
    return result


def _reconcile_scene_briefs(
    candidates: list[V2SceneBrief],
    inventory: list[CreativeSceneInventoryItem],
    lineage: dict[str, str],
) -> list[V2SceneBrief]:
    unused = list(candidates)
    result: list[V2SceneBrief] = []
    for item in inventory:
        candidate = _take_brief_candidate(unused, item.item_id, item.display_name)
        if candidate is None:
            prompt = (
                f"Define spatial layout, lighting, materials, time of day, and blocking for "
                f"{item.display_name}."
            )
            candidate = V2SceneBrief(
                item_id=item.item_id,
                display_name=item.display_name,
                description=_scene_description(item),
                item_prompt=prompt,
                slot_prompts={
                    "scene_main_image": (
                        f"Create one environment-only main reference for {item.display_name}."
                    ),
                    "scene_multi_view_grid": (
                        f"Create one 2x2 environment reference grid for {item.display_name}."
                    ),
                },
            )
        candidate = candidate.model_copy(
            update={
                "description": _with_scene_constraints(candidate.description, item),
                "item_prompt": _with_scene_constraints(candidate.item_prompt, item),
            },
            deep=True,
        )
        result.append(_brief_with_inventory(candidate, item.item_id, lineage))
    return result


def _take_brief_candidate(
    candidates: list[Any],
    item_id: str,
    display_name: str,
) -> Any | None:
    for index, candidate in enumerate(candidates):
        if candidate.item_id == item_id:
            return candidates.pop(index)
    normalized_name = display_name.casefold()
    for index, candidate in enumerate(candidates):
        if candidate.display_name.casefold() == normalized_name:
            return candidates.pop(index)
    return candidates.pop(0) if candidates else None


def _brief_with_inventory(brief: Any, item_id: str, lineage: dict[str, str]) -> Any:
    return brief.model_copy(
        update={
            "item_id": item_id,
            "metadata": {
                **brief.metadata,
                **lineage,
                "source_inventory_item_id": item_id,
            },
        },
        deep=True,
    )


def _product_category(product_name: str) -> str | None:
    normalized = product_name.lower()
    if "iphone" in normalized or "phone" in normalized:
        return "smartphone"
    return None


def _script_character_from_inventory(
    character: CreativeCharacterInventoryItem,
) -> V2ScriptCharacter:
    gender_profile = _gender_profile(character.gender)
    return V2ScriptCharacter(
        character_id=character.item_id,
        display_name=character.display_name,
        description=(
            f"{character.display_name} requested by creative inventory. "
            f"{gender_profile['description']}"
        ),
        role=character.role or "lead",
        visual_notes=(
            "Preserve the requested character inventory identity across the ad. "
            f"{gender_profile['visual_notes']}"
        ),
        gender=character.gender,
    )


def _gender_profile(gender: str | None) -> dict[str, str]:
    if gender == "male":
        return {
            "description": (
                "Male lead with tailored dark jacket, angular silhouette, short neat hair, "
                "composed analytical performance, and calm observation-driven reactions."
            ),
            "visual_notes": (
                "Wardrobe: structured jacket and clean shirt; hairstyle: short and tidy; "
                "silhouette: upright, crisp shoulders, restrained gestures."
            ),
        }
    if gender == "female":
        return {
            "description": (
                "Female lead with soft cream coat, flowing silhouette, shoulder-length styled hair, "
                "warm expressive performance, and decisive lifestyle-energy reactions."
            ),
            "visual_notes": (
                "Wardrobe: light coat and textured accessory; hairstyle: shoulder-length styled hair; "
                "silhouette: relaxed movement, expressive hands, warm posture."
            ),
        }
    return {
        "description": "Lead customer with distinct wardrobe, silhouette, hairstyle, and emotion arc.",
        "visual_notes": "Keep wardrobe, silhouette, hairstyle, and performance cues stable.",
    }


def _scene_description(scene: CreativeSceneInventoryItem) -> str:
    time_note = f" at {scene.time_of_day}" if scene.time_of_day else ""
    return (
        f"Requested {scene.location_type} scene{time_note} from creative inventory. "
        f"{_scene_profile(scene.location_type)}"
    )


def _scene_profile(location_type: str) -> str:
    profiles = {
        "office": (
            "Interior office workspace with desks, glass partitions, organized shelves, "
            "soft practical lighting, clean business surfaces, and product-friendly tabletop zones."
        ),
        "night street": (
            "Rain-polished urban street at night with neon signage, wet pavement reflections, "
            "storefront glow, deep perspective, and clear empty walking/composition lanes."
        ),
        "urban": (
            "City environment with architecture edges, sidewalk texture, storefront light, "
            "layered street depth, and premium travel-lifestyle atmosphere."
        ),
        "nature": (
            "Outdoor natural environment with organic foliage, open sky, textured ground, "
            "soft daylight, spacious movement paths, and calm lifestyle atmosphere."
        ),
    }
    return profiles.get(
        location_type,
        f"Distinct {location_type} environment with specific layout, lighting, material, and atmosphere cues.",
    )


def _inventory_id(inventory: CreativeInventorySpec) -> str:
    payload = inventory.model_dump(mode="json", exclude={"inventory_id"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "inv_" + sha256(encoded.encode("utf-8")).hexdigest()[:12]


def _intent_source_map(items: list[Any]) -> dict[str, Any]:
    if not items:
        return {"source": "default", "source_text": None}
    sources = {getattr(item, "source", None) for item in items}
    source = (
        "explicit" if "explicit" in sources else "inferred" if "inferred" in sources else "default"
    )
    spans = [
        getattr(item, "source_span", None) for item in items if getattr(item, "source_span", None)
    ]
    return {
        "source": source,
        "source_text": "; ".join(spans) if spans else None,
        "intent_source": ",".join(sorted(str(item) for item in sources if item)),
    }


def _inventory_location_type(scene_kind: str) -> str:
    if scene_kind == "night_street":
        return "night street"
    if scene_kind == "product_lifestyle":
        return "product lifestyle"
    return scene_kind.replace("_", " ")
