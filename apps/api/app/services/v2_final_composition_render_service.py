from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineRenderStateResponse,
)
from app.services.agent_trace import utc_now
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_final_composition_renderer import V2FinalCompositionRenderer
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


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_ACTIVE_STATUSES = {"queued", "running", "cancellation_requested"}
_REGISTRY_LOCK = threading.RLock()
_PROCESS_REGISTRY: dict[tuple[str, str], subprocess.Popen[str] | None] = {}


class V2FinalCompositionRenderService:
    """Durable, detached final-composition rendering over the canonical timeline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._events = V2RuntimeEventService(self._data_dir)
        self._timeline_service = V2FinalCompositionTimelineService(settings)

    def start_render(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineRenderRequest,
    ) -> WorkflowV2TimelineRenderStartResponse:
        workflow, item, slot, timeline, _source = (
            self._timeline_service.load_or_create_and_reconcile(workflow_id)
        )
        if (
            request.timeline_id != timeline.timeline_id
            or request.timeline_version != timeline.version
        ):
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Render request does not match the saved timeline version.",
                status_code=409,
            )
        if self._settings.media_mode.strip().lower() != "mock":
            try:
                V2MediaToolchainCapabilityService(self._settings).require_profile(
                    PROFILE_ID,
                    requires_subtitles=any(
                        clip.enabled and clip.clip_type == "subtitle" for clip in timeline.clips
                    ),
                )
            except V2MediaToolchainCapabilityError as exc:
                raise V2FinalCompositionTimelineError(
                    exc.code,
                    str(exc),
                    status_code=400,
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
        }
        with _REGISTRY_LOCK:
            active = self._active_state(workflow_id)
            if active is not None:
                raise V2FinalCompositionTimelineError(
                    "v2_timeline_render_already_active",
                    f"Render already active: {active['render_id']}",
                    status_code=409,
                    details={"active_render_id": active["render_id"]},
                )
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
        return WorkflowV2TimelineRenderStartResponse(
            workflow_id=workflow_id,
            render_id=render_id,
            timeline_id=timeline.timeline_id,
            timeline_version=timeline.version,
            events_cursor=event.seq,
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
        return recovered

    def _run_render(self, workflow_id: str, render_id: str) -> None:
        state = self._load_state(workflow_id, render_id)
        if state["status"] == "cancelled":
            return
        try:
            running = self._transition(state, "running")
            self._write_state(workflow_id, render_id, running)
            self._timeline_service.load_or_create_and_reconcile(workflow_id)
            self._append_render_event(workflow_id, "final_composition_render_started", running)
            request = WorkflowV2TimelineRenderRequest.model_validate(running["request"])
            service = V2FinalCompositionTimelineService(
                self._settings,
                renderer_factory=self._renderer_factory(workflow_id, render_id),
            )
            result = service.render_timeline(
                workflow_id,
                request,
                render_id=render_id,
                emit_lifecycle_events=False,
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
            progress_seconds=running["total_seconds"],
            progress_percent=100.0,
        )
        self._write_state(workflow_id, render_id, completed)
        with _REGISTRY_LOCK:
            _PROCESS_REGISTRY.pop((str(self._data_dir), workflow_id), None)

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
        }

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
