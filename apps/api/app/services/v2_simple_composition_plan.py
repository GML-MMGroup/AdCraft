from __future__ import annotations

from pathlib import Path

from app.schemas.workflow_v2 import (
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_composition import (
    V2FinalCompositionInputSettlement,
    V2SimpleCompositionBgmSource,
    V2SimpleCompositionPlan,
    V2SimpleCompositionVideoSource,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_relative_path


PENDING_STATUSES = {"empty", "ready", "running", "waiting"}
TERMINAL_UNAVAILABLE_STATUSES = {"failed", "skipped"}


class V2SimpleCompositionPlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class V2SimpleCompositionPlanService:
    def __init__(
        self,
        data_dir: Path,
        *,
        asset_store: V2AssetStoreService | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._asset_store = asset_store or V2AssetStoreService(data_dir)

    def inspect(self, workflow: WorkflowV2) -> V2FinalCompositionInputSettlement:
        usable_video_slot_ids: list[str] = []
        unavailable_video_slot_ids: list[str] = []
        pending_slot_ids: list[str] = []
        permanently_blocked_slot_ids: list[str] = []

        for _, slot in self._video_inputs(workflow):
            record = self._selected_record(slot)
            if slot.status in PENDING_STATUSES:
                pending_slot_ids.append(slot.slot_id)
            elif slot.status == "blocked":
                if self._permanently_blocked(workflow, slot):
                    permanently_blocked_slot_ids.append(slot.slot_id)
                    self._classify_terminal_video(
                        slot,
                        record,
                        usable_video_slot_ids,
                        unavailable_video_slot_ids,
                    )
                else:
                    pending_slot_ids.append(slot.slot_id)
            elif slot.status in TERMINAL_UNAVAILABLE_STATUSES:
                self._classify_terminal_video(
                    slot,
                    record,
                    usable_video_slot_ids,
                    unavailable_video_slot_ids,
                )
            elif slot.status == "completed" and record is not None:
                usable_video_slot_ids.append(slot.slot_id)
            else:
                unavailable_video_slot_ids.append(slot.slot_id)

        bgm_slot = self._bgm_slot(workflow)
        bgm_status = "not_requested"
        if workflow.audio_mode != "none":
            bgm_status = "unavailable"
            if bgm_slot is not None:
                record = self._selected_record(bgm_slot)
                if bgm_slot.status in PENDING_STATUSES:
                    bgm_status = "pending"
                    pending_slot_ids.append(bgm_slot.slot_id)
                elif bgm_slot.status == "blocked":
                    if self._permanently_blocked(workflow, bgm_slot):
                        permanently_blocked_slot_ids.append(bgm_slot.slot_id)
                        bgm_status = "available" if record is not None else "unavailable"
                    else:
                        bgm_status = "pending"
                        pending_slot_ids.append(bgm_slot.slot_id)
                elif bgm_slot.status in TERMINAL_UNAVAILABLE_STATUSES:
                    bgm_status = "available" if record is not None else "unavailable"
                elif bgm_slot.status == "completed" and record is not None:
                    bgm_status = "available"

        return V2FinalCompositionInputSettlement(
            settled=not pending_slot_ids,
            usable_video_slot_ids=usable_video_slot_ids,
            unavailable_video_slot_ids=unavailable_video_slot_ids,
            pending_slot_ids=pending_slot_ids,
            permanently_blocked_slot_ids=permanently_blocked_slot_ids,
            bgm_status=bgm_status,
            bgm_slot_id=bgm_slot.slot_id if bgm_slot is not None else None,
        )

    def build(
        self,
        workflow: WorkflowV2,
        *,
        execution_id: str | None = None,
    ) -> V2SimpleCompositionPlan:
        settlement = self.inspect(workflow)
        if not settlement.settled:
            raise V2SimpleCompositionPlanError(
                "composition_inputs_not_settled",
                "Final Composition inputs have not settled.",
            )

        usable_slot_ids = set(settlement.usable_video_slot_ids)
        unavailable_slot_ids = set(settlement.unavailable_video_slot_ids)
        videos: list[V2SimpleCompositionVideoSource] = []
        missing_shot_ids: list[str] = []
        for item, slot in self._video_inputs(workflow):
            if slot.slot_id in unavailable_slot_ids:
                missing_shot_ids.append(item.shot_id or item.item_id)
                continue
            if slot.slot_id not in usable_slot_ids:
                continue
            record = self._selected_record(slot)
            if record is None:
                missing_shot_ids.append(item.shot_id or item.item_id)
                continue
            videos.append(
                V2SimpleCompositionVideoSource(
                    shot_id=item.shot_id or item.item_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    shot_index=item.shot_index or 0,
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    reused_previous_selection=(
                        slot.status in TERMINAL_UNAVAILABLE_STATUSES
                        or slot.slot_id in settlement.permanently_blocked_slot_ids
                    ),
                )
            )

        if not videos:
            raise V2SimpleCompositionPlanError(
                "no_successful_video_segments",
                "No successful storyboard video segments are available.",
            )

        bgm_source: V2SimpleCompositionBgmSource | None = None
        bgm_slot = self._bgm_slot(workflow)
        if settlement.bgm_status == "available" and bgm_slot is not None:
            record = self._selected_record(bgm_slot)
            if record is not None:
                bgm_source = V2SimpleCompositionBgmSource(
                    slot_id=bgm_slot.slot_id,
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    reused_previous_selection=(
                        bgm_slot.status in TERMINAL_UNAVAILABLE_STATUSES
                        or bgm_slot.slot_id in settlement.permanently_blocked_slot_ids
                    ),
                )

        return V2SimpleCompositionPlan(
            workflow_id=workflow.workflow_id,
            videos=videos,
            bgm=bgm_source,
            missing_shot_ids=missing_shot_ids,
            unavailable_video_slot_ids=settlement.unavailable_video_slot_ids,
            bgm_status=settlement.bgm_status,
            created_from_execution_id=execution_id,
        )

    def _selected_record(
        self,
        slot: WorkflowSlotV2,
    ) -> WorkflowAssetVersionV2 | None:
        if not slot.selected_asset_id or not slot.selected_version_id:
            return None
        record = self._asset_store.load_asset_version(
            slot.selected_asset_id,
            slot.selected_version_id,
        )
        if record is None or not record.file_path:
            return None
        relative_path = validate_v2_relative_path(
            record.file_path,
            operation="v2-simple-composition-input",
        )
        path = self._data_dir / relative_path
        return record if path.is_file() and path.stat().st_size > 0 else None

    def _permanently_blocked(
        self,
        workflow: WorkflowV2,
        slot: WorkflowSlotV2,
    ) -> bool:
        if slot.status != "blocked":
            return False
        dependencies = [
            self._find_slot(workflow, dependency_id)
            for dependency_id in slot.dependency_slot_ids
        ]
        return bool(dependencies) and any(
            dependency is not None
            and dependency.status in TERMINAL_UNAVAILABLE_STATUSES
            and self._selected_record(dependency) is None
            for dependency in dependencies
        )

    def _video_inputs(
        self,
        workflow: WorkflowV2,
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        inputs: list[tuple[WorkflowItemV2, WorkflowSlotV2]] = []
        for node in workflow.nodes:
            for item in node.items:
                if item.item_type != "shot" or item.lifecycle_state != "active":
                    continue
                slot = next(
                    (
                        candidate
                        for candidate in item.slots
                        if candidate.slot_type == "shot_video_segment"
                    ),
                    None,
                )
                if slot is not None:
                    inputs.append((item, slot))
        return sorted(
            inputs,
            key=lambda pair: (
                pair[0].shot_index if pair[0].shot_index is not None else 2**31,
                pair[0].item_id,
                pair[1].slot_id,
            ),
        )

    @staticmethod
    def _bgm_slot(workflow: WorkflowV2) -> WorkflowSlotV2 | None:
        for node in workflow.nodes:
            for item in node.items:
                if item.lifecycle_state != "active":
                    continue
                for slot in item.slots:
                    if slot.slot_type == "bgm_audio":
                        return slot
        return None

    @staticmethod
    def _find_slot(workflow: WorkflowV2, slot_id: str) -> WorkflowSlotV2 | None:
        for node in workflow.nodes:
            for item in node.items:
                for slot in item.slots:
                    if slot.slot_id == slot_id:
                        return slot
        return None

    @staticmethod
    def _classify_terminal_video(
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2 | None,
        usable_video_slot_ids: list[str],
        unavailable_video_slot_ids: list[str],
    ) -> None:
        target = usable_video_slot_ids if record is not None else unavailable_video_slot_ids
        target.append(slot.slot_id)
