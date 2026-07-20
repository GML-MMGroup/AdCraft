from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.services.v2_asset_store import V2AssetStoreService


class V2ShotReferenceResolverError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class V2ShotReferenceAsset:
    asset_id: str
    version_id: str
    item_id: str
    slot_id: str
    slot_type: str


@dataclass(frozen=True)
class V2ResolvedShotReferences:
    shot_item_id: str
    primary_scene_item_id: str
    reference_item_ids: tuple[str, ...]
    required_main_slot_ids: tuple[str, ...]
    optional_companion_slot_ids: tuple[str, ...]
    required_assets: tuple[V2ShotReferenceAsset, ...]
    optional_assets: tuple[V2ShotReferenceAsset, ...]
    warnings: tuple[str, ...] = ()


class V2ShotReferenceResolver:
    """Resolve one Storyboard Shot's item-scoped visual reference contract."""

    def __init__(self, data_dir: Path) -> None:
        self._asset_store = V2AssetStoreService(data_dir)

    def resolve(
        self,
        workflow: WorkflowV2,
        shot: WorkflowItemV2,
        *,
        require_selected_assets: bool,
        frozen_selection: dict[str, object] | None = None,
    ) -> V2ResolvedShotReferences:
        if shot.item_type != "shot" or shot.lifecycle_state != "active":
            raise V2ShotReferenceResolverError(
                "shot_reference_contract_mismatch",
                "Shot reference resolution requires an active shot item.",
            )

        item_by_id = _active_items_by_id(workflow)
        frozen_selection = (
            frozen_selection
            if frozen_selection is not None
            else frozen_shot_reference_selection(workflow, shot)
        )
        primary_scene_item_id = (
            _string_value(frozen_selection.get("primary_scene_item_id"))
            or shot.primary_scene_item_id
        )
        if not primary_scene_item_id:
            scene_ids = _item_ids_of_type(
                list(shot.reference_item_ids),
                item_by_id,
                "scene",
            )
            if len(scene_ids) == 1:
                primary_scene_item_id = scene_ids[0]
        if not primary_scene_item_id:
            raise V2ShotReferenceResolverError(
                "shot_reference_contract_mismatch",
                "Shot primary scene is missing.",
            )

        primary_scene = item_by_id.get(primary_scene_item_id)
        if not _is_scene_item(primary_scene):
            raise V2ShotReferenceResolverError(
                "shot_reference_contract_mismatch",
                "Shot primary scene is not an active scene-generation item.",
            )

        semantic_reference_ids = _semantic_reference_ids(
            shot,
            item_by_id,
            primary_scene_item_id=primary_scene_item_id,
            frozen_selection=frozen_selection,
        )
        resolved_items = [item_by_id[item_id] for item_id in semantic_reference_ids]
        if any(not _is_semantic_reference_owner(item) for item in resolved_items):
            raise V2ShotReferenceResolverError(
                "shot_reference_contract_mismatch",
                "Shot semantic reference owner is invalid.",
            )
        required_slots: list[WorkflowSlotV2] = []
        companion_slots: list[WorkflowSlotV2] = []
        for item in resolved_items:
            main_slot_type = _main_slot_type(item)
            if main_slot_type is None:
                continue
            main_slot = _slot_by_type(item, main_slot_type)
            if main_slot is None:
                raise V2ShotReferenceResolverError(
                    "shot_reference_contract_mismatch",
                    f"Required {main_slot_type} slot is missing for {item.item_id}.",
                )
            required_slots.append(main_slot)
            companion = _slot_by_type(item, _companion_slot_type(main_slot_type))
            if companion is not None:
                companion_slots.append(companion)

        required_assets = tuple(
            asset
            for slot in required_slots
            if (
                asset := self._selected_asset(
                    workflow,
                    slot,
                    required=require_selected_assets,
                )
            )
            is not None
        )
        optional_assets = tuple(
            asset
            for slot in companion_slots
            if (asset := self._selected_asset(workflow, slot, required=False)) is not None
        )
        return V2ResolvedShotReferences(
            shot_item_id=shot.item_id,
            primary_scene_item_id=primary_scene_item_id,
            reference_item_ids=tuple(semantic_reference_ids),
            required_main_slot_ids=tuple(slot.slot_id for slot in required_slots),
            optional_companion_slot_ids=tuple(slot.slot_id for slot in companion_slots),
            required_assets=required_assets,
            optional_assets=optional_assets,
        )

    def reconcile_shot_cell_dependencies(
        self,
        workflow: WorkflowV2,
        shot: WorkflowItemV2,
        slot: WorkflowSlotV2,
        *,
        frozen_selection: dict[str, object] | None = None,
    ) -> V2ResolvedShotReferences:
        """Derive one Shot Cell's executable dependencies from semantic references."""
        if not slot.slot_type.startswith("shot_cell_") or slot.item_id != shot.item_id:
            raise V2ShotReferenceResolverError(
                "shot_reference_contract_mismatch",
                "Shot dependency reconciliation requires a cell owned by the current shot.",
            )
        resolved = self.resolve(
            workflow,
            shot,
            require_selected_assets=False,
            frozen_selection=frozen_selection,
        )
        slot.dependency_slot_ids = list(resolved.required_main_slot_ids)
        return resolved

    def _selected_asset(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        required: bool,
    ) -> V2ShotReferenceAsset | None:
        if not slot.selected_asset_id or not slot.selected_version_id:
            if required:
                raise V2ShotReferenceResolverError(
                    "shot_reference_asset_missing",
                    f"Selected asset is missing for required reference slot {slot.slot_id}.",
                )
            return None
        record = self._asset_store.load_asset_version(
            slot.selected_asset_id, slot.selected_version_id
        )
        if record is None:
            if required:
                raise V2ShotReferenceResolverError(
                    "shot_reference_asset_missing",
                    f"Selected asset metadata is missing for required reference slot {slot.slot_id}.",
                )
            return None
        if (
            record.workflow_id != workflow.workflow_id
            or record.node_id != slot.node_id
            or record.item_id != slot.item_id
            or record.slot_id != slot.slot_id
        ):
            if required:
                raise V2ShotReferenceResolverError(
                    "shot_reference_contract_mismatch",
                    f"Selected asset owner does not match required reference slot {slot.slot_id}.",
                )
            return None
        return V2ShotReferenceAsset(
            asset_id=record.asset_id,
            version_id=record.version_id,
            item_id=slot.item_id,
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
        )


def frozen_shot_reference_selection(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
) -> dict[str, object]:
    """Read a per-execution or local-regeneration selection without leaking it to callers."""
    selections = workflow.metadata.get("execution_shot_reference_selections")
    if not isinstance(selections, dict):
        return {}
    selection = selections.get(shot.item_id)
    return dict(selection) if isinstance(selection, dict) else {}


def _active_items_by_id(workflow: WorkflowV2) -> dict[str, WorkflowItemV2]:
    return {
        item.item_id: item
        for node in workflow.nodes
        for item in node.items
        if item.lifecycle_state == "active"
    }


def _semantic_reference_ids(
    shot: WorkflowItemV2,
    item_by_id: dict[str, WorkflowItemV2],
    *,
    primary_scene_item_id: str,
    frozen_selection: dict[str, object],
) -> list[str]:
    requested_ids = frozen_selection.get("reference_item_ids")
    source_ids = (
        [value for value in requested_ids if isinstance(value, str)]
        if isinstance(requested_ids, list)
        else list(shot.reference_item_ids)
    )
    product_ids = _item_ids_of_type(source_ids, item_by_id, "product")
    character_ids = _item_ids_of_type(source_ids, item_by_id, "character")
    if not product_ids:
        raise V2ShotReferenceResolverError(
            "shot_reference_contract_mismatch",
            "Shot reference contract has no active product item.",
        )
    return [*product_ids, *character_ids, primary_scene_item_id]


def _item_ids_of_type(
    item_ids: list[str],
    item_by_id: dict[str, WorkflowItemV2],
    item_type: str,
) -> list[str]:
    return [
        item_id
        for item_id in item_ids
        if (item := item_by_id.get(item_id)) is not None and item.item_type == item_type
    ]


def _is_scene_item(item: WorkflowItemV2 | None) -> bool:
    return bool(
        item
        and item.item_type == "scene"
        and item.node_id == "scene-generation"
        and item.lifecycle_state == "active"
    )


def _is_semantic_reference_owner(item: WorkflowItemV2) -> bool:
    expected_node_id = {
        "product": "product-generation",
        "character": "character-generation",
        "scene": "scene-generation",
    }.get(item.item_type)
    return bool(expected_node_id and item.node_id == expected_node_id)


def _main_slot_type(item: WorkflowItemV2) -> str | None:
    return {
        "product": "product_main_image",
        "character": "character_main_image",
        "scene": "scene_main_image",
    }.get(item.item_type)


def _companion_slot_type(main_slot_type: str) -> str:
    return {
        "product_main_image": "product_multi_view_grid",
        "character_main_image": "character_three_view",
        "scene_main_image": "scene_multi_view_grid",
    }[main_slot_type]


def _slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value or None
