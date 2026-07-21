from typing import Any

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.services.v2_workflow_planner import build_slot


FINAL_COMPOSITION_TIMELINE_ID = "system-final-composition-1"
FINAL_COMPOSITION_PROVIDER = "local_composition_ffmpeg"


class V2FinalCompositionService:
    def ensure_final_composition_item(
        self,
        workflow: WorkflowV2,
        *,
        selected_shot_video_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
        bgm_slot: WorkflowSlotV2 | None,
    ) -> None:
        ensure_final_composition_item(
            workflow,
            selected_shot_video_slots=selected_shot_video_slots,
            bgm_slot=bgm_slot,
        )


def ensure_final_composition_item(
    workflow: WorkflowV2,
    *,
    selected_shot_video_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
    bgm_slot: WorkflowSlotV2 | None,
) -> None:
    final_node = next(
        (node for node in workflow.nodes if node.node_id == "final-composition"), None
    )
    if final_node is None:
        return
    clips = default_timeline_clips(
        workflow,
        selected_shot_video_slots=selected_shot_video_slots,
        bgm_slot=bgm_slot,
    )
    dependency_slot_ids = _dependency_slot_ids(selected_shot_video_slots, bgm_slot)
    existing = next(
        (item for item in final_node.items if item.item_type == "final_composition"),
        None,
    )
    if existing is not None:
        if _manual_timeline_dirty(existing) or existing.timeline_plan.get("canonical_timeline_id"):
            for slot in existing.slots:
                if slot.slot_type == "final_video":
                    slot.dependency_slot_ids = list(dependency_slot_ids)
            return
        existing.timeline_clips = clips
        existing.timeline_plan = build_timeline_plan(
            workflow,
            clips,
            previous_plan=existing.timeline_plan,
        )
        existing.status = "ready"
        for slot in existing.slots:
            if slot.slot_type == "final_video":
                slot.dependency_slot_ids = list(dependency_slot_ids)
        return
    item_id = "final-composition-1"
    final_node.items.append(
        WorkflowItemV2(
            item_id=item_id,
            node_id="final-composition",
            item_type="final_composition",
            display_name="Final Video",
            item_prompt="Assemble selected storyboard video and audio on the final timeline.",
            status="ready",
            timeline_plan=build_timeline_plan(workflow, clips),
            timeline_clips=clips,
            metadata={"available_composition_asset_ids": []},
            slots=[
                build_slot(
                    node_id="final-composition",
                    item_id=item_id,
                    slot_type="final_video",
                    media_type="video",
                    status="ready",
                    prompt="Compose the final ad video from selected storyboard video segments.",
                    dependency_slot_ids=dependency_slot_ids,
                )
            ],
        )
    )


def default_timeline_clips(
    workflow: WorkflowV2,
    *,
    selected_shot_video_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
    bgm_slot: WorkflowSlotV2 | None,
) -> list[dict[str, object]]:
    clips: list[dict[str, object]] = []
    start_time = 0.0
    for order, (shot, slot) in enumerate(selected_shot_video_slots, start=1):
        if not slot.selected_asset_id:
            continue
        duration = float(shot.duration_seconds or 0)
        clips.append(
            {
                "clip_id": f"default-{shot.item_id}-video",
                "source_asset_id": slot.selected_asset_id,
                "source_slot_id": slot.slot_id,
                "clip_type": "video",
                "order": order,
                "start_time": start_time,
                "duration": duration,
                "track_index": 0,
                "trim_in": 0,
                "trim_out": duration,
                "volume": 1,
                "relation_id": None,
                "metadata": {"source": "default_storyboard_order"},
            }
        )
        start_time += duration
    if bgm_slot is not None and bgm_slot.selected_asset_id:
        audio_duration = start_time or float(workflow.duration_seconds)
        clips.append(
            {
                "clip_id": "default-bgm-audio",
                "source_asset_id": bgm_slot.selected_asset_id,
                "source_slot_id": bgm_slot.slot_id,
                "clip_type": "audio",
                "order": 1,
                "start_time": 0,
                "duration": audio_duration,
                "track_index": 10,
                "trim_in": 0,
                "trim_out": audio_duration,
                "volume": 1,
                "relation_id": None,
                "metadata": {"source": "default_bgm_audio_bed"},
            }
        )
    return clips


def build_timeline_plan(
    workflow: WorkflowV2,
    clips: list[dict[str, object]],
    *,
    previous_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_clips = [clip for clip in clips if clip.get("clip_type") == "video"]
    audio_clips = [clip for clip in clips if clip.get("clip_type") == "audio"]
    duration_seconds = _timeline_duration(video_clips)
    version = int((previous_plan or {}).get("version") or 0) + 1
    tracks = [
        {
            "track_id": "video-1",
            "track_type": "video",
            "order": 1,
            "clip_ids": [str(clip["clip_id"]) for clip in video_clips],
        }
    ]
    if audio_clips:
        tracks.append(
            {
                "track_id": "audio-1",
                "track_type": "audio",
                "order": 2,
                "clip_ids": [str(clip["clip_id"]) for clip in audio_clips],
            }
        )
    return {
        "timeline_id": FINAL_COMPOSITION_TIMELINE_ID,
        "version": max(version, 1),
        "source": "default_selected_inputs",
        "duration_seconds": duration_seconds,
        "tracks": tracks,
        "render_settings": {
            "provider": FINAL_COMPOSITION_PROVIDER,
            "aspect_ratio": workflow.aspect_ratio,
            "audio_mode": workflow.audio_mode,
        },
        "source_asset_ids": _ordered_source_asset_ids(clips),
        "manual_timeline_dirty": bool((previous_plan or {}).get("manual_timeline_dirty")),
    }


def _timeline_duration(video_clips: list[dict[str, object]]) -> float:
    duration = 0.0
    for clip in video_clips:
        start = _float(clip.get("start_time"))
        length = _float(clip.get("duration"))
        duration = max(duration, start + length)
    return duration


def _ordered_source_asset_ids(clips: list[dict[str, object]]) -> list[str]:
    asset_ids: list[str] = []
    for clip in clips:
        asset_id = clip.get("source_asset_id")
        if isinstance(asset_id, str) and asset_id:
            asset_ids.append(asset_id)
    return list(dict.fromkeys(asset_ids))


def _dependency_slot_ids(
    selected_shot_video_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
    bgm_slot: WorkflowSlotV2 | None,
) -> list[str]:
    slot_ids = [slot.slot_id for _, slot in selected_shot_video_slots if slot.selected_asset_id]
    if bgm_slot is not None and bgm_slot.selected_asset_id:
        slot_ids.append(bgm_slot.slot_id)
    return list(dict.fromkeys(slot_ids))


def _manual_timeline_dirty(item: WorkflowItemV2) -> bool:
    return bool(
        item.metadata.get("manual_timeline_dirty")
        or item.timeline_plan.get("manual_timeline_dirty")
    )


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0
