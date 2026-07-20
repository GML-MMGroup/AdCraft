from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2RunConcurrencyConfig,
    WorkflowItemV2,
    WorkflowMediaTypeV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.v2_slot_scheduler import V2SlotScheduler, active_items
from app.services.v2_storyboard_defaults import shot_cell_slot_types

MAIN_SLOT_TYPES = (
    "product_main_image",
    "character_main_image",
    "scene_main_image",
    "bgm_audio",
)
AUXILIARY_SLOT_TYPES = (
    "product_multi_view_grid",
    "character_three_view",
    "scene_multi_view_grid",
)
SHOT_VIDEO_SLOT_TYPES = ("shot_video_segment",)
FINAL_SLOT_TYPES = ("final_video",)
PARALLEL_SLOT_TYPES = (
    *MAIN_SLOT_TYPES,
    *AUXILIARY_SLOT_TYPES,
    *shot_cell_slot_types(),
    *SHOT_VIDEO_SLOT_TYPES,
)
ALL_SCHEDULABLE_SLOT_TYPES = (*PARALLEL_SLOT_TYPES, *FINAL_SLOT_TYPES)
SOFT_SLOT_TYPES = {
    "product_multi_view_grid",
    "character_three_view",
    "scene_multi_view_grid",
    "bgm_audio",
}


@dataclass
class V2SlotDependencyGraph:
    scheduler: V2SlotScheduler
    workflow: WorkflowV2
    mode: str
    include_failed_slots: bool

    def ready_slots(self) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        targets: list[tuple[WorkflowItemV2, WorkflowSlotV2]] = []
        for node in self.workflow.nodes:
            for item in active_items(node):
                for slot in item.slots:
                    if slot.slot_type not in ALL_SCHEDULABLE_SLOT_TYPES:
                        continue
                    if self.scheduler.slot_is_targetable(
                        self.workflow,
                        slot,
                        mode=self.mode,
                        include_failed=self.include_failed_slots,
                    ):
                        targets.append((item, slot))
        targets.sort(key=lambda pair: slot_schedule_key(pair[1]))
        return targets

    def blocked_slot_ids(self) -> list[str]:
        return [
            slot.slot_id
            for node in self.workflow.nodes
            for item in active_items(node)
            for slot in item.slots
            if slot.status == "blocked"
        ]

    def waiting_slot_ids(self) -> list[str]:
        return [
            slot.slot_id
            for node in self.workflow.nodes
            for item in active_items(node)
            for slot in item.slots
            if slot.status == "waiting"
        ]


@dataclass
class V2ParallelSlotSchedulerState:
    running_counts: Counter[str] = field(default_factory=Counter)
    running_slot_ids: set[str] = field(default_factory=set)

    def can_submit(
        self,
        slot: WorkflowSlotV2,
        config: V2RunConcurrencyConfig,
    ) -> bool:
        if len(self.running_slot_ids) >= config.max_parallel_generation_jobs:
            return False
        return self.running_counts[slot.media_type] < media_limit(slot.media_type, config)

    def mark_submitted(self, slot: WorkflowSlotV2) -> None:
        self.running_slot_ids.add(slot.slot_id)
        self.running_counts[slot.media_type] += 1

    def mark_finished(self, slot: WorkflowSlotV2) -> None:
        self.running_slot_ids.discard(slot.slot_id)
        if self.running_counts[slot.media_type] > 0:
            self.running_counts[slot.media_type] -= 1


def concurrency_config_from_settings(settings: Settings) -> V2RunConcurrencyConfig:
    return V2RunConcurrencyConfig(
        max_parallel_image_jobs=max(1, settings.v2_max_parallel_image_jobs),
        max_parallel_video_jobs=max(1, settings.v2_max_parallel_video_jobs),
        max_parallel_audio_jobs=max(1, settings.v2_max_parallel_audio_jobs),
        max_parallel_generation_jobs=max(1, settings.v2_max_parallel_generation_jobs),
    )


def media_limit(
    media_type: WorkflowMediaTypeV2 | str,
    config: V2RunConcurrencyConfig,
) -> int:
    if media_type == "image":
        return config.max_parallel_image_jobs
    if media_type == "video":
        return config.max_parallel_video_jobs
    if media_type == "audio":
        return config.max_parallel_audio_jobs
    return config.max_parallel_generation_jobs


def slot_schedule_key(slot: WorkflowSlotV2) -> tuple[int, str, str]:
    return (_slot_priority(slot.slot_type), slot.item_id, slot.slot_id)


def is_final_composition_slot(slot: WorkflowSlotV2) -> bool:
    return slot.slot_type == "final_video"


def schedulable_slot_types() -> tuple[str, ...]:
    return ALL_SCHEDULABLE_SLOT_TYPES


def active_slots(workflow: WorkflowV2) -> Iterable[WorkflowSlotV2]:
    for node in workflow.nodes:
        for item in active_items(node):
            yield from item.slots


def _slot_priority(slot_type: str) -> int:
    if slot_type in MAIN_SLOT_TYPES:
        return 10
    if slot_type in AUXILIARY_SLOT_TYPES:
        return 20
    if slot_type in shot_cell_slot_types():
        return 30
    if slot_type == "shot_video_segment":
        return 40
    if slot_type == "final_video":
        return 50
    return 100
