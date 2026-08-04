from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.schemas.workflow_v2 import (
    V2ProviderTask,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2RuntimeSnapshot,
)
from app.schemas.workflow_v2_production_acceptance import (
    V2ProductionAcceptanceCheck,
    V2ProductionAcceptanceFailure,
    V2ProductionAcceptanceFixture,
    V2ProductionAcceptanceMediaProbe,
    V2ProductionAcceptanceReport,
    V2ProductionAcceptanceReviewEntry,
)
from app.services.agent_trace import utc_now
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import (
    V2DataBoundaryError,
    validate_v2_data_path,
    validate_v2_relative_path,
)
from app.services.v2_final_composition_renderer import V2MediaProbe, V2MediaProbeResult


PRODUCTION_ACCEPTANCE_FAILURE_CODES = {
    "acceptance_orchestrator_interrupted",
    "acceptance_workflow_planning_failed",
    "acceptance_planning_clarification_required",
    "acceptance_explicit_count_mismatch",
    "acceptance_missing_required_node",
    "acceptance_missing_required_item",
    "acceptance_missing_required_slot",
    "acceptance_prompt_contract_failed",
    "acceptance_execution_start_failed",
    "acceptance_execution_failed",
    "acceptance_execution_partial_failed",
    "acceptance_execution_orphaned",
    "acceptance_provider_task_failed",
    "acceptance_required_slot_unselected",
    "acceptance_asset_record_missing",
    "acceptance_asset_file_missing",
    "acceptance_asset_unreadable",
    "acceptance_media_contract_mismatch",
    "acceptance_reference_missing",
    "acceptance_reference_not_submitted",
    "acceptance_reference_payload_unsafe",
    "acceptance_final_video_missing",
    "acceptance_final_video_unplayable",
    "acceptance_final_audio_missing",
    "acceptance_final_duration_mismatch",
}

_SENSITIVE_KEY_TERMS = (
    "authorization",
    "token",
    "secret",
    "password",
    "cookie",
    "credential",
    "signature",
    "api_key",
    "apikey",
    "raw_bytes",
)
_SIGNED_QUERY_TERMS = (
    "signature",
    "credential",
    "token",
    "key",
    "expires",
    "policy",
)
_GROUP_ORDER = {
    "product": 0,
    "character": 1,
    "scene": 2,
    "storyboard": 3,
    "bgm": 4,
    "final_composition": 5,
}


MediaProbe = Callable[[Path, str], V2MediaProbeResult | dict[str, Any]]


class V2ProductionAcceptanceValidator:
    def __init__(
        self,
        *,
        data_dir: Path,
        media_probe: MediaProbe | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._assets = V2AssetStoreService(data_dir)
        self._probe = media_probe or V2MediaProbe()

    def validate(
        self,
        *,
        acceptance_run_id: str,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
        execution_state: dict[str, Any],
        runtime: WorkflowV2RuntimeSnapshot | dict[str, Any],
        provider_tasks: list[V2ProviderTask | dict[str, Any]],
        capability_snapshot: dict[str, Any],
        events: list[Any] | None = None,
    ) -> V2ProductionAcceptanceReport:
        failures: list[V2ProductionAcceptanceFailure] = []
        warnings: list[str] = []
        probes: dict[str, V2ProductionAcceptanceMediaProbe] = {}
        records: dict[str, WorkflowAssetVersionV2] = {}
        required_slots = self._required_slots(fixture, workflow, failures)

        for item, slot in required_slots:
            record = self._selected_record(item, slot, failures)
            if record is None:
                continue
            records[slot.slot_id] = record
            probe = self._validate_asset(
                fixture,
                workflow,
                item,
                slot,
                record,
                failures,
                warnings,
            )
            if probe is not None:
                probes[slot.slot_id] = probe

        self._validate_references(workflow, required_slots, records, failures)
        provider_summaries = self._validate_provider_tasks(
            execution_state,
            provider_tasks,
            failures,
            warnings,
        )
        self._validate_execution(execution_state, runtime, provider_tasks, failures)
        self._validate_final_output(
            fixture,
            workflow,
            records,
            probes,
            failures,
            warnings,
        )

        failures = _dedupe_failures(failures)
        technical_verdict = "failed" if failures else "passed"
        lifecycle_status = "failed" if failures else "completed"
        checks = _checks_from_failures(failures, warnings)
        manifest = self._review_manifest(workflow, required_slots, records, probes)
        return V2ProductionAcceptanceReport(
            acceptance_run_id=acceptance_run_id,
            fixture_id=fixture.fixture_id,
            workflow_id=workflow.workflow_id,
            execution_id=_text(execution_state.get("execution_id")),
            lifecycle_status=lifecycle_status,
            technical_verdict=technical_verdict,
            manual_review_required=not failures,
            fixture_snapshot=sanitize_production_acceptance_evidence(
                fixture.model_dump(mode="json"),
                data_dir=self._data_dir,
            ),
            capability_snapshot=sanitize_production_acceptance_evidence(
                capability_snapshot,
                data_dir=self._data_dir,
            ),
            checks=checks,
            failures=failures,
            warnings=list(dict.fromkeys(warnings)),
            metrics={
                "required_slot_count": len(required_slots),
                "selected_asset_count": len(records),
                "provider_task_count": len(provider_tasks),
                "runtime_event_count": len(events or []),
            },
            provider_task_summaries=provider_summaries,
            review_manifest=manifest,
            created_at=utc_now().isoformat(),
        )

    def _required_slots(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
        failures: list[V2ProductionAcceptanceFailure],
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2]]:
        nodes = {node.node_id: node for node in workflow.nodes}
        for node_id in fixture.required_nodes:
            if node_id not in nodes:
                failures.append(
                    _failure(
                        "acceptance_missing_required_node",
                        "terminal_structure",
                        f"Required node is missing: {node_id}.",
                        node_id=node_id,
                    )
                )
        required: list[tuple[WorkflowItemV2, WorkflowSlotV2]] = []
        item_counts = {item_type: 0 for item_type in fixture.required_slot_types}
        for node in workflow.nodes:
            for item in node.items:
                expected_types = fixture.required_slot_types.get(item.item_type, [])
                if not expected_types:
                    continue
                item_counts[item.item_type] = item_counts.get(item.item_type, 0) + 1
                slots = {slot.slot_type: slot for slot in item.slots}
                for slot_type in expected_types:
                    slot = slots.get(slot_type)
                    if slot is None:
                        failures.append(
                            _failure(
                                "acceptance_missing_required_slot",
                                "terminal_structure",
                                f"Required slot is missing: {slot_type}.",
                                node_id=item.node_id,
                                item_id=item.item_id,
                                slot_id=f"{item.item_id}:{slot_type}",
                            )
                        )
                        continue
                    required.append((item, slot))
        for item_type, count in item_counts.items():
            if count == 0:
                failures.append(
                    _failure(
                        "acceptance_missing_required_item",
                        "terminal_structure",
                        f"Required item family is missing: {item_type}.",
                    )
                )
        return required

    def _selected_record(
        self,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        failures: list[V2ProductionAcceptanceFailure],
    ) -> WorkflowAssetVersionV2 | None:
        if not slot.selected_asset_id or not slot.selected_version_id:
            failures.append(
                _failure(
                    "acceptance_required_slot_unselected",
                    "selected_assets",
                    "Required slot has no selected canonical asset version.",
                    node_id=item.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    asset_id=slot.selected_asset_id,
                    version_id=slot.selected_version_id,
                )
            )
            return None
        record = self._assets.load_asset_version(
            slot.selected_asset_id,
            slot.selected_version_id,
        )
        if record is None:
            failures.append(
                _failure(
                    "acceptance_asset_record_missing",
                    "selected_assets",
                    "Selected canonical asset metadata is missing.",
                    node_id=item.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    asset_id=slot.selected_asset_id,
                    version_id=slot.selected_version_id,
                )
            )
        return record

    def _validate_asset(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
        failures: list[V2ProductionAcceptanceFailure],
        warnings: list[str],
    ) -> V2ProductionAcceptanceMediaProbe | None:
        try:
            relative = validate_v2_relative_path(
                record.file_path,
                operation="v2-production-acceptance-asset",
            )
            if not relative.parts or relative.parts[0] != "assets":
                raise ValueError("Canonical asset path is outside assets storage.")
            path = validate_v2_data_path(
                self._data_dir,
                self._data_dir / relative,
                operation="v2-production-acceptance-asset",
            )
        except (ValueError, V2DataBoundaryError):
            failures.append(
                _asset_failure(
                    "acceptance_asset_file_missing",
                    "Canonical asset path is outside the V2 asset boundary.",
                    item,
                    slot,
                    record,
                )
            )
            return None
        if not path.is_file() or path.stat().st_size <= 0:
            failures.append(
                _asset_failure(
                    "acceptance_asset_file_missing",
                    "Canonical asset file is missing or empty.",
                    item,
                    slot,
                    record,
                )
            )
            return None
        if record.media_type != slot.media_type:
            failures.append(
                _asset_failure(
                    "acceptance_media_contract_mismatch",
                    "Selected asset media type does not match the slot contract.",
                    item,
                    slot,
                    record,
                    evidence={
                        "expected_media_type": slot.media_type,
                        "actual_media_type": record.media_type,
                    },
                )
            )
        raw_probe = V2MediaProbeResult.from_payload(
            self._probe(path, record.media_type),
            path=path,
            media_type=record.media_type,
        )
        probe = V2ProductionAcceptanceMediaProbe(
            media_type=record.media_type,
            readable=raw_probe.error is None,
            size_bytes=path.stat().st_size,
            width=raw_probe.width,
            height=raw_probe.height,
            duration_seconds=raw_probe.duration_seconds,
            fps=raw_probe.fps,
            video_codec=raw_probe.video_codec,
            audio_codec=raw_probe.audio_codec,
            has_video=bool(raw_probe.video_codec or raw_probe.width or raw_probe.height),
            has_audio=raw_probe.has_audio,
            error=raw_probe.error,
        )
        if not probe.readable:
            failures.append(
                _asset_failure(
                    "acceptance_asset_unreadable",
                    "Canonical asset could not be probed.",
                    item,
                    slot,
                    record,
                    evidence={"probe_error": probe.error},
                )
            )
            return probe
        if slot.media_type == "video" and not probe.has_video:
            failures.append(
                _asset_failure(
                    "acceptance_media_contract_mismatch",
                    "Video slot does not contain a video stream.",
                    item,
                    slot,
                    record,
                )
            )
        if slot.media_type == "audio" and not probe.has_audio:
            failures.append(
                _asset_failure(
                    "acceptance_media_contract_mismatch",
                    "Audio slot does not contain an audio stream.",
                    item,
                    slot,
                    record,
                )
            )
        expected_ratio = _expected_ratio(slot, workflow)
        if expected_ratio and probe.width and probe.height:
            actual_ratio = probe.width / probe.height
            if abs(actual_ratio - expected_ratio) / expected_ratio > 0.03:
                failures.append(
                    _asset_failure(
                        "acceptance_media_contract_mismatch",
                        "Asset aspect ratio exceeds the allowed tolerance.",
                        item,
                        slot,
                        record,
                        evidence={
                            "expected_ratio": expected_ratio,
                            "actual_ratio": actual_ratio,
                            "width": probe.width,
                            "height": probe.height,
                        },
                    )
                )
        if slot.slot_type == "shot_video_segment":
            expected_duration = float(item.duration_seconds or fixture.request.duration_seconds)
            if not _duration_within(
                probe.duration_seconds,
                expected_duration,
                max(1.0, expected_duration * 0.20),
            ):
                failures.append(
                    _asset_failure(
                        "acceptance_media_contract_mismatch",
                        "Shot video duration exceeds the allowed tolerance.",
                        item,
                        slot,
                        record,
                        evidence={
                            "expected_duration_seconds": expected_duration,
                            "actual_duration_seconds": probe.duration_seconds,
                        },
                    )
                )
        return probe

    def _validate_references(
        self,
        workflow: WorkflowV2,
        required_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
        records: dict[str, WorkflowAssetVersionV2],
        failures: list[V2ProductionAcceptanceFailure],
    ) -> None:
        slot_by_id = {slot.slot_id: slot for _item, slot in required_slots}
        selected_main = {
            item.item_type: slot.selected_asset_id
            for item, slot in required_slots
            if slot.slot_type in {"product_main_image", "character_main_image", "scene_main_image"}
            and slot.selected_asset_id
        }
        for item, slot in required_slots:
            record = records.get(slot.slot_id)
            if record is None:
                continue
            expected: list[str] = []
            if slot.slot_type in {
                "product_multi_view_grid",
                "character_three_view",
                "scene_multi_view_grid",
            }:
                main_type = {
                    "product_multi_view_grid": "product_main_image",
                    "character_three_view": "character_main_image",
                    "scene_multi_view_grid": "scene_main_image",
                }[slot.slot_type]
                main_slot = next(
                    (candidate for candidate in item.slots if candidate.slot_type == main_type),
                    None,
                )
                if main_slot and main_slot.selected_asset_id:
                    expected = [main_slot.selected_asset_id]
            elif slot.slot_type.startswith("shot_cell_"):
                expected = [
                    asset_id
                    for key in ("product", "character", "scene")
                    if (asset_id := selected_main.get(key))
                ]
            elif slot.slot_type == "shot_video_segment":
                expected = [
                    candidate.selected_asset_id
                    for candidate in item.slots
                    if candidate.slot_type.startswith("shot_cell_") and candidate.selected_asset_id
                ]
            elif slot.slot_type == "final_video":
                expected = [
                    candidate.selected_asset_id
                    for candidate in slot_by_id.values()
                    if candidate.slot_type in {"shot_video_segment", "bgm_audio"}
                    and candidate.selected_asset_id
                ]
            if expected:
                self._require_reference_evidence(item, slot, record, expected, failures)
            if _contains_unsafe_reference_payload(record.provider_payload_snapshot):
                failures.append(
                    _asset_failure(
                        "acceptance_reference_payload_unsafe",
                        "Provider reference evidence contains unsafe payload data.",
                        item,
                        slot,
                        record,
                    )
                )

    def _require_reference_evidence(
        self,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        record: WorkflowAssetVersionV2,
        expected: list[str],
        failures: list[V2ProductionAcceptanceFailure],
    ) -> None:
        requested = _string_list(
            record.provider_payload_snapshot.get("requested_reference_asset_ids")
        ) or list(record.reference_asset_ids)
        submitted = _string_list(
            record.provider_payload_snapshot.get("submitted_reference_asset_ids")
        )
        missing = sorted(set(expected) - set(requested))
        not_submitted = sorted(set(expected) - set(submitted))
        if missing:
            failures.append(
                _asset_failure(
                    "acceptance_reference_missing",
                    "Required selected references were not requested.",
                    item,
                    slot,
                    record,
                    evidence={"missing_reference_asset_ids": missing},
                )
            )
        if not_submitted:
            failures.append(
                _asset_failure(
                    "acceptance_reference_not_submitted",
                    "Required selected references were not submitted to the provider.",
                    item,
                    slot,
                    record,
                    evidence={"not_submitted_reference_asset_ids": not_submitted},
                )
            )

    def _validate_provider_tasks(
        self,
        execution_state: dict[str, Any],
        provider_tasks: list[V2ProviderTask | dict[str, Any]],
        failures: list[V2ProductionAcceptanceFailure],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for task in provider_tasks:
            payload = _payload(task)
            summary = {
                key: payload.get(key)
                for key in (
                    "task_id",
                    "node_id",
                    "item_id",
                    "slot_id",
                    "provider",
                    "provider_model",
                    "remote_task_id",
                    "status",
                    "attempt_count",
                    "poll_count",
                    "last_error_code",
                    "submitted_at",
                    "completed_at",
                )
            }
            summaries.append(
                sanitize_production_acceptance_evidence(summary, data_dir=self._data_dir)
            )
            if str(payload.get("status") or "") == "failed":
                failures.append(
                    _failure(
                        "acceptance_provider_task_failed",
                        "provider_tasks",
                        "Required provider task failed.",
                        node_id=_text(payload.get("node_id")),
                        item_id=_text(payload.get("item_id")),
                        slot_id=_text(payload.get("slot_id")),
                        provider_task_id=_text(payload.get("task_id")),
                        source_error_code=_text(payload.get("last_error_code")),
                        evidence={
                            "provider": payload.get("provider"),
                            "provider_model": payload.get("provider_model"),
                            "attempt_count": payload.get("attempt_count", 0),
                            "poll_count": payload.get("poll_count", 0),
                        },
                    )
                )
            if int(payload.get("attempt_count") or 0) > 1:
                warnings.append(
                    f"Provider task {payload.get('task_id')} succeeded or progressed after retries."
                )
        return summaries

    def _validate_execution(
        self,
        execution_state: dict[str, Any],
        runtime: WorkflowV2RuntimeSnapshot | dict[str, Any],
        provider_tasks: list[V2ProviderTask | dict[str, Any]],
        failures: list[V2ProductionAcceptanceFailure],
    ) -> None:
        status = str(execution_state.get("status") or "")
        if status == "partial_failed":
            failures.append(
                _failure(
                    "acceptance_execution_partial_failed",
                    "execution",
                    "Workflow execution partially failed.",
                )
            )
        elif status in {"failed", "cancelled"}:
            failures.append(
                _failure(
                    "acceptance_execution_failed",
                    "execution",
                    f"Workflow execution ended with status {status}.",
                    source_error_code=status,
                )
            )
        runtime_payload = _payload(runtime)
        active_runtime = any(
            runtime_payload.get(field)
            for field in ("running_slot_ids", "waiting_slot_ids", "blocked_slot_ids")
        )
        active_tasks = any(
            str(_payload(task).get("status") or "")
            in {"submitted", "waiting", "polling", "running"}
            for task in provider_tasks
        )
        if status == "completed" and (active_runtime or active_tasks):
            failures.append(
                _failure(
                    "acceptance_execution_orphaned",
                    "execution",
                    "Completed execution still has active required work.",
                    evidence={
                        "active_runtime": active_runtime,
                        "active_provider_tasks": active_tasks,
                    },
                )
            )

    def _validate_final_output(
        self,
        fixture: V2ProductionAcceptanceFixture,
        workflow: WorkflowV2,
        records: dict[str, WorkflowAssetVersionV2],
        probes: dict[str, V2ProductionAcceptanceMediaProbe],
        failures: list[V2ProductionAcceptanceFailure],
        warnings: list[str],
    ) -> None:
        final_slot = next(
            (
                slot
                for node in workflow.nodes
                for item in node.items
                for slot in item.slots
                if slot.slot_type == "final_video"
            ),
            None,
        )
        if final_slot is None or final_slot.slot_id not in records:
            failures.append(
                _failure(
                    "acceptance_final_video_missing",
                    "final_composition",
                    "Selected final video is missing.",
                    slot_id=final_slot.slot_id if final_slot else None,
                )
            )
            return
        record = records[final_slot.slot_id]
        probe = probes.get(final_slot.slot_id)
        if probe is None or not probe.readable or not probe.has_video:
            failures.append(
                _failure(
                    "acceptance_final_video_unplayable",
                    "final_composition",
                    "Final video is not playable.",
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    slot_id=final_slot.slot_id,
                )
            )
            return
        if fixture.request.audio_mode == "bgm_only" and not probe.has_audio:
            failures.append(
                _failure(
                    "acceptance_final_audio_missing",
                    "final_composition",
                    "Final video does not contain the required audio stream.",
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    slot_id=final_slot.slot_id,
                )
            )
        expected = float(fixture.request.duration_seconds)
        if not _duration_within(
            probe.duration_seconds,
            expected,
            max(1.0, expected * 0.20),
        ):
            failures.append(
                _failure(
                    "acceptance_final_duration_mismatch",
                    "final_composition",
                    "Final video duration exceeds the fixture tolerance.",
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    slot_id=final_slot.slot_id,
                    evidence={
                        "expected_duration_seconds": expected,
                        "actual_duration_seconds": probe.duration_seconds,
                    },
                )
            )
        elif probe.duration_seconds and probe.duration_seconds != expected:
            warnings.append("Final video duration differs slightly from the fixture request.")

    def _review_manifest(
        self,
        workflow: WorkflowV2,
        required_slots: list[tuple[WorkflowItemV2, WorkflowSlotV2]],
        records: dict[str, WorkflowAssetVersionV2],
        probes: dict[str, V2ProductionAcceptanceMediaProbe],
    ) -> list[V2ProductionAcceptanceReviewEntry]:
        rows: list[tuple[tuple[int, int, int], WorkflowItemV2, WorkflowSlotV2]] = []
        for item, slot in required_slots:
            group = _manifest_group(item)
            shot_order = item.shot_index or 0
            slot_order = _slot_order(slot)
            rows.append(((_GROUP_ORDER[group], shot_order, slot_order), item, slot))
        entries: list[V2ProductionAcceptanceReviewEntry] = []
        for _sort_key, item, slot in sorted(rows, key=lambda row: row[0]):
            record = records.get(slot.slot_id)
            probe = probes.get(slot.slot_id)
            if record is None or probe is None:
                continue
            payload = sanitize_production_acceptance_evidence(
                record.provider_payload_snapshot,
                data_dir=self._data_dir,
            )
            public_url = record.public_url if _safe_public_url(record.public_url) else None
            entries.append(
                V2ProductionAcceptanceReviewEntry(
                    order=len(entries) + 1,
                    group=_manifest_group(item),
                    node_id=item.node_id,
                    item_id=item.item_id,
                    slot_id=slot.slot_id,
                    slot_type=slot.slot_type,
                    asset_id=record.asset_id,
                    version_id=record.version_id,
                    public_url=public_url,
                    summary_prompt=_optional_text(record.prompt_snapshot.get("summary_prompt")),
                    specialist_prompt=_optional_text(item.item_prompt),
                    provider_prompt=_optional_text(
                        payload.get("actual_provider_request_prompt")
                        or payload.get("provider_prompt")
                    ),
                    reference_asset_ids=_string_list(payload.get("submitted_reference_asset_ids")),
                    provider=_optional_text(
                        payload.get("provider") or record.metadata.get("provider")
                    ),
                    provider_model=_optional_text(
                        payload.get("provider_model") or record.metadata.get("provider_model")
                    ),
                    probe=probe,
                )
            )
        return entries


def sanitize_production_acceptance_evidence(
    value: Any,
    *,
    data_dir: Path,
) -> Any:
    if isinstance(value, bytes):
        return "[redacted]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(term in normalized for term in _SENSITIVE_KEY_TERMS):
                result[str(key)] = "[redacted]"
                continue
            result[str(key)] = sanitize_production_acceptance_evidence(
                item,
                data_dir=data_dir,
            )
        return result
    if isinstance(value, (list, tuple, set)):
        return [sanitize_production_acceptance_evidence(item, data_dir=data_dir) for item in value]
    if isinstance(value, Path):
        value = value.as_posix()
    if isinstance(value, str):
        if value.lower().startswith("data:") or "base64," in value.lower():
            return "[redacted]"
        if _absolute_host_path(value, data_dir):
            return "[redacted]"
        if value.startswith(("http://", "https://")):
            return _sanitize_url(value)
    return value


def _failure(
    code: str,
    stage: str,
    message: str,
    *,
    source_error_code: str | None = None,
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
    asset_id: str | None = None,
    version_id: str | None = None,
    provider_task_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> V2ProductionAcceptanceFailure:
    return V2ProductionAcceptanceFailure(
        code=code,
        source_error_code=source_error_code,
        stage=stage,
        message=message,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        asset_id=asset_id,
        version_id=version_id,
        provider_task_id=provider_task_id,
        evidence=evidence or {},
    )


def _asset_failure(
    code: str,
    message: str,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    record: WorkflowAssetVersionV2,
    *,
    evidence: dict[str, Any] | None = None,
) -> V2ProductionAcceptanceFailure:
    return _failure(
        code,
        "media_validation",
        message,
        node_id=item.node_id,
        item_id=item.item_id,
        slot_id=slot.slot_id,
        asset_id=record.asset_id,
        version_id=record.version_id,
        evidence=evidence,
    )


def _expected_ratio(slot: WorkflowSlotV2, workflow: WorkflowV2) -> float | None:
    raw = (
        slot.provider_params.get("aspect_ratio")
        or slot.metadata.get("aspect_ratio")
        or (
            workflow.aspect_ratio
            if slot.slot_type.startswith("shot_cell_")
            or slot.slot_type in {"shot_video_segment", "final_video"}
            else None
        )
    )
    if not isinstance(raw, str) or ":" not in raw:
        return None
    left, right = raw.split(":", 1)
    try:
        denominator = float(right)
        return float(left) / denominator if denominator else None
    except ValueError:
        return None


def _duration_within(actual: float | None, expected: float, tolerance: float) -> bool:
    return bool(actual and actual > 0 and abs(actual - expected) <= tolerance)


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_text(value: Any) -> str | None:
    return _text(value)


def _contains_unsafe_reference_payload(value: Any, *, key: str = "") -> bool:
    if isinstance(value, bytes):
        return True
    if isinstance(value, dict):
        return any(
            any(term in str(item_key).lower().replace("-", "_") for term in _SENSITIVE_KEY_TERMS)
            or _contains_unsafe_reference_payload(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unsafe_reference_payload(item, key=key) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith("data:") or "base64," in lowered or value.startswith("file://"):
            return True
        if key in {"path", "file_path", "local_path", "url"} and (
            value.startswith("/") or value.startswith(("assets/", "data/", "v2/"))
        ):
            return not value.startswith("/media/")
        if value.startswith(("http://", "https://")):
            query = urlsplit(value).query.lower()
            return any(term in query for term in _SIGNED_QUERY_TERMS)
    return False


def _manifest_group(item: WorkflowItemV2) -> str:
    return "storyboard" if item.item_type == "shot" else item.item_type


def _slot_order(slot: WorkflowSlotV2) -> int:
    if slot.slot_type.startswith("shot_cell_"):
        try:
            return int(slot.slot_type.rsplit("_", 1)[1])
        except ValueError:
            return 50
    if slot.slot_type == "shot_video_segment":
        return 99
    return 0 if slot.slot_type.endswith("main_image") else 1


def _safe_public_url(value: str | None) -> bool:
    return bool(value and value.startswith("/media/") and ".." not in value)


def _absolute_host_path(value: str, data_dir: Path) -> bool:
    if value.startswith("/media/"):
        return False
    path = Path(value)
    return path.is_absolute() or str(data_dir.resolve()) in value


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    safe_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(term in key.lower() for term in _SIGNED_QUERY_TERMS)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), parsed.fragment)
    )


def _dedupe_failures(
    failures: list[V2ProductionAcceptanceFailure],
) -> list[V2ProductionAcceptanceFailure]:
    result: list[V2ProductionAcceptanceFailure] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for failure in failures:
        key = (failure.code, failure.node_id, failure.item_id, failure.slot_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(failure)
    return result


def _checks_from_failures(
    failures: list[V2ProductionAcceptanceFailure],
    warnings: list[str],
) -> list[V2ProductionAcceptanceCheck]:
    stages = [
        "terminal_structure",
        "selected_assets",
        "media_validation",
        "provider_tasks",
        "execution",
        "final_composition",
    ]
    checks = []
    for stage in stages:
        stage_failures = [failure for failure in failures if failure.stage == stage]
        checks.append(
            V2ProductionAcceptanceCheck(
                check_id=stage,
                stage=stage,
                status="failed" if stage_failures else "passed",
                message=(
                    f"{len(stage_failures)} technical failure(s) detected."
                    if stage_failures
                    else "Technical checks passed."
                ),
                evidence={"failure_codes": [failure.code for failure in stage_failures]},
            )
        )
    if warnings:
        checks.append(
            V2ProductionAcceptanceCheck(
                check_id="warnings",
                stage="warnings",
                status="warning",
                message=f"{len(warnings)} warning(s) recorded.",
            )
        )
    return checks
