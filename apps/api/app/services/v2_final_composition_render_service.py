from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
import subprocess
import threading
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2FinalCompositionFingerprint,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineRenderStateResponse,
)
from app.schemas.workflow_v2_composition import V2SimpleCompositionPlan
from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_final_composition_renderer import V2FinalCompositionRenderer
from app.services.v2_final_composition_fingerprint import (
    V2FinalCompositionFingerprintError,
    V2FinalCompositionFingerprintService,
)
from app.services.v2_final_composition_publication import (
    V2FinalCompositionPublicationService,
)
from app.services.v2_final_composition_orphan_reconciler import (
    V2FinalCompositionOrphanReconciler,
)
from app.services.v2_final_composition_timeline import (
    FINAL_NODE_ID,
    V2FinalCompositionTimelineError,
    V2FinalCompositionTimelineService,
)
from app.services.v2_media_toolchain_capabilities import (
    PROFILE_ID,
    V2MediaToolchainCapabilityError,
    V2MediaToolchainCapabilityService,
)
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_simple_composition_plan import (
    V2SimpleCompositionPlanError,
    V2SimpleCompositionPlanService,
)
from app.services.v2_workflow_lock import v2_workflow_lock


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_ACTIVE_STATUSES = {"queued", "running", "cancellation_requested"}
_REGISTRY_LOCK = threading.RLock()
_PROCESS_REGISTRY: dict[tuple[str, str], subprocess.Popen[str] | None] = {}
_LOGGER = logging.getLogger(__name__)


class V2FinalCompositionRenderService:
    """Durable, detached final-composition rendering over the canonical timeline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._events = V2RuntimeEventService(self._data_dir)
        self._timeline_service = V2FinalCompositionTimelineService(settings)
        self._simple_plan_service = V2SimpleCompositionPlanService(self._data_dir)
        self._fingerprints = V2FinalCompositionFingerprintService(
            self._data_dir,
            settings,
        )
        self._publication = V2FinalCompositionPublicationService(settings)
        self._orphans = V2FinalCompositionOrphanReconciler(
            self._data_dir,
            manifest_reconciler=self._timeline_service.reconcile_pending_publications,
        )

    def start_render(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineRenderRequest,
    ) -> WorkflowV2TimelineRenderStartResponse:
        workflow, item, slot, timeline, _source = (
            self._timeline_service.load_or_create_and_reconcile(workflow_id)
        )
        self.reconcile_final_composition_artifacts(workflow_id)
        if (
            request.timeline_id != timeline.timeline_id
            or request.timeline_version != timeline.version
        ):
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Render request does not match the saved timeline version.",
                status_code=409,
            )
        simple_plan: V2SimpleCompositionPlan | None = None
        render_mode = self._settings.final_composition_render_mode.strip().lower()
        if render_mode == "simple_sequence":
            settlement = self._simple_plan_service.inspect(workflow)
            if not settlement.settled:
                raise V2FinalCompositionTimelineError(
                    "composition_inputs_not_settled",
                    "Final Composition inputs have not settled.",
                    status_code=409,
                    details={"pending_slot_ids": settlement.pending_slot_ids},
                )
            try:
                simple_plan = self._simple_plan_service.build(workflow)
            except V2SimpleCompositionPlanError as exc:
                raise V2FinalCompositionTimelineError(
                    exc.code,
                    str(exc),
                    status_code=409,
                ) from exc
        if self._settings.media_mode.strip().lower() != "mock":
            try:
                V2MediaToolchainCapabilityService(self._settings).require_profile(
                    PROFILE_ID,
                    requires_subtitles=(
                        False
                        if render_mode == "simple_sequence"
                        else any(
                            clip.enabled and clip.clip_type == "subtitle" for clip in timeline.clips
                        )
                    ),
                )
            except V2MediaToolchainCapabilityError as exc:
                raise V2FinalCompositionTimelineError(
                    exc.code,
                    str(exc),
                    status_code=400,
                ) from exc
        try:
            fingerprint = self._fingerprints.build_for_composition(
                workflow_id=workflow_id,
                slot_id=slot.slot_id,
                timeline=timeline,
                render_settings=request.render_settings,
                render_mode=render_mode,
                audio_mode=workflow.audio_mode,
                simple_plan=simple_plan,
            )
        except V2FinalCompositionFingerprintError as exc:
            raise V2FinalCompositionTimelineError(
                "v2_final_composition_fingerprint_invalid",
                str(exc),
                status_code=500,
            ) from exc
        render_id = f"render_{uuid4().hex[:12]}"
        now = utc_now().isoformat()
        state = {
            "workflow_id": workflow_id,
            "render_id": render_id,
            "node_id": FINAL_NODE_ID,
            "item_id": item.item_id,
            "slot_id": slot.slot_id,
            "status": "queued",
            "timeline_id": timeline.timeline_id,
            "timeline_version": timeline.version,
            "progress_seconds": 0.0,
            "total_seconds": timeline.duration_seconds,
            "progress_percent": 0.0,
            "asset_id": None,
            "version_id": None,
            "error_code": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            "events_cursor": self._events.events_cursor(workflow_id),
            "request": request.model_dump(mode="json"),
            "composition_fingerprint": fingerprint.fingerprint,
            "fingerprint_contract_version": fingerprint.contract_version,
            "composition_fingerprint_payload": fingerprint.canonical_payload,
            "source_action": "editor_export",
            "select_result": True,
            "reused": False,
            "reused_from_render_id": None,
            "reuse_kind": None,
            "output_url": None,
            **self._simple_plan_state_metadata(simple_plan),
        }
        with v2_workflow_lock(self._data_dir, workflow_id):
            with _REGISTRY_LOCK:
                self._publication.reconcile_pending(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                )
                active = self._active_state(workflow_id)
                if active is not None:
                    if (
                        active.get("status") in {"queued", "running"}
                        and active.get("composition_fingerprint") == fingerprint.fingerprint
                    ):
                        reused_state = {
                            **active,
                            "reused": True,
                            "reused_from_render_id": active["render_id"],
                            "reuse_kind": "active_render",
                        }
                        self._append_render_event(
                            workflow_id,
                            "final_composition_render_reused",
                            reused_state,
                        )
                        return self._start_response(reused_state)
                    raise V2FinalCompositionTimelineError(
                        "v2_timeline_render_already_active",
                        f"Render already active: {active['render_id']}",
                        status_code=409,
                        details={
                            "active_render_id": active["render_id"],
                            "purpose": "final",
                        },
                    )
                reusable = self._publication.find_reusable(
                    workflow_id=workflow_id,
                    slot_id=slot.slot_id,
                    composition_fingerprint=fingerprint.fingerprint,
                )
                if reusable is not None:
                    workflow = self._timeline_service.select_published_result(
                        workflow=workflow,
                        item=item,
                        slot=slot,
                        record=reusable,
                        source_action="editor_export",
                    )
                    del workflow
                    reused_render_id = str(
                        reusable.metadata.get("source_render_id")
                        or f"render_{reusable.version_id.removeprefix('ver_comp_')[:12]}"
                    )
                    completed_state = {
                        **state,
                        "render_id": reused_render_id,
                        "status": "completed",
                        "asset_id": reusable.asset_id,
                        "version_id": reusable.version_id,
                        "output_url": reusable.public_url,
                        "reused": True,
                        "reused_from_render_id": reusable.metadata.get("source_render_id"),
                        "reuse_kind": "completed_asset",
                        "progress_seconds": state["total_seconds"],
                        "progress_percent": 100.0,
                    }
                    self._write_state(
                        workflow_id,
                        reused_render_id,
                        completed_state,
                    )
                    self._append_render_event(
                        workflow_id,
                        "final_composition_render_reused",
                        completed_state,
                    )
                    return self._start_response(completed_state)
                if simple_plan is not None:
                    self._write_simple_plan(workflow_id, render_id, simple_plan)
                self._write_state(workflow_id, render_id, state)
                _PROCESS_REGISTRY[(str(self._data_dir), workflow_id)] = None
        event = self._events.append_event(
            workflow_id,
            "final_composition_render_queued",
            node_id=FINAL_NODE_ID,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            payload=self._event_payload(state),
        )
        self._write_state(
            workflow_id,
            render_id,
            {**state, "events_cursor": event.seq, "updated_at": utc_now().isoformat()},
        )
        thread = threading.Thread(
            target=self._run_render,
            args=(workflow_id, render_id),
            name=f"v2-final-render-{render_id}",
            daemon=True,
        )
        thread.start()
        return self._start_response(
            {
                **state,
                "events_cursor": event.seq,
            }
        )

    def load_render_state(
        self,
        workflow_id: str,
        render_id: str,
    ) -> WorkflowV2TimelineRenderStateResponse:
        return WorkflowV2TimelineRenderStateResponse.model_validate(
            self._load_state(workflow_id, render_id)
        )

    def cancel_render(
        self,
        workflow_id: str,
        render_id: str,
    ) -> WorkflowV2TimelineRenderStateResponse:
        state = self._load_state(workflow_id, render_id)
        if state["status"] in _TERMINAL_STATUSES:
            return WorkflowV2TimelineRenderStateResponse.model_validate(state)
        key = (str(self._data_dir), workflow_id)
        with _REGISTRY_LOCK:
            process = _PROCESS_REGISTRY.get(key)
            if state["status"] == "queued" and process is None:
                return self._transition_cancelled(state)
            state = self._transition(state, "cancellation_requested")
            _PROCESS_REGISTRY[key] = process
        self._write_state(workflow_id, render_id, state)
        if process is not None and process.poll() is None:
            self._stop_process(process)
        return WorkflowV2TimelineRenderStateResponse.model_validate(state)

    def recover_interrupted_renders(self, workflow_id: str) -> list[str]:
        recovered: list[str] = []
        try:
            self._timeline_service.reconcile_pending_publications(workflow_id)
        except Exception:  # noqa: BLE001 - recovery cannot prevent backend startup.
            _LOGGER.exception(
                "Pending Final Composition publication recovery failed.",
                extra={"workflow_id": workflow_id},
            )
        for state_path in self._composition_dir(workflow_id).glob("render_*/state.json"):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            status = state.get("status")
            if status == "queued":
                key = (str(self._data_dir), workflow_id)
                with _REGISTRY_LOCK:
                    if key in _PROCESS_REGISTRY:
                        continue
                    _PROCESS_REGISTRY[key] = None
                thread = threading.Thread(
                    target=self._run_render,
                    args=(workflow_id, str(state["render_id"])),
                    name=f"v2-final-render-{state['render_id']}",
                    daemon=True,
                )
                thread.start()
                recovered.append(str(state["render_id"]))
            elif status in {"running", "cancellation_requested"}:
                with _REGISTRY_LOCK:
                    if (str(self._data_dir), workflow_id) in _PROCESS_REGISTRY:
                        continue
                failed = self._transition(
                    state,
                    "failed",
                    error_code="v2_timeline_render_interrupted",
                    error_message="Final composition render was interrupted before recovery.",
                )
                self._write_state(workflow_id, str(state["render_id"]), failed)
                self._append_render_event(workflow_id, "final_composition_render_failed", failed)
                recovered.append(str(state["render_id"]))
        self.reconcile_final_composition_artifacts(workflow_id)
        return recovered

    def reconcile_final_composition_artifacts(self, workflow_id: str) -> None:
        try:
            self._orphans.reconcile(workflow_id)
        except Exception:  # noqa: BLE001 - maintenance cannot fail render lifecycle.
            _LOGGER.exception(
                "Final composition artifact reconciliation failed.",
                extra={"workflow_id": workflow_id},
            )

    def _run_render(self, workflow_id: str, render_id: str) -> None:
        state = self._load_state(workflow_id, render_id)
        if state["status"] == "cancelled":
            return
        try:
            running = self._transition(state, "running")
            self._write_state(workflow_id, render_id, running)
            if running.get("render_mode") != "simple_sequence":
                self._timeline_service.load_or_create_and_reconcile(workflow_id)
            self._append_render_event(workflow_id, "final_composition_render_started", running)
            request = WorkflowV2TimelineRenderRequest.model_validate(running["request"])
            simple_plan = (
                self._load_simple_plan(workflow_id, render_id)
                if running.get("render_mode") == "simple_sequence"
                else None
            )
            service = V2FinalCompositionTimelineService(
                self._settings,
                renderer_factory=self._renderer_factory(workflow_id, render_id),
            )
            result = service.render_timeline(
                workflow_id,
                request,
                render_id=render_id,
                emit_lifecycle_events=False,
                simple_plan_override=simple_plan,
                enforce_current_timeline_version=False,
                composition_fingerprint=V2FinalCompositionFingerprint(
                    contract_version=running["fingerprint_contract_version"],
                    fingerprint=running["composition_fingerprint"],
                    canonical_payload=running["composition_fingerprint_payload"],
                ),
                source_action="editor_export",
                select_result=True,
            )
        except V2FinalCompositionTimelineError as exc:
            self._fail_render(workflow_id, render_id, exc.code, str(exc))
            return
        except Exception:  # noqa: BLE001 - worker failures must reach a durable terminal state.
            self._fail_render(
                workflow_id,
                render_id,
                "v2_timeline_render_failed",
                "Final composition render failed before completion.",
            )
            return
        completed = self._transition(
            self._load_state(workflow_id, render_id),
            "completed",
            asset_id=result.asset_id,
            version_id=result.version_id,
            output_url=result.public_url,
            progress_seconds=running["total_seconds"],
            progress_percent=100.0,
        )
        self._write_state(workflow_id, render_id, completed)
        with _REGISTRY_LOCK:
            _PROCESS_REGISTRY.pop((str(self._data_dir), workflow_id), None)
        self.reconcile_final_composition_artifacts(workflow_id)

    def _fail_render(
        self,
        workflow_id: str,
        render_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        current = self._load_state(workflow_id, render_id)
        if current["status"] == "cancellation_requested":
            self._transition_cancelled(current)
            return
        if current["status"] in _TERMINAL_STATUSES:
            with _REGISTRY_LOCK:
                _PROCESS_REGISTRY.pop((str(self._data_dir), workflow_id), None)
            return
        failed = self._transition(
            current,
            "failed",
            error_code=error_code,
            error_message=error_message,
        )
        self._write_state(workflow_id, render_id, failed)
        self._append_render_event(workflow_id, "final_composition_render_failed", failed)
        with _REGISTRY_LOCK:
            _PROCESS_REGISTRY.pop((str(self._data_dir), workflow_id), None)
        self.reconcile_final_composition_artifacts(workflow_id)

    def _renderer_factory(
        self,
        workflow_id: str,
        render_id: str,
    ) -> Callable[[Path, Settings], V2FinalCompositionRenderer]:
        def factory(data_dir: Path, settings: Settings) -> V2FinalCompositionRenderer:
            return V2FinalCompositionRenderer(
                data_dir=data_dir,
                settings=settings,
                runner=lambda args, **_kwargs: self._run_process(
                    workflow_id,
                    render_id,
                    args,
                ),
            )

        return factory

    def _run_process(
        self,
        workflow_id: str,
        render_id: str,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        state = self._load_state(workflow_id, render_id)
        if state["status"] in {"cancellation_requested", "cancelled"}:
            return subprocess.CompletedProcess(args, -15, "", "render cancelled")
        command = [*args[:-1], "-progress", "pipe:1", "-nostats", args[-1]]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _REGISTRY_LOCK:
            _PROCESS_REGISTRY[(str(self._data_dir), workflow_id)] = process
        stdout: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                stdout.append(line)
                self._record_progress(workflow_id, render_id, line)
        stderr_lines: list[str] = []

        def read_stderr() -> None:
            if process.stderr is not None:
                stderr_lines.append(process.stderr.read())

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()
        returncode = process.wait()
        stderr_thread.join(timeout=2)
        return subprocess.CompletedProcess(
            command,
            returncode,
            "".join(stdout),
            "".join(stderr_lines)[-8192:],
        )

    def _record_progress(self, workflow_id: str, render_id: str, line: str) -> None:
        if not line.startswith("out_time_"):
            return
        key, _, raw_value = line.partition("=")
        try:
            seconds = float(raw_value.strip()) / (1_000_000 if key == "out_time_us" else 1_000)
        except ValueError:
            return
        state = self._load_state(workflow_id, render_id)
        total = float(state.get("total_seconds") or 0)
        percent = min(100.0, max(0.0, seconds / total * 100 if total else 0.0))
        updated = self._transition(
            state,
            state["status"],
            progress_seconds=seconds,
            progress_percent=percent,
        )
        self._write_state(workflow_id, render_id, updated)
        self._append_render_event(workflow_id, "final_composition_render_progress", updated)

    def _transition_cancelled(self, state: dict[str, Any]) -> WorkflowV2TimelineRenderStateResponse:
        cancelled = self._transition(state, "cancelled")
        self._write_state(cancelled["workflow_id"], cancelled["render_id"], cancelled)
        self._append_render_event(
            cancelled["workflow_id"], "final_composition_render_cancelled", cancelled
        )
        with _REGISTRY_LOCK:
            _PROCESS_REGISTRY.pop((str(self._data_dir), cancelled["workflow_id"]), None)
        self.reconcile_final_composition_artifacts(cancelled["workflow_id"])
        return WorkflowV2TimelineRenderStateResponse.model_validate(cancelled)

    def _transition(self, state: dict[str, Any], status: str, **updates: Any) -> dict[str, Any]:
        return {
            **state,
            **updates,
            "status": status,
            "updated_at": utc_now().isoformat(),
            "events_cursor": self._events.events_cursor(state["workflow_id"]),
        }

    def _event_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_id": state["workflow_id"],
            "render_id": state["render_id"],
            "timeline_id": state["timeline_id"],
            "timeline_version": state["timeline_version"],
            "status": state["status"],
            "progress_seconds": state.get("progress_seconds"),
            "total_seconds": state.get("total_seconds"),
            "progress_percent": state.get("progress_percent"),
            "render_mode": state.get("render_mode"),
            "included_shot_ids": state.get("included_shot_ids", []),
            "missing_shot_ids": state.get("missing_shot_ids", []),
            "source_asset_versions": state.get("source_asset_versions", []),
            "bgm_status": state.get("bgm_status"),
            "bgm_gain_db": state.get("bgm_gain_db"),
            "timeline_controls_applied": state.get("timeline_controls_applied"),
            "composition_fingerprint": state.get("composition_fingerprint"),
            "fingerprint_contract_version": state.get("fingerprint_contract_version"),
            "reused": state.get("reused", False),
            "reused_from_render_id": state.get("reused_from_render_id"),
            "reuse_kind": state.get("reuse_kind"),
        }

    @staticmethod
    def _start_response(state: dict[str, Any]) -> WorkflowV2TimelineRenderStartResponse:
        return WorkflowV2TimelineRenderStartResponse(
            workflow_id=state["workflow_id"],
            render_id=state["render_id"],
            status=state["status"],
            timeline_id=state["timeline_id"],
            timeline_version=state["timeline_version"],
            events_cursor=state["events_cursor"],
            output_url=state.get("output_url"),
            asset_id=state.get("asset_id"),
            version_id=state.get("version_id"),
            reused=bool(state.get("reused", False)),
            composition_fingerprint=state.get("composition_fingerprint"),
        )

    def _append_render_event(
        self,
        workflow_id: str,
        event_type: str,
        state: dict[str, Any],
    ) -> None:
        event = self._events.append_event(
            workflow_id,
            event_type,
            node_id=state.get("node_id", FINAL_NODE_ID),
            item_id=state.get("item_id"),
            slot_id=state.get("slot_id"),
            asset_id=state.get("asset_id"),
            version_id=state.get("version_id"),
            payload=self._event_payload(state),
        )
        self._write_state(
            workflow_id,
            state["render_id"],
            {**state, "events_cursor": event.seq, "updated_at": utc_now().isoformat()},
        )

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                return
            process.wait(timeout=2)

    def _active_state(self, workflow_id: str) -> dict[str, Any] | None:
        for state_path in self._composition_dir(workflow_id).glob("render_*/state.json"):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("status") in _ACTIVE_STATUSES:
                return state
        return None

    def _load_state(self, workflow_id: str, render_id: str) -> dict[str, Any]:
        path = self._state_path(workflow_id, render_id)
        if not path.exists():
            raise V2FinalCompositionTimelineError(
                "v2_timeline_render_not_found",
                "Final composition render was not found.",
                status_code=404,
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_state(self, workflow_id: str, render_id: str, state: dict[str, Any]) -> None:
        path = self._state_path(workflow_id, render_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _simple_plan_path(self, workflow_id: str, render_id: str) -> Path:
        path = self._composition_dir(workflow_id) / render_id / "simple-sequence-plan.json"
        return validate_v2_data_path(
            self._data_dir,
            path,
            operation="v2-simple-composition-plan-write",
        )

    def _write_simple_plan(
        self,
        workflow_id: str,
        render_id: str,
        plan: V2SimpleCompositionPlan,
    ) -> None:
        path = self._simple_plan_path(workflow_id, render_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _load_simple_plan(
        self,
        workflow_id: str,
        render_id: str,
    ) -> V2SimpleCompositionPlan:
        path = self._simple_plan_path(workflow_id, render_id)
        try:
            return V2SimpleCompositionPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise V2FinalCompositionTimelineError(
                "v2_simple_composition_plan_invalid",
                "Persisted simple composition input snapshot is unavailable.",
                status_code=500,
            ) from exc

    def _simple_plan_state_metadata(
        self,
        plan: V2SimpleCompositionPlan | None,
    ) -> dict[str, Any]:
        if plan is None:
            return {
                "render_mode": "timeline_editor",
                "timeline_controls_applied": True,
            }
        has_source_audio = True
        return {
            "render_mode": plan.render_mode,
            "included_shot_ids": [source.shot_id for source in plan.videos],
            "missing_shot_ids": list(plan.missing_shot_ids),
            "source_asset_versions": [
                {"asset_id": source.asset_id, "version_id": source.version_id}
                for source in plan.videos
            ],
            "bgm_status": plan.bgm_status,
            "bgm_gain_db": (
                self._settings.final_composition_bgm_gain_db_with_source
                if has_source_audio
                else self._settings.final_composition_bgm_gain_db_without_source
            ),
            "timeline_controls_applied": False,
        }

    def _composition_dir(self, workflow_id: str) -> Path:
        path = self._data_dir / "v2" / "runs" / workflow_id / "composition"
        return validate_v2_data_path(self._data_dir, path, operation="v2-composition-render-state")

    def _state_path(self, workflow_id: str, render_id: str) -> Path:
        if not render_id.startswith("render_") or not render_id.replace("_", "").isalnum():
            raise V2FinalCompositionTimelineError(
                "v2_timeline_render_not_found",
                "Final composition render id is invalid.",
                status_code=404,
            )
        return self._composition_dir(workflow_id) / render_id / "state.json"
