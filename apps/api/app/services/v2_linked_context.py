from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.schemas.workflow_v2_screenplay import (
    V2LinkedContextSummary,
    V2ScriptPlanV2,
    V2ScriptStructuralDiff,
)
from app.services.v2_shot_reference_planner import reference_dependency_slot_ids
from app.services.v2_specialist_handoff import V2ScreenplaySliceBuilder
from app.services.v2_storyboard_defaults import shot_cell_slot_types
from app.services.v2_workflow_planner import build_slot


_LINKED_CONTRACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class V2LinkedContextResult:
    workflow: WorkflowV2
    structural_diff: V2ScriptStructuralDiff
    summary: V2LinkedContextSummary


class V2LinkedContextSynchronizer:
    def __init__(self) -> None:
        self._slices = V2ScreenplaySliceBuilder()

    def preview(
        self,
        workflow: WorkflowV2,
        old_script: V2ScriptPlanV2,
        new_script: V2ScriptPlanV2,
        diff: V2ScriptStructuralDiff,
    ) -> V2LinkedContextResult:
        candidate = workflow.model_copy(deep=True)
        updated_nodes: set[str] = set()
        updated_items: set[str] = set()
        updated_slots: set[str] = set()
        reactivated: dict[str, list[str]] = {
            "character": [],
            "scene": [],
            "shot": [],
        }
        affected = _affected_ids(old_script, new_script, diff)
        self._sync_script_item(candidate, new_script, updated_nodes, updated_items)
        self._sync_products(
            candidate,
            new_script,
            affected["product"],
            updated_nodes,
            updated_items,
            updated_slots,
        )
        self._sync_characters(
            candidate,
            new_script,
            affected["character"],
            updated_nodes,
            updated_items,
            updated_slots,
            reactivated,
        )
        self._sync_scenes(
            candidate,
            new_script,
            affected["scene"],
            updated_nodes,
            updated_items,
            updated_slots,
            reactivated,
        )
        self._sync_storyboard(
            candidate,
            new_script,
            affected["shot"],
            updated_nodes,
            updated_items,
            updated_slots,
            reactivated,
        )
        self._sync_bgm(
            candidate,
            new_script,
            changed=affected["bgm"],
            updated_nodes=updated_nodes,
            updated_items=updated_items,
            updated_slots=updated_slots,
        )
        adjusted_diff = _with_reactivated(diff, reactivated)
        summary = V2LinkedContextSummary(
            updated_node_ids=sorted(updated_nodes),
            updated_item_ids=sorted(updated_items),
            updated_slot_ids=sorted(updated_slots),
            updated_fields=[
                "system_suggested_prompt",
                "screenplay_slice",
                "system_reference_ids",
            ]
            if updated_items
            else [],
            refresh=["workflow", "slot_prompts", "references"] if updated_items else [],
        )
        return V2LinkedContextResult(
            workflow=candidate,
            structural_diff=adjusted_diff,
            summary=summary,
        )

    def synchronize(
        self,
        workflow: WorkflowV2,
        old_script: V2ScriptPlanV2,
        new_script: V2ScriptPlanV2,
        diff: V2ScriptStructuralDiff,
    ) -> V2LinkedContextResult:
        return self.preview(workflow, old_script, new_script, diff)

    def _sync_script_item(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        updated_nodes: set[str],
        updated_items: set[str],
    ) -> None:
        node = _node(workflow, "script")
        if node is None or not node.items:
            return
        item = node.items[0]
        suggestion = (
            f"{script.script_title}. Tone: {script.tone}. "
            f"Scenes: {len(script.scenes)}, shots: {len(script.shots)}."
        )
        _set_system_item_prompt(item, suggestion)
        item.description = script.script_title
        item.metadata.update(
            {
                "script_text": script.script_text,
                "script_brief_id": script.script_brief_id,
                "script_version_id": script.script_version_id,
                "script_plan_version": script.script_plan_version,
            }
        )
        updated_nodes.add(node.node_id)
        updated_items.add(item.item_id)

    def _sync_characters(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        affected_ids: set[str],
        updated_nodes: set[str],
        updated_items: set[str],
        updated_slots: set[str],
        reactivated: dict[str, list[str]],
    ) -> None:
        node = _node(workflow, "character-generation")
        if node is None:
            return
        desired = {item.character_id: item for item in script.characters}
        _archive_missing(node.items, set(desired), updated_items, updated_slots)
        for character_id, character in desired.items():
            item = _active_item(node.items, character_id)
            created = False
            if item is None:
                expected = _new_character_item(character, script)
                archived = _archived_item(node.items, character_id)
                if archived is not None and _item_contract_matches(archived, expected):
                    item = archived
                    item.lifecycle_state = "active"
                    reactivated["character"].append(character_id)
                else:
                    item = expected
                    node.items.append(item)
                    created = True
            if (
                not created
                and character_id not in affected_ids
                and character_id not in reactivated["character"]
            ):
                continue
            item.display_name = character.display_name
            item.description = character.description
            suggestion = _character_system_prompt(character)
            _set_system_item_prompt(item, suggestion)
            self._update_item_context(workflow, script, item, "character", suggestion)
            updated_items.add(item.item_id)
            updated_slots.update(slot.slot_id for slot in item.slots)
        if desired:
            node.metadata.pop("execution_disposition", None)
            node.metadata.pop("reason_code", None)
        updated_nodes.add(node.node_id)

    def _sync_scenes(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        affected_ids: set[str],
        updated_nodes: set[str],
        updated_items: set[str],
        updated_slots: set[str],
        reactivated: dict[str, list[str]],
    ) -> None:
        node = _node(workflow, "scene-generation")
        if node is None:
            return
        desired = {item.scene_id: item for item in script.scenes}
        _archive_missing(node.items, set(desired), updated_items, updated_slots)
        for scene_id, scene in desired.items():
            item = _active_item(node.items, scene_id)
            created = False
            if item is None:
                expected = _new_scene_item(scene, script)
                archived = _archived_item(node.items, scene_id)
                if archived is not None and _item_contract_matches(archived, expected):
                    item = archived
                    item.lifecycle_state = "active"
                    reactivated["scene"].append(scene_id)
                else:
                    item = expected
                    node.items.append(item)
                    created = True
            if (
                not created
                and scene_id not in affected_ids
                and scene_id not in reactivated["scene"]
            ):
                continue
            item.display_name = scene.title
            item.description = scene.description
            suggestion = _scene_system_prompt(scene)
            _set_system_item_prompt(item, suggestion)
            self._update_item_context(workflow, script, item, "scene", suggestion)
            updated_items.add(item.item_id)
            updated_slots.update(slot.slot_id for slot in item.slots)
        updated_nodes.add(node.node_id)

    def _sync_storyboard(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        affected_ids: set[str],
        updated_nodes: set[str],
        updated_items: set[str],
        updated_slots: set[str],
        reactivated: dict[str, list[str]],
    ) -> None:
        node = _node(workflow, "storyboard")
        if node is None:
            return
        desired = {shot.shot_id: shot for shot in script.shots}
        _archive_missing(node.items, set(desired), updated_items, updated_slots)
        ordered: list[WorkflowItemV2] = []
        for shot in script.shots:
            item = _active_item(node.items, shot.shot_id)
            created = False
            if item is None:
                expected = _new_storyboard_item(workflow, shot, script)
                archived = _archived_item(node.items, shot.shot_id)
                if archived is not None and _item_contract_matches(archived, expected):
                    item = archived
                    item.lifecycle_state = "active"
                    reactivated["shot"].append(shot.shot_id)
                else:
                    item = expected
                    node.items.append(item)
                    created = True
            if (
                not created
                and shot.shot_id not in affected_ids
                and shot.shot_id not in reactivated["shot"]
            ):
                ordered.append(item)
                continue
            item.shot_id = shot.shot_id
            item.shot_index = shot.shot_index
            item.display_name = f"Shot {shot.shot_index}"
            item.description = shot.description
            item.duration_seconds = shot.duration_seconds
            item.aspect_ratio = script.aspect_ratio
            item.reference_item_ids = list(shot.reference_item_ids)
            item.primary_scene_item_id = shot.scene_id
            suggestion = shot.description
            _set_system_item_prompt(item, suggestion)
            item.metadata.update(
                {
                    "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
                    "source_script_shot": shot.model_dump(mode="json"),
                    "source_script_version_id": script.script_version_id,
                    "reference_item_ids": list(shot.reference_item_ids),
                    "primary_scene_item_id": shot.scene_id,
                    "screenplay_slice": self._slices.build(
                        script,
                        workflow,
                        specialist="storyboard",
                        item=item,
                        slot=item.slots[0],
                    ).model_dump(mode="json"),
                }
            )
            dependencies = reference_dependency_slot_ids(workflow, shot.reference_item_ids)
            for slot in item.slots:
                slot_suggestion = _storyboard_slot_prompt(shot, slot.slot_type)
                _set_system_slot_prompt(slot, slot_suggestion)
                slot.metadata.update(
                    {
                        "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
                        "source_script_version_id": script.script_version_id,
                        "source_scene_ids": list(shot.scene_ids),
                        "source_shot_ids": [shot.shot_id],
                        "reference_item_ids": list(shot.reference_item_ids),
                        "screenplay_slice": item.metadata["screenplay_slice"],
                    }
                )
                if slot.slot_type.startswith("shot_cell_"):
                    slot.dependency_slot_ids = dependencies
                updated_slots.add(slot.slot_id)
            updated_items.add(item.item_id)
            ordered.append(item)
        archived = [item for item in node.items if item.lifecycle_state == "archived"]
        node.items = [*ordered, *archived]
        updated_nodes.add(node.node_id)

    def _sync_bgm(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        *,
        changed: bool,
        updated_nodes: set[str],
        updated_items: set[str],
        updated_slots: set[str],
    ) -> None:
        node = _node(workflow, "bgm")
        if node is None or not node.items:
            return
        if not changed:
            return
        item = node.items[0]
        suggestion = (
            f"Instrumental score for {script.script_title}. Tone: {script.tone}. "
            f"Duration: {script.duration_seconds} seconds."
        )
        _set_system_item_prompt(item, suggestion)
        self._update_item_context(workflow, script, item, "bgm", suggestion)
        updated_nodes.add(node.node_id)
        updated_items.add(item.item_id)
        updated_slots.update(slot.slot_id for slot in item.slots)

    def _sync_products(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        affected_ids: set[str],
        updated_nodes: set[str],
        updated_items: set[str],
        updated_slots: set[str],
    ) -> None:
        if not affected_ids:
            return
        node = _node(workflow, "product-generation")
        if node is None:
            return
        for item in node.items:
            if item.lifecycle_state != "active" or item.item_id not in affected_ids:
                continue
            suggestion = f"{item.display_name}. {item.description}. Product beats: " + "; ".join(
                script.product_beats
            )
            _set_system_item_prompt(item, suggestion)
            self._update_item_context(workflow, script, item, "product", suggestion)
            updated_items.add(item.item_id)
            updated_slots.update(slot.slot_id for slot in item.slots)
        if updated_items:
            updated_nodes.add(node.node_id)

    def _update_item_context(
        self,
        workflow: WorkflowV2,
        script: V2ScriptPlanV2,
        item: WorkflowItemV2,
        specialist: Any,
        suggestion: str,
    ) -> None:
        for slot in item.slots:
            slot_suggestion = f"{suggestion} Deliver {slot.slot_type.replace('_', ' ')}."
            _set_system_slot_prompt(slot, slot_suggestion)
            screenplay_slice = self._slices.build(
                script,
                workflow,
                specialist=specialist,
                item=item,
                slot=slot,
            ).model_dump(mode="json")
            slot.metadata.update(
                {
                    "source_script_version_id": script.script_version_id,
                    "screenplay_slice": screenplay_slice,
                }
            )
        item.metadata.update(
            {
                "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
                "source_script_version_id": script.script_version_id,
                "screenplay_slice": (
                    item.slots[0].metadata["screenplay_slice"] if item.slots else {}
                ),
            }
        )


def _new_character_item(character: Any, script: V2ScriptPlanV2) -> WorkflowItemV2:
    suggestion = _character_system_prompt(character)
    item = WorkflowItemV2(
        item_id=character.character_id,
        node_id="character-generation",
        item_type="character",
        display_name=character.display_name,
        description=character.description,
        item_prompt=suggestion,
        system_suggested_prompt=suggestion,
        status="empty",
        metadata={
            "source_script_version_id": script.script_version_id,
            "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
        },
        slots=[
            build_slot(
                node_id="character-generation",
                item_id=character.character_id,
                slot_type="character_main_image",
                media_type="image",
                status="empty",
                prompt=f"{suggestion} Create the canonical main portrait.",
            ),
            build_slot(
                node_id="character-generation",
                item_id=character.character_id,
                slot_type="character_three_view",
                media_type="image",
                status="blocked",
                prompt=f"{suggestion} Create a front, side, and back turnaround.",
                dependency_slot_ids=[f"{character.character_id}:character_main_image"],
            ),
        ],
    )
    return _mark_linked_contract(item)


def _new_scene_item(scene: Any, script: V2ScriptPlanV2) -> WorkflowItemV2:
    suggestion = _scene_system_prompt(scene)
    return _mark_linked_contract(
        WorkflowItemV2(
            item_id=scene.scene_id,
            node_id="scene-generation",
            item_type="scene",
            display_name=scene.title,
            description=scene.description,
            item_prompt=suggestion,
            system_suggested_prompt=suggestion,
            status="empty",
            metadata={
                "source_script_version_id": script.script_version_id,
                "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
            },
            slots=[
                build_slot(
                    node_id="scene-generation",
                    item_id=scene.scene_id,
                    slot_type="scene_main_image",
                    media_type="image",
                    status="empty",
                    prompt=f"{suggestion} Create the canonical environment image without people.",
                ),
                build_slot(
                    node_id="scene-generation",
                    item_id=scene.scene_id,
                    slot_type="scene_multi_view_grid",
                    media_type="image",
                    status="blocked",
                    prompt=f"{suggestion} Create a consistent multi-view environment grid.",
                    dependency_slot_ids=[f"{scene.scene_id}:scene_main_image"],
                ),
            ],
        )
    )


def _new_storyboard_item(
    workflow: WorkflowV2,
    shot: Any,
    script: V2ScriptPlanV2,
) -> WorkflowItemV2:
    dependencies = reference_dependency_slot_ids(workflow, shot.reference_item_ids)
    provider_duration = 5 if shot.duration_seconds <= 7 else 10
    required_cell_slot_ids = [f"{shot.shot_id}:{slot_type}" for slot_type in shot_cell_slot_types()]
    slots = [
        build_slot(
            node_id="storyboard",
            item_id=shot.shot_id,
            slot_type=slot_type,
            media_type="image",
            status="blocked" if dependencies else "empty",
            prompt=_storyboard_slot_prompt(shot, slot_type),
            dependency_slot_ids=dependencies,
            metadata={"grid_layout": "2x2"},
        )
        for slot_type in shot_cell_slot_types()
    ]
    slots.append(
        build_slot(
            node_id="storyboard",
            item_id=shot.shot_id,
            slot_type="shot_video_segment",
            media_type="video",
            status="blocked",
            prompt=shot.visual_prompt,
            dependency_slot_ids=[
                f"{shot.shot_id}:{slot_type}" for slot_type in shot_cell_slot_types()
            ],
            metadata={"reference_item_ids": list(shot.reference_item_ids)},
        )
    )
    return _mark_linked_contract(
        WorkflowItemV2(
            item_id=shot.shot_id,
            node_id="storyboard",
            item_type="shot",
            display_name=f"Shot {shot.shot_index}",
            description=shot.description,
            item_prompt=shot.description,
            system_suggested_prompt=shot.description,
            status="empty",
            shot_id=shot.shot_id,
            shot_index=shot.shot_index,
            aspect_ratio=script.aspect_ratio,
            duration_seconds=shot.duration_seconds,
            shot_summary_prompt=shot.visual_prompt,
            detail_prompts={
                "shot_id": shot.shot_id,
                "shot_index": shot.shot_index,
                "desired_duration_seconds": shot.duration_seconds,
                "provider_duration_seconds": provider_duration,
                "required_shot_cell_slot_ids": required_cell_slot_ids,
                "required_shot_cell_asset_ids": [],
                "cell_prompts": {
                    slot_type: {
                        "provider_prompt": _storyboard_slot_prompt(shot, slot_type),
                    }
                    for slot_type in shot_cell_slot_types()
                },
                "video_provider_prompt": shot.visual_prompt,
                "storyboard_content": shot.description,
                "dialogue": _dialogue_text(shot),
                "audio_description": "Natural ambient sound appropriate to the action.",
                "voice_style": "Natural restrained delivery when dialogue is present.",
                "video_negative_constraints": (
                    "No watermark. No subtitles. Preserve product, character, and scene identity."
                ),
                "time_segments": [
                    {
                        "start_seconds": 0,
                        "end_seconds": provider_duration,
                        "content": shot.description,
                    }
                ],
                "materializer_mode": "linked_context",
                "materializer_version": "v2-linked-context-1",
            },
            reference_item_ids=list(shot.reference_item_ids),
            primary_scene_item_id=shot.scene_id,
            slots=slots,
            metadata={
                "linked_contract_schema_version": _LINKED_CONTRACT_SCHEMA_VERSION,
                "source_script_shot": shot.model_dump(mode="json"),
                "source_script_version_id": script.script_version_id,
                "reference_item_ids": list(shot.reference_item_ids),
                "primary_scene_item_id": shot.scene_id,
            },
        )
    )


def _archive_missing(
    items: list[WorkflowItemV2],
    desired_ids: set[str],
    updated_items: set[str],
    updated_slots: set[str],
) -> None:
    for item in items:
        if item.item_id in desired_ids or item.lifecycle_state == "archived":
            continue
        item.lifecycle_state = "archived"
        updated_items.add(item.item_id)
        updated_slots.update(slot.slot_id for slot in item.slots)


def _set_system_item_prompt(item: WorkflowItemV2, suggestion: str) -> None:
    item.system_suggested_prompt = suggestion
    if not item.user_prompt and not item.manual_prompt_dirty and item.prompt_source != "user":
        item.item_prompt = suggestion
        item.prompt_source = "system"


def _set_system_slot_prompt(slot: WorkflowSlotV2, suggestion: str) -> None:
    slot.system_suggested_prompt = suggestion
    if not slot.user_prompt and not slot.manual_prompt_dirty and slot.prompt_source != "user":
        slot.slot_prompt = suggestion
        slot.prompt_source = "system"


def _character_system_prompt(character: Any) -> str:
    return (
        f"{character.display_name}. {character.description}. Role: {character.role}. "
        f"Visual continuity: {character.visual_notes}."
    )


def _scene_system_prompt(scene: Any) -> str:
    return f"{scene.title}. {scene.description}. Preserve the canonical environment identity."


def _storyboard_slot_prompt(shot: Any, slot_type: str) -> str:
    if slot_type == "shot_video_segment":
        return shot.visual_prompt
    cell_number = slot_type.rsplit("_", 1)[-1]
    return (
        f"{shot.description} Storyboard cell {cell_number} for shot {shot.shot_index}. "
        f"Production direction: {shot.visual_prompt}"
    )


def _dialogue_text(shot: Any) -> str:
    lines = [line.text for line in shot.dialogue]
    return " ".join(lines) if lines else "No spoken dialogue."


def _node(workflow: WorkflowV2, node_id: str) -> Any | None:
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def _active_item(items: list[WorkflowItemV2], item_id: str) -> WorkflowItemV2 | None:
    return next(
        (item for item in items if item.item_id == item_id and item.lifecycle_state == "active"),
        None,
    )


def _archived_item(items: list[WorkflowItemV2], item_id: str) -> WorkflowItemV2 | None:
    return next(
        (item for item in items if item.item_id == item_id and item.lifecycle_state == "archived"),
        None,
    )


def _mark_linked_contract(item: WorkflowItemV2) -> WorkflowItemV2:
    item.metadata["linked_contract_schema_version"] = _LINKED_CONTRACT_SCHEMA_VERSION
    for slot in item.slots:
        slot.metadata["linked_contract_schema_version"] = _LINKED_CONTRACT_SCHEMA_VERSION
    return item


def _item_contract_matches(
    archived: WorkflowItemV2,
    expected: WorkflowItemV2,
) -> bool:
    if (
        archived.item_id != expected.item_id
        or archived.node_id != expected.node_id
        or archived.item_type != expected.item_type
    ):
        return False
    item_schema = archived.metadata.get("linked_contract_schema_version")
    if item_schema not in {None, _LINKED_CONTRACT_SCHEMA_VERSION}:
        return False
    if len(archived.slots) != len(expected.slots):
        return False
    archived_slots = {slot.slot_id: slot for slot in archived.slots}
    if len(archived_slots) != len(archived.slots):
        return False
    for expected_slot in expected.slots:
        slot = archived_slots.get(expected_slot.slot_id)
        if slot is None:
            return False
        if (
            slot.node_id != expected_slot.node_id
            or slot.item_id != expected_slot.item_id
            or slot.slot_type != expected_slot.slot_type
            or slot.media_type != expected_slot.media_type
            or slot.required != expected_slot.required
        ):
            return False
        slot_schema = slot.metadata.get("linked_contract_schema_version")
        if slot_schema not in {None, _LINKED_CONTRACT_SCHEMA_VERSION}:
            return False
    return True


def _with_reactivated(
    diff: V2ScriptStructuralDiff,
    reactivated: dict[str, list[str]],
) -> V2ScriptStructuralDiff:
    updates: dict[str, Any] = {}
    for namespace in ("character", "scene", "shot"):
        values = sorted(set(reactivated[namespace]))
        if not values:
            continue
        added_field = f"added_{namespace}_ids"
        updates[added_field] = [
            item_id for item_id in getattr(diff, added_field) if item_id not in values
        ]
        updates[f"reactivated_{namespace}_ids"] = values
    return diff.model_copy(update=updates, deep=True) if updates else diff


def _affected_ids(
    old_script: V2ScriptPlanV2,
    new_script: V2ScriptPlanV2,
    diff: V2ScriptStructuralDiff,
) -> dict[str, Any]:
    changed_shot_ids = {
        *diff.added_shot_ids,
        *diff.archived_shot_ids,
        *diff.reactivated_shot_ids,
        *diff.updated_shot_ids,
    }
    if diff.order_changed:
        changed_shot_ids.update(shot.shot_id for shot in new_script.shots)
    changed_shots = [
        shot for shot in [*old_script.shots, *new_script.shots] if shot.shot_id in changed_shot_ids
    ]
    product_ids = {product_id for shot in changed_shots for product_id in shot.product_ids}
    character_ids = {
        *diff.added_character_ids,
        *diff.archived_character_ids,
        *diff.reactivated_character_ids,
        *diff.updated_character_ids,
        *(character_id for shot in changed_shots for character_id in shot.character_ids),
    }
    scene_ids = {
        *diff.added_scene_ids,
        *diff.archived_scene_ids,
        *diff.reactivated_scene_ids,
        *diff.updated_scene_ids,
        *(scene_id for shot in changed_shots for scene_id in shot.scene_ids),
    }
    changed_location_ids = {
        *diff.added_location_ids,
        *diff.archived_location_ids,
        *diff.reactivated_location_ids,
        *diff.updated_location_ids,
    }
    scene_ids.update(
        scene.scene_id
        for scene in [*old_script.scenes, *new_script.scenes]
        if scene.location_id in changed_location_ids
    )
    if old_script.product_beats != new_script.product_beats:
        product_ids.update(
            product_id for shot in new_script.shots for product_id in shot.product_ids
        )
    bgm_changed = bool(
        changed_shot_ids
        or old_script.tone != new_script.tone
        or old_script.script_title != new_script.script_title
        or old_script.duration_seconds != new_script.duration_seconds
    )
    return {
        "product": product_ids,
        "character": character_ids,
        "scene": scene_ids,
        "shot": changed_shot_ids,
        "bgm": bgm_changed,
    }
