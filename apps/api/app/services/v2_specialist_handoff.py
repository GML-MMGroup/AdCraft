from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    V2ReferenceBundle,
    WorkflowItemV2,
    WorkflowNodeV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_screenplay import (
    V2ScreenplaySlice,
    V2ScriptPlanV2,
    V2SelectedReferenceDescriptor,
    V2SpecialistHandoffContext,
    V2SpecialistRole,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_creative_inventory import creative_inventory_from_metadata
from app.services.v2_reference_bundle_builder import V2ReferenceBundleBuilder
from app.services.v2_script_persistence import V2ScriptPersistenceError, V2ScriptVersionStore


class V2SpecialistHandoffError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class V2ScreenplaySliceBuilder:
    def build(
        self,
        script: V2ScriptPlanV2,
        workflow: WorkflowV2,
        *,
        specialist: V2SpecialistRole,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
    ) -> V2ScreenplaySlice:
        shots = self._shots(script, specialist=specialist, item=item)
        source_shot_ids = [shot.shot_id for shot in shots]
        source_scene_ids = list(
            dict.fromkeys(scene_id for shot in shots for scene_id in shot.scene_ids)
        )
        product_ids = list(
            dict.fromkeys(product_id for shot in shots for product_id in shot.product_ids)
        )
        character_ids = list(
            dict.fromkeys(character_id for shot in shots for character_id in shot.character_ids)
        )
        scene_ids = list(dict.fromkeys(scene_id for shot in shots for scene_id in shot.scene_ids))
        descriptor_product_ids = [item.item_id] if specialist == "product" else product_ids
        descriptor_character_ids = [item.item_id] if specialist == "character" else character_ids
        descriptor_scene_ids = [item.item_id] if specialist == "scene" else scene_ids
        products = [
            _workflow_item_descriptor(candidate, id_key="product_id")
            for candidate in _active_items(workflow, "product-generation")
            if candidate.item_id in descriptor_product_ids
        ]
        characters = [
            character.model_dump(mode="json")
            for character in script.characters
            if character.character_id in descriptor_character_ids
        ]
        scenes = [
            _scene_descriptor(script, scene_id)
            for scene_id in descriptor_scene_ids
            if _scene_by_id(script, scene_id) is not None
        ]
        timing = [
            {
                "shot_id": shot.shot_id,
                "shot_index": shot.shot_index,
                "duration_seconds": shot.duration_seconds,
            }
            for shot in shots
        ]
        return V2ScreenplaySlice(
            script_version_id=script.script_version_id,
            specialist=specialist,
            source_scene_ids=source_scene_ids,
            source_shot_ids=source_shot_ids,
            product_ids=product_ids,
            character_ids=character_ids,
            scene_ids=scene_ids,
            title=_slice_title(script, item),
            summary=_slice_summary(script, specialist, item, shots),
            product_beats=list(script.product_beats),
            products=products,
            characters=characters,
            scenes=scenes,
            shots=[shot.model_dump(mode="json") for shot in shots],
            cell_plan=_cell_plan(item, slot),
            timing=timing,
        )

    def _shots(
        self,
        script: V2ScriptPlanV2,
        *,
        specialist: V2SpecialistRole,
        item: WorkflowItemV2,
    ) -> list[Any]:
        if specialist == "product":
            return [shot for shot in script.shots if item.item_id in shot.product_ids]
        if specialist == "character":
            return [shot for shot in script.shots if item.item_id in shot.character_ids]
        if specialist == "scene":
            return [shot for shot in script.shots if item.item_id in shot.scene_ids]
        if specialist == "storyboard":
            shot_id = item.shot_id or item.item_id
            return [shot for shot in script.shots if shot.shot_id == shot_id]
        return list(script.shots)


class V2SpecialistHandoffBuilder:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._versions = V2ScriptVersionStore(data_dir)
        self._references = V2ReferenceBundleBuilder(data_dir)
        self._assets = V2AssetStoreService(data_dir)
        self._slices = V2ScreenplaySliceBuilder()

    def build(
        self,
        workflow: WorkflowV2,
        *,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        latest_instruction: str | None = None,
        generation_mode: str,
        reference_bundle: V2ReferenceBundle | None = None,
    ) -> V2SpecialistHandoffContext:
        specialist = _specialist_for_node(slot.node_id)
        if specialist is None:
            raise V2SpecialistHandoffError(
                "final_composition_handoff_not_supported",
                "Final composition does not use a creative specialist handoff.",
            )
        script = self._selected_script(workflow)
        screenplay_slice = self._slices.build(
            script,
            workflow,
            specialist=specialist,
            item=item,
            slot=slot,
        )
        bundle = reference_bundle or self._references.build_for_slot(
            workflow,
            item,
            slot,
            generation_mode=generation_mode,
        )
        references = _dedupe_descriptors(
            [
                self._reference_descriptor(reference)
                for reference in [
                    *bundle.explicit_reference_assets,
                    *bundle.implicit_reference_assets,
                ]
            ]
        )
        return V2SpecialistHandoffContext(
            workflow_id=workflow.workflow_id,
            specialist=specialist,
            node_id=slot.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            script_version_id=script.script_version_id,
            screenplay_slice=screenplay_slice,
            hard_constraints={
                "duration_seconds": workflow.duration_seconds,
                "aspect_ratio": workflow.aspect_ratio,
                "audio_mode": workflow.audio_mode,
                "provider_capabilities": dict(slot.provider_params),
                "negative_prompt": slot.negative_prompt,
                "negative_constraints": slot.negative_constraints,
            },
            system_suggested_prompt=_system_prompt(item, slot),
            user_prompt=_user_prompt(item, slot),
            latest_user_instruction=latest_instruction,
            selected_references=references,
        )

    def build_initial_planning_handoffs(
        self,
        workflow: WorkflowV2,
    ) -> list[V2SpecialistHandoffContext]:
        script = self._selected_script(workflow)
        planning_workflow = workflow.model_copy(
            update={"nodes": _initial_planning_nodes(workflow, script)},
            deep=True,
        )
        contexts: list[V2SpecialistHandoffContext] = []
        for node in planning_workflow.nodes:
            for item in node.items:
                if not item.slots:
                    continue
                contexts.append(
                    self.build(
                        planning_workflow,
                        item=item,
                        slot=item.slots[0],
                        generation_mode="global_run",
                    )
                )
        return contexts

    def _selected_script(self, workflow: WorkflowV2) -> V2ScriptPlanV2:
        selected_id = str(workflow.metadata.get("selected_script_version_id") or "")
        if not selected_id:
            raise V2SpecialistHandoffError(
                "script_plan_unavailable",
                "A selected canonical screenplay is required for specialist generation.",
            )
        try:
            return self._versions.load_version(workflow.workflow_id, selected_id).script
        except V2ScriptPersistenceError as exc:
            raise V2SpecialistHandoffError(exc.code, str(exc)) from exc

    def _reference_descriptor(self, reference: Any) -> V2SelectedReferenceDescriptor:
        record = self._assets.load_asset_version(reference.asset_id, reference.version_id)
        return V2SelectedReferenceDescriptor(
            asset_id=reference.asset_id,
            version_id=reference.version_id,
            media_type=reference.media_type,
            semantic_type=reference.semantic_type,
            node_id=record.node_id if record is not None else None,
            item_id=record.item_id if record is not None else None,
            slot_id=reference.slot_id or (record.slot_id if record is not None else None),
            display_name=reference.display_name,
            media_handle=f"asset:{reference.asset_id}@{reference.version_id}",
        )


def _specialist_for_node(node_id: str) -> V2SpecialistRole | None:
    return {
        "product-generation": "product",
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard",
        "bgm": "bgm",
    }.get(node_id)  # type: ignore[return-value]


def _active_items(workflow: WorkflowV2, node_id: str) -> list[WorkflowItemV2]:
    node = next((candidate for candidate in workflow.nodes if candidate.node_id == node_id), None)
    if node is None:
        return []
    return [item for item in node.items if item.lifecycle_state == "active"]


def _workflow_item_descriptor(item: WorkflowItemV2, *, id_key: str) -> dict[str, Any]:
    return {
        id_key: item.item_id,
        "display_name": item.display_name,
        "description": item.description,
    }


def _scene_by_id(script: V2ScriptPlanV2, scene_id: str) -> Any | None:
    return next((scene for scene in script.scenes if scene.scene_id == scene_id), None)


def _scene_descriptor(script: V2ScriptPlanV2, scene_id: str) -> dict[str, Any]:
    scene = _scene_by_id(script, scene_id)
    assert scene is not None
    payload = scene.model_dump(mode="json")
    location = next(
        (item for item in script.locations if item.location_id == scene.location_id),
        None,
    )
    if location is not None:
        payload["location"] = location.model_dump(mode="json")
    return payload


def _slice_title(script: V2ScriptPlanV2, item: WorkflowItemV2) -> str:
    return f"{script.script_title}: {item.display_name}"


def _slice_summary(
    script: V2ScriptPlanV2,
    specialist: V2SpecialistRole,
    item: WorkflowItemV2,
    shots: list[Any],
) -> str:
    if specialist == "bgm":
        return (
            f"Tone: {script.tone}. Visual style: {script.visual_style}. "
            f"Duration: {script.duration_seconds} seconds."
        )
    actions = " ".join(shot.description for shot in shots)
    return f"{item.display_name}. {item.description}. {actions}".strip()


def _cell_plan(item: WorkflowItemV2, slot: WorkflowSlotV2) -> list[dict[str, Any]]:
    if item.item_type != "shot" or not (
        slot.slot_type.startswith("shot_cell_") or slot.slot_type == "shot_video_segment"
    ):
        return []
    result: list[dict[str, Any]] = []
    for cell_slot in sorted(
        (candidate for candidate in item.slots if candidate.slot_type.startswith("shot_cell_")),
        key=lambda candidate: candidate.slot_type,
    ):
        cell_index = int(cell_slot.slot_type.rsplit("_", 1)[-1])
        result.append(
            {
                "slot_id": cell_slot.slot_id,
                "slot_type": cell_slot.slot_type,
                "cell_index": cell_index,
                "cell_role": {
                    1: "establishing",
                    2: "action",
                    3: "detail",
                    4: "payoff",
                }[cell_index],
                "selected_asset_id": cell_slot.selected_asset_id,
                "selected_version_id": cell_slot.selected_version_id,
            }
        )
    return result


def _system_prompt(item: WorkflowItemV2, slot: WorkflowSlotV2) -> str:
    return (
        slot.system_suggested_prompt
        or item.system_suggested_prompt
        or (slot.slot_prompt if slot.prompt_source != "user" else None)
        or (item.item_prompt if item.prompt_source != "user" else None)
        or "Generate the target asset from the selected screenplay facts."
    )


def _user_prompt(item: WorkflowItemV2, slot: WorkflowSlotV2) -> str | None:
    return (
        slot.user_prompt
        or item.user_prompt
        or (slot.slot_prompt if slot.prompt_source == "user" else None)
        or (item.item_prompt if item.prompt_source == "user" else None)
    )


def _dedupe_descriptors(
    values: list[V2SelectedReferenceDescriptor],
) -> list[V2SelectedReferenceDescriptor]:
    result: list[V2SelectedReferenceDescriptor] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value.asset_id, value.version_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _initial_planning_nodes(
    workflow: WorkflowV2,
    script: V2ScriptPlanV2,
) -> list[WorkflowNodeV2]:
    inventory = creative_inventory_from_metadata(workflow.metadata)
    product_items = [
        _planning_item(
            node_id="product-generation",
            item_id=product.item_id,
            item_type="product",
            display_name=product.display_name,
            description=product.category or product.display_name,
            slot_type="product_main_image",
            media_type="image",
        )
        for product in (inventory.products if inventory is not None else [])
    ]
    character_items = [
        _planning_item(
            node_id="character-generation",
            item_id=character.character_id,
            item_type="character",
            display_name=character.display_name,
            description=character.description,
            slot_type="character_main_image",
            media_type="image",
        )
        for character in script.characters
    ]
    scene_items = [
        _planning_item(
            node_id="scene-generation",
            item_id=scene.scene_id,
            item_type="scene",
            display_name=scene.title,
            description=scene.description,
            slot_type="scene_main_image",
            media_type="image",
        )
        for scene in script.scenes
    ]
    bgm_items = [
        _planning_item(
            node_id="bgm",
            item_id="bgm-1",
            item_type="bgm",
            display_name="BGM",
            description=f"Instrumental score for {script.script_title}.",
            slot_type="bgm_audio",
            media_type="audio",
        )
    ]
    return [
        _planning_node("product-generation", "Product Generation", product_items),
        _planning_node("character-generation", "Character Generation", character_items),
        _planning_node("scene-generation", "Scene Generation", scene_items),
        _planning_node("bgm", "BGM", bgm_items),
    ]


def _planning_node(
    node_id: str,
    title: str,
    items: list[WorkflowItemV2],
) -> WorkflowNodeV2:
    return WorkflowNodeV2(
        node_id=node_id,
        node_type=node_id,
        title=title,
        status="not_ready",
        items=items,
    )


def _planning_item(
    *,
    node_id: str,
    item_id: str,
    item_type: str,
    display_name: str,
    description: str,
    slot_type: str,
    media_type: str,
) -> WorkflowItemV2:
    suggestion = f"{display_name}. {description}".strip()
    return WorkflowItemV2(
        item_id=item_id,
        node_id=node_id,
        item_type=item_type,  # type: ignore[arg-type]
        display_name=display_name,
        description=description,
        item_prompt=suggestion,
        system_suggested_prompt=suggestion,
        status="empty",
        slots=[
            WorkflowSlotV2(
                slot_id=f"{item_id}:{slot_type}",
                node_id=node_id,
                item_id=item_id,
                slot_type=slot_type,
                media_type=media_type,  # type: ignore[arg-type]
                status="empty",
                slot_prompt=suggestion,
                system_suggested_prompt=suggestion,
            )
        ],
    )
