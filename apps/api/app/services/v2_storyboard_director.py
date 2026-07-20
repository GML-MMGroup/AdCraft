from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_v2_storyboard_detail import (
    V2StoryboardDetailInput,
    V2StoryboardDetailMaterializationRecord,
    V2StoryboardDetailPlan,
)
from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2, WorkflowV2Event
from app.services.v2_storyboard_detail_materializer import (
    V2StoryboardDetailMaterializer,
    V2StoryboardDetailMaterializerError,
)
from app.services.v2_storyboard_defaults import (
    DEFAULT_STORYBOARD_SHOT_COUNT,
    shot_cell_role,
    shot_cell_slot_types,
)
from app.services.v2_shot_reference_planner import (
    reference_dependency_slot_ids,
    resolve_storyboard_shot_references,
)
from app.services.v2_storyboard_cell_prompts import (
    cell_prompt_record_for_slot,
    cell_prompt_records_by_slot,
    enrich_detail_prompts_with_cell_records,
    storyboard_cell_prompt_records,
)
from app.services.v2_versioning import V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION
from app.services.v2_workflow_planner import build_slot

SUPPORTED_SHOT_VIDEO_DURATIONS = (5, 10)


class V2StoryboardDirector:
    def __init__(self, settings: Settings | None = None) -> None:
        self._materializer = V2StoryboardDetailMaterializer(settings)

    def ensure_storyboard_shots(
        self,
        workflow: WorkflowV2,
        *,
        include_slots: bool = True,
    ) -> None:
        synchronize_storyboard_structure(
            workflow,
            include_slots=include_slots,
        )
        if include_slots:
            self.prepare_details(
                workflow,
                append_event=lambda *_args, **_kwargs: None,
                execution_id="compatibility",
            )

    def synchronize_structure(
        self,
        workflow: WorkflowV2,
        *,
        include_slots: bool = True,
    ) -> None:
        """Synchronize shot shells, references, and dependencies without calling an LLM."""
        synchronize_storyboard_structure(workflow, include_slots=include_slots)

    def prepare_details(
        self,
        workflow: WorkflowV2,
        *,
        append_event: Callable[..., WorkflowV2Event | None],
        execution_id: str,
    ) -> list[str]:
        return prepare_storyboard_details(
            workflow,
            materializer=self._materializer,
            append_event=append_event,
            execution_id=execution_id,
        )

    def refine_shot_summary(
        self,
        workflow: WorkflowV2,
        shot: WorkflowItemV2,
        shot_summary_prompt: str,
    ) -> None:
        refine_shot_summary(
            shot,
            shot_summary_prompt,
            workflow=workflow,
            materializer=self._materializer,
            force_mock=False,
        )

    def materialize_detail_prompts_for_shot(
        self,
        workflow: WorkflowV2,
        shot: WorkflowItemV2,
        *,
        summary: str,
    ) -> dict[str, Any]:
        desired_duration = int(
            shot.metadata.get("desired_duration_seconds") or shot.duration_seconds or 5
        )
        provider_duration = int(
            shot.metadata.get("provider_duration_seconds")
            or normalize_provider_duration(desired_duration)
        )
        return materialize_shot_detail_prompts(
            summary=summary,
            script_shot=shot.metadata.get("source_script_shot")
            if isinstance(shot.metadata.get("source_script_shot"), dict)
            else {},
            desired_duration_seconds=desired_duration,
            provider_duration_seconds=provider_duration,
            workflow=workflow,
            shot_id=shot.shot_id or shot.item_id,
            shot_index=shot.shot_index or 1,
            materializer=self._materializer,
            force_mock=False,
        )


def ensure_storyboard_shots(
    workflow: WorkflowV2,
    *,
    materializer: V2StoryboardDetailMaterializer | None = None,
    force_mock: bool = True,
    include_slots: bool = True,
) -> None:
    """Compatibility entry point that performs structure sync and detail preparation."""
    synchronize_storyboard_structure(workflow, include_slots=include_slots)
    if include_slots:
        prepare_storyboard_details(
            workflow,
            materializer=materializer or V2StoryboardDetailMaterializer(),
            append_event=lambda *_args, **_kwargs: None,
            execution_id="compatibility",
            force_mock=force_mock,
        )


def synchronize_storyboard_structure(
    workflow: WorkflowV2,
    *,
    include_slots: bool = True,
) -> None:
    storyboard = next((node for node in workflow.nodes if node.node_id == "storyboard"), None)
    if storyboard is None:
        return
    script_shots = _script_plan_shots(workflow)
    script_shots = _shots_for_target_count(
        workflow,
        script_shots,
        _target_shot_count(workflow, len(script_shots)),
    )
    resolved_shots = resolve_storyboard_shot_references(workflow, script_shots)
    script_shots = [result.shot for result in resolved_shots]
    reference_sources = {
        str(result.shot.get("shot_id") or f"shot-{index}"): result.reference_source
        for index, result in enumerate(resolved_shots, start=1)
    }
    expected_ids = {
        str(shot.get("shot_id") or f"shot-{index}")
        for index, shot in enumerate(script_shots, start=1)
    }
    storyboard.items = [
        item
        for item in storyboard.items
        if item.lifecycle_state != "active" or (item.shot_id or item.item_id) in expected_ids
    ]
    active_by_id = {
        item.shot_id or item.item_id: item
        for item in storyboard.items
        if item.lifecycle_state == "active"
    }
    start_seconds = 0
    for fallback_index, script_shot in enumerate(script_shots, start=1):
        shot_id = str(script_shot.get("shot_id") or f"shot-{fallback_index}")
        desired_duration = int(script_shot.get("duration_seconds") or 5)
        end_seconds = start_seconds + desired_duration
        time_range = {"start_seconds": start_seconds, "end_seconds": end_seconds}
        existing = active_by_id.get(shot_id)
        reference_source = reference_sources.get(shot_id, "deterministic_fallback")
        if existing is not None:
            _sync_shot_reference_metadata(
                workflow,
                existing,
                script_shot,
                reference_source=reference_source,
            )
            if include_slots:
                ensure_shot_structure(existing, materialize_missing=False)
                _apply_reference_metadata_to_slots(existing)
            existing.duration_seconds = desired_duration
            existing.metadata["time_range"] = time_range
            existing.metadata["desired_duration_seconds"] = desired_duration
            for slot in existing.slots:
                if slot.slot_type == "shot_video_segment":
                    slot.provider_params["duration_seconds"] = desired_duration
            start_seconds = end_seconds
            continue
        shot_index = int(script_shot.get("shot_index") or fallback_index)
        summary = _shot_summary(script_shot, _storyboard_fallback_context(workflow))
        provider_duration = normalize_provider_duration(desired_duration)
        reference_item_ids = _reference_item_ids(script_shot)
        detail_prompts = (
            _placeholder_detail_prompts(
                summary=summary,
                shot_id=shot_id,
                shot_index=shot_index,
                desired_duration_seconds=desired_duration,
                provider_duration_seconds=provider_duration,
            )
            if include_slots
            else {}
        )
        primary_scene_item_id = str(script_shot.get("scene_id") or "").strip() or None
        detail_prompts, cell_prompt_records, _cell_warnings = (
            enrich_detail_prompts_with_cell_records(
                shot_id=shot_id,
                summary_prompt=summary,
                detail_prompts=detail_prompts,
                reference_item_ids=reference_item_ids,
            )
        )
        reference_dependency_ids = reference_dependency_slot_ids(workflow, reference_item_ids)
        storyboard.items.append(
            WorkflowItemV2(
                item_id=shot_id,
                node_id="storyboard",
                item_type="shot",
                display_name=f"Shot {shot_index}",
                item_prompt=summary,
                status="empty",
                shot_id=shot_id,
                shot_index=shot_index,
                aspect_ratio=workflow.aspect_ratio,
                duration_seconds=desired_duration,
                summary_prompt=summary,
                cell_prompts=cell_prompt_records,
                shot_summary_prompt=summary,
                detail_prompts=detail_prompts,
                reference_item_ids=reference_item_ids,
                primary_scene_item_id=primary_scene_item_id,
                reference_source=reference_source,
                slots=shot_slots(
                    shot_id,
                    summary,
                    detail_prompts=detail_prompts,
                    provider_duration_seconds=provider_duration,
                    reference_item_ids=reference_item_ids,
                    reference_source=reference_source,
                    cell_prompt_records=cell_prompt_records,
                    reference_dependency_slot_ids=reference_dependency_ids,
                )
                if include_slots
                else [],
                metadata={
                    "grid_layout": "2x2",
                    "source_script_shot": script_shot,
                    "reference_item_ids": reference_item_ids,
                    "primary_scene_item_id": primary_scene_item_id,
                    "reference_source": reference_source,
                    "reference_dependency_slot_ids": reference_dependency_ids,
                    "reference_warnings": script_shot.get("reference_warnings", []),
                    "summary_prompt_source": _summary_source(script_shot),
                    "detail_prompt_sources": _detail_prompt_sources(),
                    "detail_prompt_dirty_fields": [],
                    "desired_duration_seconds": desired_duration,
                    "provider_duration_seconds": provider_duration,
                    "time_range": time_range,
                    "time_segments": detail_prompts.get("time_segments", []),
                    "materializer_version": V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
                },
            )
        )
        _apply_reference_metadata_to_slots(storyboard.items[-1])
        start_seconds = end_seconds


def prepare_storyboard_details(
    workflow: WorkflowV2,
    *,
    materializer: V2StoryboardDetailMaterializer,
    append_event: Callable[..., WorkflowV2Event | None],
    execution_id: str,
    force_mock: bool = False,
) -> list[str]:
    """Materialize each changed shot once, outside the scheduler's steady-state loop."""
    storyboard = next((node for node in workflow.nodes if node.node_id == "storyboard"), None)
    if storyboard is None:
        return []
    prepared: list[str] = []
    for shot in storyboard.items:
        if shot.lifecycle_state != "active" or shot.item_type != "shot":
            continue
        input_data = _build_storyboard_detail_input(workflow, shot)
        fingerprint = storyboard_detail_input_fingerprint(workflow, shot, input_data)
        existing_record = _detail_materialization_record(shot)
        if (
            existing_record is not None
            and existing_record.input_fingerprint == fingerprint
            and _has_complete_detail_contract(shot.detail_prompts)
        ):
            continue
        if existing_record is None and _can_adopt_legacy_details(shot.detail_prompts):
            shot.metadata["detail_materialization"] = V2StoryboardDetailMaterializationRecord(
                input_fingerprint=fingerprint,
                script_version_id=str(workflow.metadata.get("selected_script_version_id") or ""),
                materializer_version=str(
                    shot.detail_prompts.get("materializer_version")
                    or V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION
                ),
                prompt_lineage=_prompt_lineage(workflow, input_data),
                mode="reused",
                warnings=list(shot.detail_prompts.get("warnings") or []),
                updated_at=datetime.now(timezone.utc),
            ).model_dump(mode="json")
            continue
        fallback_used = False
        try:
            plan = materializer.materialize_detail(input_data, force_mock=force_mock)
        except V2StoryboardDetailMaterializerError as exc:
            fallback_used = True
            plan = materializer.deterministic_fallback(
                input_data,
                error_code=exc.code,
                error_message=str(exc),
            )
        details = detail_plan_to_prompts(plan)
        if plan.materializer_mode == "fallback":
            fallback_used = True
        _apply_prepared_details(shot, details)
        record = V2StoryboardDetailMaterializationRecord(
            input_fingerprint=fingerprint,
            script_version_id=str(workflow.metadata.get("selected_script_version_id") or ""),
            materializer_version=plan.materializer_version,
            prompt_lineage=_prompt_lineage(workflow, input_data),
            mode="deterministic_fallback" if fallback_used else "llm",
            warnings=list(plan.warnings),
            updated_at=datetime.now(timezone.utc),
        )
        shot.metadata["detail_materialization"] = record.model_dump(mode="json")
        prepared.append(shot.item_id)
        if fallback_used:
            append_event(
                workflow.workflow_id,
                "storyboard_detail_fallback_used",
                node_id="storyboard",
                item_id=shot.item_id,
                payload={
                    "execution_id": execution_id,
                    "shot_id": shot.shot_id or shot.item_id,
                    "input_fingerprint": fingerprint,
                    "warnings": list(plan.warnings),
                },
            )
    return prepared


def storyboard_detail_input_fingerprint(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
    input_data: V2StoryboardDetailInput,
) -> str:
    selected_reference_version_ids = [
        str(summary.get("version_id") or summary.get("selected_version_id") or "")
        for summary in input_data.selected_reference_summaries
        if isinstance(summary, dict)
    ]
    payload = {
        "aspect_ratio": workflow.aspect_ratio,
        "desired_duration_seconds": input_data.desired_duration_seconds,
        "materializer_version": V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
        "ordered_reference_item_ids": list(shot.reference_item_ids),
        "ordered_selected_reference_version_ids": selected_reference_version_ids,
        "prompt_lineage": _prompt_lineage(workflow, input_data),
        "provider_duration_seconds": input_data.provider_duration_seconds,
        "script_version_id": str(workflow.metadata.get("selected_script_version_id") or ""),
        "shot_id": input_data.shot_id,
        "shot_index": input_data.shot_index,
        "shot_summary_prompt": input_data.shot_summary_prompt,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _build_storyboard_detail_input(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
) -> V2StoryboardDetailInput:
    desired_duration = int(
        shot.metadata.get("desired_duration_seconds") or shot.duration_seconds or 5
    )
    provider_duration = int(
        shot.metadata.get("provider_duration_seconds")
        or normalize_provider_duration(desired_duration)
    )
    script_shot = (
        shot.metadata.get("source_script_shot")
        if isinstance(shot.metadata.get("source_script_shot"), dict)
        else {}
    )
    summary = (
        shot.shot_summary_prompt
        or shot.item_prompt
        or _shot_summary(
            script_shot,
            _storyboard_fallback_context(workflow),
        )
    )
    reference_item_ids = list(shot.reference_item_ids or _reference_item_ids(script_shot))
    continuity = _previous_continuity_context(workflow, shot.shot_index or 1)
    return V2StoryboardDetailInput(
        workflow_id=workflow.workflow_id,
        shot_id=shot.shot_id or shot.item_id,
        shot_index=shot.shot_index or 1,
        shot_summary_prompt=summary,
        script_shot=script_shot,
        workflow_aspect_ratio=workflow.aspect_ratio,
        desired_duration_seconds=desired_duration,
        provider_duration_seconds=provider_duration,  # type: ignore[arg-type]
        product_brief_summaries=_brief_summaries(
            workflow,
            "product-generation",
            reference_item_ids,
        ),
        character_brief_summaries=_brief_summaries(
            workflow,
            "character-generation",
            reference_item_ids,
        ),
        scene_brief_summaries=_brief_summaries(
            workflow,
            "scene-generation",
            reference_item_ids,
        ),
        selected_reference_summaries=_selected_reference_summaries(
            workflow,
            reference_item_ids,
        ),
        skill_context={"style": workflow.metadata.get("visual_style")}
        if workflow.metadata.get("visual_style")
        else {},
        prompt_profile_id=str(workflow.metadata.get("prompt_profile_id") or "") or None,
        previous_transition_summary=continuity["previous_transition_summary"],
        previous_product_state=continuity["previous_product_state"],
        previous_story_state=continuity["previous_story_state"],
    )


def _prompt_lineage(
    workflow: WorkflowV2,
    input_data: V2StoryboardDetailInput,
) -> dict[str, Any]:
    registry_lineage = workflow.metadata.get("prompt_registry_lineage")
    return {
        "materializer_version": V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
        "prompt_profile_id": input_data.prompt_profile_id,
        "prompt_registry_lineage": registry_lineage if isinstance(registry_lineage, dict) else {},
    }


def _detail_materialization_record(
    shot: WorkflowItemV2,
) -> V2StoryboardDetailMaterializationRecord | None:
    raw_record = shot.metadata.get("detail_materialization")
    if not isinstance(raw_record, dict):
        return None
    try:
        return V2StoryboardDetailMaterializationRecord.model_validate(raw_record)
    except ValueError:
        return None


def _has_complete_detail_contract(details: dict[str, Any]) -> bool:
    cell_prompts = details.get("cell_prompts")
    if not isinstance(cell_prompts, dict):
        return False
    return all(
        isinstance(cell_prompts.get(slot_type), dict)
        and bool(str(cell_prompts[slot_type].get("provider_prompt") or "").strip())
        for slot_type in shot_cell_slot_types()
    ) and bool(str(details.get("video_provider_prompt") or "").strip())


def _can_adopt_legacy_details(details: dict[str, Any]) -> bool:
    return (
        _has_complete_detail_contract(details)
        and details.get("materializer_mode") != "pending_preflight"
    )


def _apply_prepared_details(shot: WorkflowItemV2, details: dict[str, Any]) -> None:
    preserved = dict(shot.detail_prompts)
    for field in list(shot.metadata.get("detail_prompt_dirty_fields") or []):
        if field in preserved:
            details[field] = preserved[field]
    summary = shot.shot_summary_prompt or shot.item_prompt or "Storyboard shot"
    details, cell_prompt_records, _warnings = enrich_detail_prompts_with_cell_records(
        shot_id=shot.shot_id or shot.item_id,
        summary_prompt=summary,
        detail_prompts=details,
        reference_item_ids=shot.reference_item_ids,
    )
    shot.detail_prompts = details
    shot.cell_prompts = cell_prompt_records
    shot.metadata.update(
        {
            "detail_prompt_sources": _detail_prompt_sources(),
            "desired_duration_seconds": details.get("desired_duration_seconds"),
            "provider_duration_seconds": details.get("provider_duration_seconds"),
            "time_segments": details.get("time_segments", []),
            "materializer_version": details.get("materializer_version"),
        }
    )
    for slot in shot.slots:
        if slot.manual_prompt_dirty or slot.prompt_source == "user" or slot.user_prompt:
            continue
        if slot.slot_type.startswith("shot_cell_"):
            record = _cell_prompt_record_for_shot(shot, slot.slot_type)
            prompt = str(record["provider_prompt"])
            slot.slot_prompt = prompt
            slot.system_suggested_prompt = prompt
            slot.metadata.update(_slot_cell_prompt_metadata(record))
        elif slot.slot_type == "shot_video_segment":
            apply_shot_video_prompts(slot, summary, detail_prompts=details)
            slot.system_suggested_prompt = slot.slot_prompt


def _placeholder_detail_prompts(
    *,
    summary: str,
    shot_id: str,
    shot_index: int,
    desired_duration_seconds: int,
    provider_duration_seconds: int,
) -> dict[str, Any]:
    return {
        "shot_id": shot_id,
        "shot_index": shot_index,
        "storyboard_content": summary,
        "dialogue": "No spoken dialogue.",
        "audio_description": "Natural production sound only.",
        "voice_style": "No voice performance required.",
        "video_negative_constraints": "No watermark. No subtitles.",
        "video_provider_prompt": f"Create one video segment for this shot: {summary}",
        "time_segments": [],
        "desired_duration_seconds": desired_duration_seconds,
        "provider_duration_seconds": provider_duration_seconds,
        "required_shot_cell_slot_ids": [f"{shot_id}:shot_cell_{index}" for index in range(1, 5)],
        "required_shot_cell_asset_ids": [],
        "cell_prompts": {
            slot_type: {
                "provider_prompt": shot_cell_prompt(summary, slot_type),
                "negative_prompt": "No storyboard sheet or captions.",
                "negative_constraints": ["No storyboard sheet", "No captions"],
                "cell_role": shot_cell_role(slot_type),
                "cell_index": index,
                "continuity_notes": "Preserve same-shot visual continuity.",
                "required_reference_asset_ids": [],
            }
            for index, slot_type in enumerate(shot_cell_slot_types(), start=1)
        },
        "reference_item_ids": [],
        "reference_asset_ids": [],
        "materializer_mode": "pending_preflight",
        "model_id": None,
        "quality_notes": [],
        "warnings": [],
        "materializer_version": V2_STORYBOARD_DETAIL_MATERIALIZER_VERSION,
    }


def _materialize_linked_shot_details(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
    script_shot: dict[str, Any],
    *,
    desired_duration_seconds: int,
    materializer: V2StoryboardDetailMaterializer | None,
    force_mock: bool,
) -> None:
    if shot.detail_prompts.get("materializer_mode") != "linked_context":
        return
    summary = _shot_summary(script_shot, _storyboard_fallback_context(workflow))
    provider_duration = normalize_provider_duration(desired_duration_seconds)
    details = materialize_shot_detail_prompts(
        summary=summary,
        script_shot=script_shot,
        desired_duration_seconds=desired_duration_seconds,
        provider_duration_seconds=provider_duration,
        workflow=workflow,
        shot_id=shot.shot_id or shot.item_id,
        shot_index=shot.shot_index or 1,
        materializer=materializer,
        force_mock=force_mock,
    )
    _apply_prepared_details(shot, details)
    if not shot.user_prompt and not shot.manual_prompt_dirty and shot.prompt_source != "user":
        shot.shot_summary_prompt = summary
        shot.item_prompt = summary
        shot.system_suggested_prompt = summary
    shot.metadata.update(
        {
            "summary_prompt_source": _summary_source(script_shot),
            "detail_prompt_sources": _detail_prompt_sources(),
            "detail_prompt_dirty_fields": [],
            "desired_duration_seconds": desired_duration_seconds,
            "provider_duration_seconds": provider_duration,
            "time_segments": details.get("time_segments", []),
            "materializer_version": details.get("materializer_version"),
        }
    )


def _sync_shot_reference_metadata(
    workflow: WorkflowV2,
    shot: WorkflowItemV2,
    script_shot: dict[str, Any],
    *,
    reference_source: str,
) -> None:
    reference_item_ids = _reference_item_ids(script_shot)
    primary_scene_item_id = str(script_shot.get("scene_id") or "").strip() or None
    shot.reference_item_ids = reference_item_ids
    shot.primary_scene_item_id = primary_scene_item_id
    shot.reference_source = reference_source  # type: ignore[assignment]
    shot.summary_prompt = shot.shot_summary_prompt or shot.item_prompt
    shot.metadata["source_script_shot"] = script_shot
    shot.metadata["reference_item_ids"] = reference_item_ids
    shot.metadata["primary_scene_item_id"] = primary_scene_item_id
    shot.metadata["reference_source"] = reference_source
    shot.metadata["reference_dependency_slot_ids"] = reference_dependency_slot_ids(
        workflow,
        reference_item_ids,
    )
    shot.metadata["reference_warnings"] = script_shot.get("reference_warnings", [])
    _apply_reference_metadata_to_slots(shot)


def _apply_reference_metadata_to_slots(shot: WorkflowItemV2) -> None:
    dependencies = list(shot.metadata.get("reference_dependency_slot_ids") or [])
    for slot in shot.slots:
        slot.metadata["reference_item_ids"] = list(shot.reference_item_ids)
        slot.metadata["reference_source"] = shot.reference_source
        if slot.slot_type.startswith("shot_cell_"):
            slot.dependency_slot_ids = dependencies
            record = _cell_prompt_record_for_shot(shot, slot.slot_type)
            slot.metadata.update(_slot_cell_prompt_metadata(record))
            if not slot.manual_prompt_dirty:
                slot.slot_prompt = str(record.get("provider_prompt") or slot.slot_prompt or "")


def refine_shot_summary(
    shot: WorkflowItemV2,
    shot_summary_prompt: str,
    *,
    workflow: WorkflowV2 | None = None,
    materializer: V2StoryboardDetailMaterializer | None = None,
    force_mock: bool = True,
) -> None:
    shot.summary_prompt = shot_summary_prompt
    shot.shot_summary_prompt = shot_summary_prompt
    shot.item_prompt = shot_summary_prompt
    shot.metadata["summary_prompt_source"] = "user"
    desired_duration = int(
        shot.metadata.get("desired_duration_seconds") or shot.duration_seconds or 5
    )
    provider_duration = int(
        shot.metadata.get("provider_duration_seconds")
        or normalize_provider_duration(desired_duration)
    )
    detail_prompts = materialize_shot_detail_prompts(
        summary=shot_summary_prompt,
        script_shot=shot.metadata.get("source_script_shot")
        if isinstance(shot.metadata.get("source_script_shot"), dict)
        else {},
        desired_duration_seconds=desired_duration,
        provider_duration_seconds=provider_duration,
        workflow=workflow,
        shot_id=shot.shot_id or shot.item_id,
        shot_index=shot.shot_index or 1,
        materializer=materializer,
        force_mock=force_mock,
    )
    shot.detail_prompts, shot.cell_prompts, _warnings = enrich_detail_prompts_with_cell_records(
        shot_id=shot.shot_id or shot.item_id,
        summary_prompt=shot_summary_prompt,
        detail_prompts=detail_prompts,
        reference_item_ids=shot.reference_item_ids,
    )
    shot.metadata["detail_prompts_outdated"] = False
    shot.metadata["detail_prompt_dirty_fields"] = []
    shot.metadata["materializer_version"] = shot.detail_prompts.get("materializer_version")
    shot.metadata["time_segments"] = shot.detail_prompts.get("time_segments", [])
    for slot in shot.slots:
        if slot.slot_type.startswith("shot_cell_"):
            record = _cell_prompt_record_for_shot(shot, slot.slot_type)
            slot.slot_prompt = str(record["provider_prompt"])
            slot.metadata.update(_slot_cell_prompt_metadata(record))
            if slot.selected_asset_id:
                slot.metadata["linked_source_has_new_version"] = True
        elif slot.slot_type == "shot_video_segment":
            apply_shot_video_prompts(slot, shot_summary_prompt, detail_prompts=shot.detail_prompts)


def shot_slots(
    shot_id: str,
    summary: str,
    *,
    detail_prompts: dict[str, Any],
    provider_duration_seconds: int,
    reference_item_ids: list[str] | None = None,
    reference_source: str | None = None,
    cell_prompt_records: list[dict[str, Any]] | None = None,
    reference_dependency_slot_ids: list[str] | None = None,
) -> list[WorkflowSlotV2]:
    reference_item_ids = reference_item_ids or []
    reference_dependency_slot_ids = reference_dependency_slot_ids or []
    if cell_prompt_records is None:
        cell_prompt_records, _warnings = storyboard_cell_prompt_records(
            shot_id=shot_id,
            summary_prompt=summary,
            detail_prompts=detail_prompts,
            reference_item_ids=reference_item_ids,
        )
    cell_prompts_by_slot = cell_prompt_records_by_slot(cell_prompt_records)
    slots: list[WorkflowSlotV2] = [
        build_slot(
            node_id="storyboard",
            item_id=shot_id,
            slot_type=slot_type,
            media_type="image",
            status="empty",
            prompt=str(cell_prompts_by_slot[slot_type]["provider_prompt"]),
            dependency_slot_ids=reference_dependency_slot_ids,
            metadata={
                "grid_layout": "2x2",
                "reference_item_ids": list(reference_item_ids),
                "reference_source": reference_source,
                **_slot_cell_prompt_metadata(cell_prompts_by_slot[slot_type]),
            },
        )
        for slot_type in shot_cell_slot_types()
    ]
    video_slot = build_slot(
        node_id="storyboard",
        item_id=shot_id,
        slot_type="shot_video_segment",
        media_type="video",
        status="blocked",
        prompt=video_prompt_from_details(detail_prompts),
        dependency_slot_ids=[f"{shot_id}:{slot_type}" for slot_type in shot_cell_slot_types()],
    )
    apply_shot_video_prompts(video_slot, summary, detail_prompts=detail_prompts)
    video_slot.provider_params["duration_seconds"] = (
        detail_prompts.get("desired_duration_seconds") or provider_duration_seconds
    )
    video_slot.metadata["reference_item_ids"] = list(reference_item_ids)
    video_slot.metadata["reference_source"] = reference_source
    slots.append(video_slot)
    return slots


def ensure_shot_structure(
    shot: WorkflowItemV2,
    *,
    materialize_missing: bool = True,
) -> None:
    existing = {slot.slot_type: slot for slot in shot.slots}
    summary = shot.shot_summary_prompt or shot.item_prompt or f"Shot {shot.shot_index or ''}"
    shot.summary_prompt = shot.summary_prompt or summary
    shot.shot_summary_prompt = shot.shot_summary_prompt or summary
    desired_duration = int(
        shot.metadata.get("desired_duration_seconds") or shot.duration_seconds or 5
    )
    provider_duration = int(
        shot.metadata.get("provider_duration_seconds")
        or normalize_provider_duration(desired_duration)
    )
    if not shot.detail_prompts:
        if materialize_missing:
            shot.detail_prompts = materialize_shot_detail_prompts(
                summary=summary,
                script_shot=shot.metadata.get("source_script_shot")
                if isinstance(shot.metadata.get("source_script_shot"), dict)
                else {},
                desired_duration_seconds=desired_duration,
                provider_duration_seconds=provider_duration,
            )
        else:
            shot.detail_prompts = _placeholder_detail_prompts(
                summary=summary,
                shot_id=shot.shot_id or shot.item_id,
                shot_index=shot.shot_index or 1,
                desired_duration_seconds=desired_duration,
                provider_duration_seconds=provider_duration,
            )
    elif materialize_missing and not _has_storyboard_video_details(shot.detail_prompts):
        shot.detail_prompts = materialize_shot_detail_prompts(
            summary=summary,
            script_shot=shot.metadata.get("source_script_shot")
            if isinstance(shot.metadata.get("source_script_shot"), dict)
            else {},
            desired_duration_seconds=desired_duration,
            provider_duration_seconds=provider_duration,
        )
    shot.detail_prompts, shot.cell_prompts, _warnings = enrich_detail_prompts_with_cell_records(
        shot_id=shot.shot_id or shot.item_id,
        summary_prompt=summary,
        detail_prompts=shot.detail_prompts,
        reference_item_ids=shot.reference_item_ids,
    )
    for slot_type in shot_cell_slot_types():
        if slot_type in existing:
            continue
        record = _cell_prompt_record_for_shot(shot, slot_type)
        slot = build_slot(
            node_id="storyboard",
            item_id=shot.item_id,
            slot_type=slot_type,
            media_type="image",
            status="empty",
            prompt=str(record["provider_prompt"]),
            dependency_slot_ids=list(shot.metadata.get("reference_dependency_slot_ids") or []),
            metadata={
                "grid_layout": "2x2",
                "reference_item_ids": list(shot.reference_item_ids),
                "reference_source": shot.reference_source,
                **_slot_cell_prompt_metadata(record),
            },
        )
        shot.slots.append(slot)
    if "shot_video_segment" not in existing:
        video_slot = build_slot(
            node_id="storyboard",
            item_id=shot.item_id,
            slot_type="shot_video_segment",
            media_type="video",
            status="blocked",
            prompt=video_prompt_from_details(shot.detail_prompts),
            dependency_slot_ids=[
                f"{shot.item_id}:{slot_type}" for slot_type in shot_cell_slot_types()
            ],
        )
        apply_shot_video_prompts(video_slot, summary, detail_prompts=shot.detail_prompts)
        video_slot.provider_params["duration_seconds"] = provider_duration
        video_slot.metadata["reference_item_ids"] = list(shot.reference_item_ids)
        video_slot.metadata["reference_source"] = shot.reference_source
        shot.slots.append(video_slot)
    _apply_reference_metadata_to_slots(shot)


def _has_storyboard_video_details(detail_prompts: dict[str, Any]) -> bool:
    return all(
        isinstance(detail_prompts.get(key), str) and str(detail_prompts[key]).strip()
        for key in ("storyboard_content", "video_provider_prompt")
    )


def shot_detail_prompts(summary: str) -> dict[str, Any]:
    return materialize_shot_detail_prompts(
        summary=summary,
        script_shot={},
        desired_duration_seconds=5,
        provider_duration_seconds=5,
    )


def materialize_shot_detail_prompts(
    *,
    summary: str,
    script_shot: dict[str, Any],
    desired_duration_seconds: int,
    provider_duration_seconds: int | None = None,
    workflow: WorkflowV2 | None = None,
    shot_id: str = "shot-1",
    shot_index: int = 1,
    materializer: V2StoryboardDetailMaterializer | None = None,
    force_mock: bool = True,
    previous_transition_summary: str | None = None,
    previous_product_state: str | None = None,
    previous_story_state: str | None = None,
) -> dict[str, Any]:
    provider_duration = provider_duration_seconds or normalize_provider_duration(
        desired_duration_seconds
    )
    reference_item_ids = _reference_item_ids(script_shot)
    continuity = _previous_continuity_context(workflow, shot_index)
    detail_input = V2StoryboardDetailInput(
        workflow_id=workflow.workflow_id if workflow is not None else "v2_storyboard_detail",
        shot_id=shot_id,
        shot_index=shot_index,
        shot_summary_prompt=summary,
        script_shot=script_shot,
        workflow_aspect_ratio=workflow.aspect_ratio if workflow is not None else "16:9",
        desired_duration_seconds=desired_duration_seconds,
        provider_duration_seconds=provider_duration,  # type: ignore[arg-type]
        product_brief_summaries=_brief_summaries(
            workflow,
            "product-generation",
            reference_item_ids,
        ),
        character_brief_summaries=_brief_summaries(
            workflow,
            "character-generation",
            reference_item_ids,
        ),
        scene_brief_summaries=_brief_summaries(
            workflow,
            "scene-generation",
            reference_item_ids,
        ),
        selected_reference_summaries=_selected_reference_summaries(
            workflow,
            reference_item_ids,
        ),
        skill_context={"style": workflow.metadata.get("visual_style")}
        if workflow is not None and workflow.metadata.get("visual_style")
        else {},
        previous_transition_summary=(
            previous_transition_summary or continuity["previous_transition_summary"]
        ),
        previous_product_state=(previous_product_state or continuity["previous_product_state"]),
        previous_story_state=previous_story_state or continuity["previous_story_state"],
    )
    service = materializer or V2StoryboardDetailMaterializer()
    plan = service.materialize_detail(detail_input, force_mock=force_mock)
    return detail_plan_to_prompts(plan)


def detail_plan_to_prompts(plan: V2StoryboardDetailPlan) -> dict[str, Any]:
    video = plan.video_detail
    cell_records = [
        {
            "slot_id": f"{plan.shot_id}:{cell.slot_type}",
            "slot_type": cell.slot_type,
            "cell_id": cell.slot_type,
            "sequence_index": cell.cell_index,
            "sequence_role": cell.cell_role,
            "cell_index": cell.cell_index,
            "cell_role": cell.cell_role,
            "summary_prompt": plan.shot_summary_prompt,
            "provider_prompt": cell.provider_prompt,
            "negative_prompt": cell.negative_prompt,
            "negative_constraints": list(cell.negative_constraints),
            "continuity_notes": cell.continuity_notes,
            "reference_item_ids": list(plan.reference_item_ids),
            "required_reference_asset_ids": list(cell.required_reference_asset_ids),
        }
        for cell in plan.cell_prompts
    ]
    return {
        "shot_id": plan.shot_id,
        "shot_index": plan.shot_index,
        "shot_summary_prompt": plan.shot_summary_prompt,
        "summary_prompt": plan.shot_summary_prompt,
        "storyboard_content": video.storyboard_content,
        "dialogue": video.dialogue,
        "audio_description": video.audio_description,
        "voice_style": video.voice_style,
        "video_negative_constraints": video.video_negative_constraints,
        "video_provider_prompt": video.provider_prompt,
        "time_segments": [segment.model_dump(mode="json") for segment in video.time_segments],
        "desired_duration_seconds": video.desired_duration_seconds,
        "provider_duration_seconds": video.provider_duration_seconds,
        "required_shot_cell_slot_ids": video.required_shot_cell_slot_ids,
        "required_shot_cell_asset_ids": video.required_shot_cell_asset_ids,
        "cell_prompts": cell_prompt_records_by_slot(cell_records),
        "cell_prompt_records": cell_records,
        "reference_item_ids": plan.reference_item_ids,
        "reference_asset_ids": plan.reference_asset_ids,
        "materializer_mode": plan.materializer_mode,
        "model_id": plan.model_id,
        "quality_notes": plan.quality_notes,
        "warnings": plan.warnings,
        "materializer_version": plan.materializer_version,
    }


def shot_cell_prompt(summary: str, slot_type: str) -> str:
    return (
        f"{slot_type} single full-frame keyframe prompt ({shot_cell_role(slot_type)}). "
        "Maintain same-shot "
        "visual continuity, product identity, character identity, scene identity, style, "
        f"lighting, and time context. Shot summary: {summary}"
    )


def cell_prompt_from_details(
    details: dict[str, Any],
    slot_type: str,
    *,
    summary: str,
) -> str:
    record = cell_prompt_record_for_slot(
        shot_id=str(details.get("shot_id") or "shot"),
        summary_prompt=summary,
        detail_prompts=details,
        slot_type=slot_type,
        reference_item_ids=[
            str(item_id)
            for item_id in details.get("reference_item_ids", [])
            if str(item_id).strip()
        ],
    )
    return str(record.get("provider_prompt") or shot_cell_prompt(summary, slot_type)).strip()


def apply_shot_video_prompts(
    slot: WorkflowSlotV2,
    summary: str,
    *,
    detail_prompts: dict[str, Any] | None = None,
) -> None:
    details = detail_prompts or shot_detail_prompts(summary)
    slot.slot_prompt = video_prompt_from_details(details)
    slot.dialogue_prompt = str(details.get("dialogue") or "")
    slot.audio_description_prompt = str(details.get("audio_description") or "")
    slot.voice_style_prompt = str(details.get("voice_style") or "")
    slot.negative_constraints = str(details.get("video_negative_constraints") or "")
    slot.metadata["detail_prompt_keys"] = [
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
    ]
    slot.metadata["desired_duration_seconds"] = details.get("desired_duration_seconds")
    slot.metadata["provider_duration_seconds"] = details.get("provider_duration_seconds")
    slot.metadata["required_shot_cell_slot_ids"] = details.get("required_shot_cell_slot_ids", [])
    slot.metadata["required_shot_cell_asset_ids"] = details.get("required_shot_cell_asset_ids", [])
    cell_records, _warnings = storyboard_cell_prompt_records(
        shot_id=slot.item_id,
        summary_prompt=summary,
        detail_prompts=details,
        reference_item_ids=[
            str(item_id)
            for item_id in details.get("reference_item_ids", [])
            if str(item_id).strip()
        ],
    )
    slot.metadata["cell_prompts"] = cell_records
    slot.metadata["storyboard_detail_materializer_mode"] = details.get("materializer_mode")
    slot.metadata["storyboard_detail_materializer_version"] = details.get("materializer_version")
    slot.provider_params["duration_seconds"] = int(details.get("provider_duration_seconds") or 5)


def _cell_prompt_record_for_shot(shot: WorkflowItemV2, slot_type: str) -> dict[str, Any]:
    summary = shot.summary_prompt or shot.shot_summary_prompt or shot.item_prompt or ""
    records = shot.cell_prompts
    if not records:
        shot.detail_prompts, records, _warnings = enrich_detail_prompts_with_cell_records(
            shot_id=shot.shot_id or shot.item_id,
            summary_prompt=summary,
            detail_prompts=shot.detail_prompts,
            reference_item_ids=shot.reference_item_ids,
        )
        shot.cell_prompts = records
    for record in records:
        if record.get("slot_type") == slot_type:
            return dict(record)
    return cell_prompt_record_for_slot(
        shot_id=shot.shot_id or shot.item_id,
        summary_prompt=summary,
        detail_prompts=shot.detail_prompts,
        slot_type=slot_type,
        reference_item_ids=shot.reference_item_ids,
    )


def _slot_cell_prompt_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": record.get("cell_id"),
        "sequence_index": record.get("sequence_index"),
        "sequence_role": record.get("sequence_role"),
        "summary_prompt": record.get("summary_prompt"),
        "provider_prompt": record.get("provider_prompt"),
        "reference_item_ids": list(record.get("reference_item_ids") or []),
        "required_reference_asset_ids": list(record.get("required_reference_asset_ids") or []),
    }


def video_prompt_from_details(details: dict[str, Any]) -> str:
    cell_lines = _video_cell_prompt_lines(details)
    parts = [
        str(details.get("video_provider_prompt") or "").strip(),
        str(details.get("storyboard_content") or "").strip(),
        "\n".join(cell_lines),
        f"Dialogue: {details.get('dialogue')}" if details.get("dialogue") else "",
        f"Audio direction: {details.get('audio_description')}"
        if details.get("audio_description")
        else "",
        f"Voice style: {details.get('voice_style')}" if details.get("voice_style") else "",
        f"Negative constraints: {details.get('video_negative_constraints')}"
        if details.get("video_negative_constraints")
        else "",
    ]
    return "\n".join(part for part in parts if part).strip()


def _video_cell_prompt_lines(details: dict[str, Any]) -> list[str]:
    records, _warnings = storyboard_cell_prompt_records(
        shot_id=str(details.get("shot_id") or "shot"),
        summary_prompt=str(
            details.get("shot_summary_prompt") or details.get("summary_prompt") or ""
        ),
        detail_prompts=details,
        reference_item_ids=[
            str(item_id)
            for item_id in details.get("reference_item_ids", [])
            if str(item_id).strip()
        ],
    )
    return [
        (
            f"Cell {record['sequence_index']} ({record['sequence_role']}): "
            f"{record['provider_prompt']}"
        )
        for record in records
    ]


def normalize_provider_duration(desired_duration_seconds: int) -> int:
    desired = max(1, int(desired_duration_seconds))
    return min(SUPPORTED_SHOT_VIDEO_DURATIONS, key=lambda value: abs(value - desired))


def _script_plan_shots(workflow: WorkflowV2) -> list[dict[str, Any]]:
    script_plan = workflow.metadata.get("script_plan")
    if isinstance(script_plan, dict) and isinstance(script_plan.get("shots"), list):
        return [shot for shot in script_plan["shots"] if isinstance(shot, dict)]
    duration = normalize_provider_duration(
        max(1, round(workflow.duration_seconds / DEFAULT_STORYBOARD_SHOT_COUNT))
    )
    return [
        {
            "shot_id": f"shot-{index}",
            "shot_index": index,
            "description": f"Fallback storyboard beat {index}.",
            "visual_prompt": (
                f"Fallback storyboard beat {index} for {_storyboard_fallback_context(workflow)}"
            ),
            "duration_seconds": duration,
        }
        for index in range(1, DEFAULT_STORYBOARD_SHOT_COUNT + 1)
    ]


def _target_shot_count(workflow: WorkflowV2, fallback_count: int) -> int:
    constraints = workflow.metadata.get("planning_constraints")
    if isinstance(constraints, dict):
        requested = constraints.get("requested_shot_count")
        if isinstance(requested, int) and requested > 0:
            return requested
    storyboard_config = workflow.metadata.get("storyboard_config")
    if isinstance(storyboard_config, dict):
        applied = storyboard_config.get("applied_shot_count")
        if isinstance(applied, int) and applied > 0:
            return applied
    return max(1, fallback_count)


def _shots_for_target_count(
    workflow: WorkflowV2,
    script_shots: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    if target_count <= 0:
        return []
    source = list(script_shots)
    if not source:
        duration = normalize_provider_duration(
            max(1, round(workflow.duration_seconds / target_count))
        )
        source = [
            {
                "shot_id": "shot-1",
                "shot_index": 1,
                "description": "Fallback storyboard beat 1.",
                "visual_prompt": (
                    f"Fallback storyboard beat 1 for {_storyboard_fallback_context(workflow)}"
                ),
                "duration_seconds": duration,
            }
        ]
    result: list[dict[str, Any]] = []
    duration = max(1, round(workflow.duration_seconds / target_count))
    for index in range(1, target_count + 1):
        template = source[index - 1] if index <= len(source) else source[-1]
        shot = dict(template)
        shot["shot_id"] = (
            str(template.get("shot_id") or f"shot-{index}")
            if index <= len(source)
            else f"shot-{index}"
        )
        shot["shot_index"] = index
        shot.setdefault("scene_id", template.get("scene_id") or "scene-1")
        if index > len(source):
            summary = str(
                template.get("visual_prompt")
                or template.get("description")
                or f"Storyboard beat {index}."
            )
            shot["description"] = f"Continuation storyboard beat {index}: {summary}"
            shot["visual_prompt"] = f"Shot {index}: {summary}"
        shot["duration_seconds"] = int(shot.get("duration_seconds") or duration)
        result.append(shot)
    return result


def _storyboard_fallback_context(workflow: WorkflowV2) -> str:
    if workflow.metadata.get("selected_script_version_id"):
        script_plan = workflow.metadata.get("script_plan")
        if isinstance(script_plan, dict) and script_plan.get("script_title"):
            return str(script_plan["script_title"])
        return workflow.name
    return workflow.prompt


def _shot_summary(script_shot: dict[str, Any], fallback_prompt: str) -> str:
    for key in ("visual_prompt", "description"):
        value = script_shot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback_prompt


def _summary_source(script_shot: dict[str, Any]) -> str:
    if isinstance(script_shot.get("visual_prompt"), str) and script_shot["visual_prompt"].strip():
        return "script_plan.shots.visual_prompt"
    if isinstance(script_shot.get("description"), str) and script_shot["description"].strip():
        return "script_plan.shots.description"
    return "fallback"


def _detail_prompt_sources() -> dict[str, str]:
    return {
        "storyboard_content": "storyboard_detail_materializer",
        "dialogue": "script_plan.shots.narration",
        "audio_description": "storyboard_detail_materializer",
        "voice_style": "storyboard_detail_materializer",
        "video_negative_constraints": "storyboard_detail_materializer",
    }


def _reference_item_ids(script_shot: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("product_ids", "character_ids", "scene_ids", "reference_item_ids"):
        references = script_shot.get(key)
        if isinstance(references, list):
            values.extend(str(item_id).strip() for item_id in references if str(item_id).strip())
    scene_id = str(script_shot.get("scene_id") or "").strip()
    if scene_id:
        values.append(scene_id)
    return list(dict.fromkeys(values))


def _brief_summaries(
    workflow: WorkflowV2 | None,
    node_id: str,
    reference_item_ids: list[str],
) -> list[dict[str, Any]]:
    if workflow is None:
        return []
    node = next((node for node in workflow.nodes if node.node_id == node_id), None)
    if node is None:
        return []
    summaries: list[dict[str, Any]] = []
    allowed = set(reference_item_ids)
    for item in node.items:
        if item.lifecycle_state != "active" or item.item_id not in allowed:
            continue
        summaries.append(
            {
                "item_id": item.item_id,
                "display_name": item.display_name,
                "description": item.description,
                "summary": item.item_prompt or item.description or item.display_name,
            }
        )
    return summaries


def _selected_reference_summaries(
    workflow: WorkflowV2 | None,
    reference_item_ids: list[str],
) -> list[dict[str, Any]]:
    if workflow is None:
        return []
    summaries: list[dict[str, Any]] = []
    allowed = set(reference_item_ids)
    for node in workflow.nodes:
        if node.node_id not in {"product-generation", "character-generation", "scene-generation"}:
            continue
        for item in node.items:
            if item.item_id not in allowed:
                continue
            for slot in item.slots:
                if not slot.selected_asset_id:
                    continue
                summaries.append(
                    {
                        "asset_id": slot.selected_asset_id,
                        "version_id": slot.selected_version_id or slot.current_working_version_id,
                        "owner_item_id": item.item_id,
                        "owner_display_name": item.display_name,
                        "source_slot_id": slot.slot_id,
                        "slot_type": slot.slot_type,
                        "media_type": slot.media_type,
                        "semantic_type": slot.metadata.get("semantic_type"),
                        "display_name": item.display_name,
                        "tags": [],
                    }
                )
    return summaries


def _previous_continuity_context(
    workflow: WorkflowV2 | None,
    shot_index: int,
) -> dict[str, str | None]:
    empty = {
        "previous_transition_summary": None,
        "previous_product_state": None,
        "previous_story_state": None,
    }
    if workflow is None or shot_index <= 1:
        return empty
    shots = _script_plan_shots(workflow)
    previous = next(
        (
            shot
            for fallback_index, shot in enumerate(shots, start=1)
            if int(shot.get("shot_index") or fallback_index) == shot_index - 1
        ),
        None,
    )
    if previous is None:
        return empty
    previous_id = str(previous.get("shot_id") or f"shot-{shot_index - 1}").strip()
    description = _compact_continuity_text(
        str(previous.get("description") or "The previous story beat is complete.")
    )
    raw_product_ids = previous.get("product_ids")
    product_ids = (
        [str(item_id).strip() for item_id in raw_product_ids if str(item_id).strip()]
        if isinstance(raw_product_ids, list)
        else []
    )
    product_state = (
        f"Previous product references remain consistent: {', '.join(product_ids)}."
        if product_ids
        else "Preserve any product identity established in the previous beat."
    )
    return {
        "previous_transition_summary": _compact_continuity_text(
            f"{previous_id} closes with {description}"
        ),
        "previous_product_state": _compact_continuity_text(product_state),
        "previous_story_state": _compact_continuity_text(
            f"Continue the ordered story after {previous_id} without copying its prompts or assets."
        ),
    }


def _compact_continuity_text(value: str, *, limit: int = 320) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
