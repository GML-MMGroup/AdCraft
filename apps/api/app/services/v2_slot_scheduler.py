from collections.abc import Callable
from copy import deepcopy
from typing import Any

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowNodeV2, WorkflowSlotV2, WorkflowV2
from app.services.v2_main_to_multiview_consistency import (
    dependency_slot_ids_for_multiview,
    is_main_to_multiview_slot,
    main_reference_missing_metadata,
    matching_main_slot,
)
from app.services.v2_shot_reference_resolver import (
    V2ShotReferenceResolver,
    V2ShotReferenceResolverError,
)
from app.services.v2_storyboard_defaults import shot_cell_slot_types


class V2SlotScheduler:
    SOFT_SLOT_TYPES = frozenset(
        {
            "product_multi_view_grid",
            "character_three_view",
            "scene_multi_view_grid",
            "bgm_audio",
        }
    )

    def __init__(
        self,
        *,
        asset_exists: Callable[[str], bool],
        shot_reference_resolver: V2ShotReferenceResolver | None = None,
    ) -> None:
        self._asset_exists = asset_exists
        self._shot_reference_resolver = shot_reference_resolver

    def initial_slot_runtime(
        self,
        workflow: WorkflowV2,
        *,
        execution_id: str,
        updated_at: str,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        slot_runtime: dict[str, dict[str, Any]] = {}
        target_slot_ids: list[str] = []
        for node in workflow.nodes:
            for item in active_items(node):
                for slot in item.slots:
                    if not slot.required or slot.status == "skipped":
                        status = "skipped"
                    elif self.slot_has_valid_selected_asset(slot):
                        status = "completed"
                    elif not self.dependencies_satisfied(workflow, slot):
                        status = "blocked"
                    else:
                        status = "queued"
                        target_slot_ids.append(slot.slot_id)
                    slot_runtime[slot.slot_id] = {
                        "slot_id": slot.slot_id,
                        "node_id": slot.node_id,
                        "item_id": slot.item_id,
                        "status": status,
                        "runtime_status": status,
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                        "selected_asset_id": slot.selected_asset_id,
                        "selected_version_id": slot.selected_version_id,
                        "current_working_asset_id": slot.current_working_asset_id,
                        "current_working_version_id": slot.current_working_version_id,
                        "execution_id": execution_id,
                        "updated_at": updated_at,
                    }
        return slot_runtime, target_slot_ids

    def targetable_slots(
        self,
        workflow: WorkflowV2,
        slot_types: tuple[str, ...],
        *,
        mode: str,
        include_failed: bool,
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        targets: list[tuple[WorkflowItemV2, WorkflowSlotV2]] = []
        for node in workflow.nodes:
            for item in active_items(node):
                for slot in item.slots:
                    if slot.slot_type not in slot_types:
                        continue
                    if not self.slot_is_targetable(
                        workflow,
                        slot,
                        mode=mode,
                        include_failed=include_failed,
                    ):
                        continue
                    targets.append((item, slot))
        return targets

    def slot_is_targetable(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
        *,
        mode: str = "fill_missing_required_slots",
        include_failed: bool = True,
    ) -> bool:
        if not slot.required or slot.status in {"skipped", "waiting", "running"}:
            return False
        slot_state = slot.status
        slot_metadata = deepcopy(slot.metadata)
        slot_dependency_slot_ids = list(slot.dependency_slot_ids)
        try:
            dependencies_ready = self.dependencies_satisfied(workflow, slot)
        finally:
            slot.status = slot_state
            slot.metadata = slot_metadata
            slot.dependency_slot_ids = slot_dependency_slot_ids
        if not dependencies_ready:
            return False
        has_selected_asset = self.slot_has_valid_selected_asset(slot)
        stale = slot_is_stale(slot)
        force_rerun = mode == "force_rerun_all"
        regenerate_stale = mode == "regenerate_missing_stale" and stale
        if has_selected_asset and not force_rerun and not regenerate_stale:
            return False
        if slot.status == "completed" and not force_rerun and not regenerate_stale:
            return False
        targetable_statuses = {"empty", "blocked", "ready"}
        if force_rerun or regenerate_stale:
            targetable_statuses.update({"completed", "stale"})
        if include_failed:
            targetable_statuses.add("failed")
        if slot.status not in targetable_statuses:
            return False
        return True

    def refresh_workflow_state(self, workflow: WorkflowV2) -> None:
        for node in workflow.nodes:
            for item in active_items(node):
                for slot in item.slots:
                    if slot.status in {"skipped", "waiting", "running", "failed"}:
                        continue
                    if slot.required and not self.dependencies_satisfied(workflow, slot):
                        slot.status = "blocked"
                    elif self.slot_has_valid_selected_asset(slot):
                        slot.status = "completed"
                    elif slot.required:
                        slot.status = "ready" if slot.status != "empty" else "empty"
                if item.slots:
                    item.status = self.item_status(item)
        self.record_soft_dependency_warnings(workflow)
        if self.visual_reference_bundles_complete(workflow):
            storyboard = node_by_id(workflow, "storyboard")
            if storyboard and not storyboard.items:
                storyboard.status = "ready"
        if self.final_inputs_ready(workflow):
            final_node = node_by_id(workflow, "final-composition")
            if final_node and not final_node.items:
                final_node.status = "ready"
        for node in workflow.nodes:
            node.status = self.node_status(workflow, node)

    def item_status(self, item: WorkflowItemV2) -> Any:
        required_slots = [slot for slot in item.slots if slot.required]
        if not required_slots:
            return item.status
        statuses = {slot.status for slot in required_slots}
        if "running" in statuses:
            return "running"
        if "waiting" in statuses:
            return "waiting"
        if statuses <= {"completed", "skipped"}:
            return "completed"
        if "failed" in statuses and "completed" in statuses:
            return "partial_failed"
        if statuses == {"failed"}:
            return "failed"
        if "ready" in statuses:
            return "ready"
        if "blocked" in statuses:
            return "blocked"
        return "empty"

    def node_status(self, workflow: WorkflowV2, node: WorkflowNodeV2) -> Any:
        if node.node_id == "script":
            return "completed"
        if node.metadata.get("execution_disposition") == "not_applicable":
            return "completed"
        active_slots = [slot for item in active_items(node) for slot in item.slots if slot.required]
        if not active_slots:
            if node.node_id == "storyboard" and self.visual_reference_bundles_complete(workflow):
                return "ready"
            if node.node_id == "final-composition" and self.final_inputs_ready(workflow):
                return "ready"
            return "not_ready"
        statuses = {slot.status for slot in active_slots}
        if "running" in statuses:
            return "running"
        if "waiting" in statuses:
            return "waiting"
        if statuses <= {"completed", "skipped"}:
            return "completed"
        if "failed" in statuses and "completed" in statuses:
            return "partial_failed"
        if statuses == {"failed"}:
            return "failed"
        if "ready" in statuses or "empty" in statuses:
            return "ready"
        return "not_ready"

    def dependencies_satisfied(self, workflow: WorkflowV2, slot: WorkflowSlotV2) -> bool:
        if slot.slot_type == "final_video":
            return self.final_inputs_ready(workflow)
        if slot.slot_type.startswith("shot_cell_"):
            item = find_item(workflow, slot.node_id, slot.item_id)
            if item is None:
                slot.metadata["blocked_reason"] = "shot_reference_contract_mismatch"
                return False
            if self._shot_reference_resolver is not None:
                try:
                    self._shot_reference_resolver.reconcile_shot_cell_dependencies(
                        workflow,
                        item,
                        slot,
                    )
                except V2ShotReferenceResolverError as exc:
                    slot.metadata["blocked_reason"] = exc.code
                    return False
        if slot.slot_type == "shot_video_segment":
            item = find_item(workflow, slot.node_id, slot.item_id)
            if item is None:
                slot.metadata["blocked_reason"] = "missing_required_shot_cell_assets"
                return False
            required_cells = [slot_by_type(item, slot_type) for slot_type in shot_cell_slot_types()]
            if not all(
                cell and self.slot_has_valid_selected_asset(cell) for cell in required_cells
            ):
                slot.metadata["blocked_reason"] = "missing_required_shot_cell_assets"
                return False
            slot.metadata.pop("blocked_reason", None)
            return True
        if is_main_to_multiview_slot(slot.slot_type):
            item = find_item(workflow, slot.node_id, slot.item_id)
            if item is None:
                slot.metadata.update(
                    {
                        "blocked_reason": "missing_selected_main_image",
                        "missing_source_slot_id": None,
                        "required_main_slot_type": None,
                    }
                )
                return False
            source = matching_main_slot(item, slot)
            if source is None or not self.slot_has_valid_selected_asset(source):
                slot.metadata.update(main_reference_missing_metadata(item, slot))
                return False
            slot.dependency_slot_ids = dependency_slot_ids_for_multiview(item, slot)
            for key in (
                "blocked_reason",
                "missing_source_slot_id",
                "required_main_slot_type",
            ):
                slot.metadata.pop(key, None)
        for dependency_slot_id in slot.dependency_slot_ids:
            dependency = find_slot(workflow, dependency_slot_id)
            if dependency is None or not self.slot_has_valid_selected_asset(dependency):
                return False
        return True

    def slot_has_valid_selected_asset(self, slot: WorkflowSlotV2) -> bool:
        if not slot.selected_asset_id or not slot.selected_version_id:
            return False
        return self._asset_exists(slot.selected_asset_id)

    def visual_reference_bundles_complete(self, workflow: WorkflowV2) -> bool:
        character_node = node_by_id(workflow, "character-generation")
        character_ready = bool(
            character_node
            and character_node.metadata.get("execution_disposition") == "not_applicable"
        ) or self.node_bundle_complete(
            workflow,
            "character-generation",
            ("character_main_image",),
        )
        return (
            self.node_bundle_complete(workflow, "product-generation", ("product_main_image",))
            and character_ready
            and self.node_bundle_complete(
                workflow,
                "scene-generation",
                ("scene_main_image",),
            )
        )

    def record_soft_dependency_warnings(self, workflow: WorkflowV2) -> None:
        warnings = [
            warning
            for warning in list(workflow.metadata.get("warnings") or [])
            if not (isinstance(warning, dict) and warning.get("code") == "soft_dependency_failed")
        ]
        for slot in self.soft_dependency_slots(workflow):
            if slot.status != "failed":
                continue
            error = slot.metadata.get("error")
            error_code = slot.metadata.get("generation_error_code")
            if not error_code and isinstance(error, dict):
                error_code = error.get("code")
            warnings.append(
                {
                    "code": "soft_dependency_failed",
                    "slot_id": slot.slot_id,
                    "slot_type": slot.slot_type,
                    "node_id": slot.node_id,
                    "item_id": slot.item_id,
                    "error_code": error_code,
                    "message": f"Soft dependency {slot.slot_id} failed but does not block mainline progress.",
                }
            )
        if warnings:
            workflow.metadata["warnings"] = warnings

    def soft_dependency_slots(self, workflow: WorkflowV2) -> list[WorkflowSlotV2]:
        return [
            slot for slot in _workflow_slots(workflow) if slot.slot_type in self.SOFT_SLOT_TYPES
        ]

    def final_inputs_ready(self, workflow: WorkflowV2) -> bool:
        storyboard_items = self.storyboard_items(workflow)
        if not storyboard_items:
            return False
        for item in storyboard_items:
            slot = slot_by_type(item, "shot_video_segment")
            if slot is None or not self.slot_has_valid_selected_asset(slot):
                return False
        return True

    def final_composition_dependency_error_code(self, workflow: WorkflowV2) -> str:
        storyboard_items = self.storyboard_items(workflow)
        if not storyboard_items:
            return "composition_input_missing"
        for item in storyboard_items:
            slot = slot_by_type(item, "shot_video_segment")
            if slot is None or not self.slot_has_valid_selected_asset(slot):
                return "composition_input_missing"
        return "final_composition_not_ready"

    def node_bundle_complete(
        self,
        workflow: WorkflowV2,
        node_id: str,
        required_slot_types: tuple[str, ...],
    ) -> bool:
        node = node_by_id(workflow, node_id)
        if node is None:
            return False
        node_items = active_items(node)
        if not node_items:
            return False
        for item in node_items:
            for slot_type in required_slot_types:
                slot = slot_by_type(item, slot_type)
                if slot is None or not self.slot_has_valid_selected_asset(slot):
                    return False
        return True

    def visual_reference_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        asset_ids: list[str] = []
        for slot_type in (
            "product_main_image",
            "character_main_image",
            "scene_main_image",
        ):
            slot = find_slot_by_type(workflow, slot_type)
            if slot and slot.selected_asset_id:
                asset_ids.append(slot.selected_asset_id)
        return asset_ids

    def dependency_asset_ids(self, workflow: WorkflowV2, slot: WorkflowSlotV2) -> list[str]:
        asset_ids: list[str] = []
        for dependency_slot_id in slot.dependency_slot_ids:
            dependency = find_slot(workflow, dependency_slot_id)
            if dependency and dependency.selected_asset_id:
                asset_ids.append(dependency.selected_asset_id)
        return asset_ids

    def selected_shot_video_asset_ids(self, workflow: WorkflowV2) -> list[str]:
        return [
            slot.selected_asset_id
            for _item, slot in self.selected_shot_video_slots(workflow)
            if slot.selected_asset_id
        ]

    def selected_shot_video_slots(
        self,
        workflow: WorkflowV2,
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        storyboard = node_by_id(workflow, "storyboard")
        if storyboard is None:
            return []
        slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]] = []
        for item in sorted(active_items(storyboard), key=lambda shot: shot.shot_index or 0):
            slot = slot_by_type(item, "shot_video_segment")
            if slot and self.slot_has_valid_selected_asset(slot):
                slots.append((item, slot))
        return slots

    def selected_bgm_asset_id(self, workflow: WorkflowV2) -> str | None:
        bgm_slot = self.selected_bgm_slot(workflow)
        return bgm_slot.selected_asset_id if bgm_slot else None

    def selected_bgm_slot(self, workflow: WorkflowV2) -> WorkflowSlotV2 | None:
        bgm_slot = find_slot_by_type(workflow, "bgm_audio")
        if bgm_slot is None or bgm_slot.status == "skipped":
            return None
        if self.slot_has_valid_selected_asset(bgm_slot):
            return bgm_slot
        return None

    def final_composition_item(self, workflow: WorkflowV2) -> WorkflowItemV2 | None:
        node = node_by_id(workflow, "final-composition")
        if node is None:
            return None
        for item in active_items(node):
            if item.item_type == "final_composition":
                return item
        return None

    def slots_for_node(self, workflow: WorkflowV2, node_id: str) -> list[WorkflowSlotV2]:
        node = node_by_id(workflow, node_id)
        if node is None:
            return []
        return [slot for item in active_items(node) for slot in item.slots]

    def blocked_slot_ids(self, workflow: WorkflowV2) -> list[str]:
        return [
            slot.slot_id
            for node in workflow.nodes
            for item in active_items(node)
            for slot in item.slots
            if slot.status == "blocked"
        ]

    def storyboard_items(self, workflow: WorkflowV2) -> list[WorkflowItemV2]:
        storyboard = node_by_id(workflow, "storyboard")
        if storyboard is None:
            return []
        return sorted(active_items(storyboard), key=lambda item: item.shot_index or 0)


def node_by_id(workflow: WorkflowV2, node_id: str) -> WorkflowNodeV2 | None:
    return next((node for node in workflow.nodes if node.node_id == node_id), None)


def active_items(node: WorkflowNodeV2) -> list[WorkflowItemV2]:
    return [item for item in node.items if item.lifecycle_state == "active"]


def slot_by_type(item: WorkflowItemV2, slot_type: str) -> WorkflowSlotV2 | None:
    return next((slot for slot in item.slots if slot.slot_type == slot_type), None)


def find_item(
    workflow: WorkflowV2,
    node_id: str,
    item_id_or_shot_id: str,
) -> WorkflowItemV2 | None:
    node = node_by_id(workflow, node_id)
    if node is None:
        return None
    for item in active_items(node):
        if item.item_id == item_id_or_shot_id or item.shot_id == item_id_or_shot_id:
            return item
    return None


def find_slot(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in active_items(node):
            for slot in item.slots:
                if slot.slot_id == slot_id:
                    return slot
    return None


def find_slot_by_type(workflow: WorkflowV2, slot_type: str) -> WorkflowSlotV2 | None:
    for node in workflow.nodes:
        for item in active_items(node):
            slot = slot_by_type(item, slot_type)
            if slot is not None:
                return slot
    return None


def _workflow_slots(workflow: WorkflowV2) -> list[WorkflowSlotV2]:
    return [slot for node in workflow.nodes for item in active_items(node) for slot in item.slots]


def find_item_any_node(workflow: WorkflowV2, item_id: str) -> WorkflowItemV2 | None:
    for node in workflow.nodes:
        for item in active_items(node):
            if item.item_id == item_id:
                return item
    return None


def slot_is_stale(slot: WorkflowSlotV2) -> bool:
    return slot.status == "stale" or bool(slot.metadata.get("stale"))
