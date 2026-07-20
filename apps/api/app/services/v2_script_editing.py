from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from app.schemas.workflow_v2_creative_inventory import CreativeInventorySpec
from app.schemas.workflow_v2_integrity import V2PlanningConstraints
from app.schemas.workflow_v2_planning import (
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptScene,
)
from app.schemas.workflow_v2_screenplay import (
    V2EditableScriptDocument,
    V2ScriptDialogueLine,
    V2ScriptPlanV2,
    V2ScriptShotV2,
    V2ScriptStructuralDiff,
)
from app.services.v2_screenplay_renderer import V2ScreenplayRenderer


@dataclass(frozen=True)
class V2ScriptReconciliationResult:
    script: V2ScriptPlanV2
    structural_diff: V2ScriptStructuralDiff
    client_key_mapping: dict[str, str]


class V2ScriptEditError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.violations = violations or []
        super().__init__(message)


class V2ScriptEditReconciler:
    def reconcile(
        self,
        document: V2EditableScriptDocument,
        selected: V2ScriptPlanV2,
    ) -> V2ScriptReconciliationResult:
        mapping: dict[str, str] = {}
        existing = _existing_ids(selected)
        characters = [
            V2ScriptCharacter(
                character_id=_resolve_entity_id(
                    item.character_id,
                    item.client_key,
                    namespace="character",
                    existing=existing["character"],
                    seed=selected.script_version_id,
                    mapping=mapping,
                ),
                display_name=item.display_name,
                description=item.description,
                role=item.role,
                visual_notes=item.visual_notes,
                gender=item.gender,
            )
            for item in document.characters
        ]
        locations = [
            V2ScriptLocation(
                location_id=_resolve_entity_id(
                    item.location_id,
                    item.client_key,
                    namespace="location",
                    existing=existing["location"],
                    seed=selected.script_version_id,
                    mapping=mapping,
                ),
                display_name=item.display_name,
                description=item.description,
                visual_notes=item.visual_notes,
                location_type=item.location_type,
                time_of_day=item.time_of_day,
                setting_type=item.setting_type,
            )
            for item in document.locations
        ]
        scene_ids = [
            _resolve_entity_id(
                item.scene_id,
                item.client_key,
                namespace="scene",
                existing=existing["scene"],
                seed=selected.script_version_id,
                mapping=mapping,
            )
            for item in document.scenes
        ]
        known_characters = {item.character_id for item in characters}
        known_locations = {item.location_id for item in locations}
        known_scenes = set(scene_ids)
        shots: list[V2ScriptShotV2] = []
        scenes: list[V2ScriptScene] = []
        dialogue_ids: set[str] = set()
        shot_index = 0
        for scene_position, editable_scene in enumerate(document.scenes):
            scene_id = scene_ids[scene_position]
            location_id = _resolve_reference(
                editable_scene.location_id,
                mapping,
                known_locations,
                field=f"document.scenes.{scene_position}.location_id",
                optional=True,
            )
            scene_shots: list[V2ScriptShotV2] = []
            for local_index, editable_shot in enumerate(editable_scene.shots):
                shot_index += 1
                shot_id = _resolve_entity_id(
                    editable_shot.shot_id,
                    editable_shot.client_key,
                    namespace="shot",
                    existing=existing["shot"],
                    seed=selected.script_version_id,
                    mapping=mapping,
                )
                product_ids = list(editable_shot.product_ids)
                character_ids = [
                    _resolve_reference(
                        value,
                        mapping,
                        known_characters,
                        field=(
                            f"document.scenes.{scene_position}.shots.{local_index}.character_ids"
                        ),
                    )
                    for value in editable_shot.character_ids
                ]
                referenced_scenes = [
                    _resolve_reference(
                        value,
                        mapping,
                        known_scenes,
                        field=f"document.scenes.{scene_position}.shots.{local_index}.scene_ids",
                    )
                    for value in editable_shot.scene_ids
                ]
                if scene_id not in referenced_scenes:
                    referenced_scenes = [scene_id, *referenced_scenes]
                dialogue: list[V2ScriptDialogueLine] = []
                for dialogue_index, line in enumerate(editable_shot.dialogue):
                    dialogue_id = _resolve_entity_id(
                        line.dialogue_id,
                        line.client_key,
                        namespace="dialogue",
                        existing=existing["dialogue"],
                        seed=selected.script_version_id,
                        mapping=mapping,
                    )
                    if dialogue_id in dialogue_ids:
                        raise _invalid(
                            f"document.scenes.{scene_position}.shots.{local_index}.dialogue.{dialogue_index}.dialogue_id",
                            dialogue_id,
                            "Dialogue identity is duplicated.",
                        )
                    dialogue_ids.add(dialogue_id)
                    dialogue.append(
                        V2ScriptDialogueLine(
                            dialogue_id=dialogue_id,
                            character_id=_resolve_reference(
                                line.character_id,
                                mapping,
                                known_characters,
                                field=(
                                    f"document.scenes.{scene_position}.shots.{local_index}"
                                    f".dialogue.{dialogue_index}.character_id"
                                ),
                            ),
                            performance_cue=line.performance_cue,
                            text=line.text,
                        )
                    )
                shot = V2ScriptShotV2(
                    shot_id=shot_id,
                    scene_id=scene_id,
                    shot_index=shot_index,
                    product_ids=product_ids,
                    character_ids=character_ids,
                    scene_ids=referenced_scenes,
                    reference_item_ids=[*product_ids, *character_ids, *referenced_scenes],
                    description=editable_shot.description,
                    dialogue=dialogue,
                    narration=editable_shot.narration,
                    visual_prompt=editable_shot.visual_prompt,
                    duration_seconds=editable_shot.duration_seconds,
                )
                scene_shots.append(shot)
                shots.append(shot)
            scenes.append(
                V2ScriptScene(
                    scene_id=scene_id,
                    title=editable_scene.title,
                    description=editable_scene.description,
                    location_id=location_id,
                    shot_ids=[item.shot_id for item in scene_shots],
                    duration_seconds=sum(item.duration_seconds for item in scene_shots),
                    location_type=editable_scene.location_type,
                    time_of_day=editable_scene.time_of_day,
                    setting_type=editable_scene.setting_type,
                )
            )
        draft = V2ScriptPlanV2(
            **selected.model_dump(
                mode="python",
                exclude={
                    "script_text",
                    "script_title",
                    "language",
                    "characters",
                    "locations",
                    "scenes",
                    "shots",
                    "product_beats",
                    "tone",
                    "visual_style",
                    "duration_seconds",
                    "aspect_ratio",
                },
            ),
            script_text="",
            script_title=document.script_title,
            language=document.language,
            characters=characters,
            locations=locations,
            scenes=scenes,
            shots=shots,
            product_beats=document.product_beats,
            tone=document.tone,
            visual_style=document.visual_style,
            duration_seconds=sum(item.duration_seconds for item in shots),
            aspect_ratio=document.aspect_ratio,
        )
        script = draft.model_copy(
            update={"script_text": V2ScreenplayRenderer().render(draft)},
            deep=True,
        )
        return V2ScriptReconciliationResult(
            script=script,
            structural_diff=_structural_diff(selected, script),
            client_key_mapping=mapping,
        )


class V2ScriptContractValidator:
    def validate(
        self,
        plan: V2ScriptPlanV2,
        *,
        inventory: CreativeInventorySpec | None,
        hard_constraints: V2PlanningConstraints | None,
        explicit_constraints: dict[str, Any] | None = None,
    ) -> None:
        product_ids = {item.item_id for item in inventory.products} if inventory else set()
        for shot_index, shot in enumerate(plan.shots):
            for product_id in shot.product_ids:
                if inventory is not None and product_id not in product_ids:
                    raise V2ScriptEditError(
                        "unknown_script_reference",
                        "The screenplay contains an unknown product reference.",
                        violations=[
                            {
                                "field": f"document.shots.{shot_index}.product_ids",
                                "value": product_id,
                                "message": "Product references must resolve to canonical inventory IDs.",
                            }
                        ],
                    )
        violations: list[dict[str, Any]] = []
        if (
            hard_constraints is not None
            and hard_constraints.duration_seconds is not None
            and (plan.duration_seconds != hard_constraints.duration_seconds)
        ):
            violations.append(
                {
                    "field": "document.scenes.shots.duration_seconds",
                    "expected": hard_constraints.duration_seconds,
                    "actual": plan.duration_seconds,
                    "message": "Total shot duration conflicts with the locked workflow duration.",
                }
            )
        if (
            hard_constraints is not None
            and hard_constraints.aspect_ratio
            and plan.aspect_ratio != hard_constraints.aspect_ratio
        ):
            violations.append(
                {
                    "field": "document.aspect_ratio",
                    "expected": hard_constraints.aspect_ratio,
                    "actual": plan.aspect_ratio,
                    "message": "Aspect ratio conflicts with the locked workflow constraint.",
                }
            )
        explicit_constraints = explicit_constraints or {}
        count_constraints = (
            ("character_count", "document.characters", len(plan.characters), "Character"),
            ("scene_count", "document.scenes", len(plan.scenes), "Scene"),
            (
                "storyboard_shot_count",
                "document.scenes.shots",
                len(plan.shots),
                "Shot",
            ),
        )
        for key, field, actual, label in count_constraints:
            expected = explicit_constraints.get(key)
            if not isinstance(expected, int) or isinstance(expected, bool) or expected == actual:
                continue
            violations.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "message": f"{label} count conflicts with the explicit workflow constraint.",
                }
            )
        if violations:
            raise V2ScriptEditError(
                "explicit_constraint_conflict",
                "The screenplay conflicts with explicit workflow constraints.",
                violations=violations,
            )


def _existing_ids(plan: V2ScriptPlanV2) -> dict[str, set[str]]:
    return {
        "character": {item.character_id for item in plan.characters},
        "location": {item.location_id for item in plan.locations},
        "scene": {item.scene_id for item in plan.scenes},
        "shot": {item.shot_id for item in plan.shots},
        "dialogue": {line.dialogue_id for shot in plan.shots for line in shot.dialogue},
    }


def _resolve_entity_id(
    canonical_id: str | None,
    client_key: str | None,
    *,
    namespace: str,
    existing: set[str],
    seed: str,
    mapping: dict[str, str],
) -> str:
    if canonical_id:
        if canonical_id not in existing:
            raise _invalid(
                f"document.{namespace}_id",
                canonical_id,
                "Canonical identity does not exist in the selected screenplay.",
                code="unknown_script_reference",
            )
        return canonical_id
    assert client_key is not None
    mapping_key = f"{namespace}:{client_key}"
    if mapping_key in mapping:
        raise _invalid(
            f"document.{namespace}.client_key",
            client_key,
            "Client key is duplicated.",
        )
    digest = sha256(f"{seed}:{mapping_key}".encode("utf-8")).hexdigest()[:12]
    resolved = f"{namespace}-{digest}"
    if resolved in existing:
        raise _invalid(
            f"document.{namespace}.client_key",
            client_key,
            "Client key collides with an existing identity.",
        )
    mapping[mapping_key] = resolved
    mapping[client_key] = resolved
    return resolved


def _resolve_reference(
    value: str | None,
    mapping: dict[str, str],
    known: set[str],
    *,
    field: str,
    optional: bool = False,
) -> str | None:
    if value is None and optional:
        return None
    assert value is not None
    resolved = mapping.get(value, value)
    if resolved not in known:
        raise _invalid(
            field,
            value,
            "Reference does not resolve to an active screenplay identity.",
            code="unknown_script_reference",
        )
    return resolved


def _invalid(
    field: str,
    value: str,
    message: str,
    *,
    code: str = "invalid_script_document",
) -> V2ScriptEditError:
    return V2ScriptEditError(
        code,
        message,
        violations=[{"field": field, "value": value, "message": message}],
    )


def _structural_diff(old: V2ScriptPlanV2, new: V2ScriptPlanV2) -> V2ScriptStructuralDiff:
    old_maps = _entity_maps(old)
    new_maps = _entity_maps(new)
    values: dict[str, Any] = {}
    for namespace in ("character", "location", "scene", "shot", "dialogue"):
        old_ids = set(old_maps[namespace])
        new_ids = set(new_maps[namespace])
        values[f"added_{namespace}_ids"] = sorted(new_ids - old_ids)
        values[f"archived_{namespace}_ids"] = sorted(old_ids - new_ids)
        values[f"updated_{namespace}_ids"] = [
            item_id
            for item_id in new_maps[namespace]
            if item_id in old_maps[namespace]
            and _canonical_json(new_maps[namespace][item_id])
            != _canonical_json(old_maps[namespace][item_id])
        ]
    values["order_changed"] = _retained_order_changed(
        [item.scene_id for item in old.scenes],
        [item.scene_id for item in new.scenes],
    ) or _retained_order_changed(
        [item.shot_id for item in old.shots],
        [item.shot_id for item in new.shots],
    )
    return V2ScriptStructuralDiff.model_validate(values)


def structural_diff(old: V2ScriptPlanV2, new: V2ScriptPlanV2) -> V2ScriptStructuralDiff:
    return _structural_diff(old, new)


def _entity_maps(plan: V2ScriptPlanV2) -> dict[str, dict[str, Any]]:
    return {
        "character": {item.character_id: item for item in plan.characters},
        "location": {item.location_id: item for item in plan.locations},
        "scene": {item.scene_id: item for item in plan.scenes},
        "shot": {item.shot_id: item for item in plan.shots},
        "dialogue": {item.dialogue_id: item for shot in plan.shots for item in shot.dialogue},
    }


def _canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _retained_order_changed(old_ids: list[str], new_ids: list[str]) -> bool:
    old_set = set(old_ids)
    new_set = set(new_ids)
    return [item_id for item_id in old_ids if item_id in new_set] != [
        item_id for item_id in new_ids if item_id in old_set
    ]
