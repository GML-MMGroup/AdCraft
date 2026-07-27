import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2ProviderResult,
    V2ProviderTask,
    V2ProviderTaskPollResponse,
    WorkflowItemV2,
    WorkflowV2RuntimeSnapshot,
)
from app.services.v2_generation_pipeline import V2GenerationPipeline
from app.services.v2_provider_executor import V2ProviderExecutor
from app.services.v2_provider_result_store import V2ProviderResultStore
from app.services.v2_provider_task_service import V2ProviderTaskService
from app.services.v2_event_store import V2EventStore
from app.services.v2_workflow_planner import build_slot
from app.services.v2_workflow_store import V2WorkflowStore
from app.services.workflow_v2 import _SchedulerRunResult, WorkflowV2Error, WorkflowV2Service
from tests.helpers.v2_factories import (
    find_v2_slot,
    make_v2_completed_asset_workflow,
    make_v2_workflow,
    persist_v2_workflow_semantic,
)
from tests.helpers.v2_runtime import wait_for_v2_execution_state

pytestmark = [pytest.mark.integration, pytest.mark.media]

_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomfake mp4 bytes"


def _completed_final_video_result() -> V2ProviderResult:
    return V2ProviderResult(
        status="completed",
        media_type="video",
        asset_bytes=_MP4_BYTES,
        provider="local_composition_ffmpeg",
        provider_payload_snapshot={"provider_prompt": "compose final video"},
    )


def test_v2_stale_terminal_poll_exception_does_not_reopen_task(
    v2_media_data_dir: Path,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_terminal_poll_exception",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
        ],
    )
    slot = find_v2_slot(workflow, "shot-1:shot_cell_1")
    assert not isinstance(slot, dict)
    slot.status = "failed"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    task_store = V2ProviderTaskService(v2_media_data_dir)
    task = V2ProviderTask(
        task_id="task_terminal_poll_exception",
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_terminal_poll_exception",
        version_id="ver_terminal_poll_exception",
        provider="test-provider",
        remote_task_id="remote-terminal-poll-exception",
        status="failed",
        submitted_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        completed_at="2026-07-16T00:00:01+00:00",
        metadata={"media_type": "image", "slot_type": slot.slot_type},
    )
    task_store.save_task(task)
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )

    response = service._record_provider_task_poll_exception(
        workflow.workflow_id,
        task,
        WorkflowV2Error(
            "provider_task_already_terminal",
            "A concurrent poll already finalized this provider task.",
        ),
    )

    persisted_task = task_store.load_task(workflow.workflow_id, task.task_id)
    persisted_slot = find_v2_slot(service.get_workflow(workflow.workflow_id), slot.slot_id)
    assert persisted_task is not None
    assert not isinstance(persisted_slot, dict)
    assert response.task.status == "failed"
    assert persisted_task.status == "failed"
    assert persisted_slot.status == "failed"
    assert persisted_task.last_error_code is None


def test_v2_concurrent_batches_reconcile_one_task_once_before_scheduling(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_concurrent_provider_poll",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
        ],
    )
    slot = find_v2_slot(workflow, "shot-1:shot_cell_1")
    assert not isinstance(slot, dict)
    slot.status = "waiting"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    settings = Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    first_service = WorkflowV2Service(settings)
    second_service = WorkflowV2Service(settings)
    item = first_service._find_item(workflow, slot.node_id, slot.item_id)
    assert item is not None
    item.reference_item_ids = ["product-1", "character-1", "scene-1"]
    item.primary_scene_item_id = "scene-1"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    plan = first_service._generation_pipeline.build_plan(
        workflow,
        item,
        slot,
        source_action="global_run",
    )
    task = V2ProviderTask(
        task_id="task_concurrent_provider_poll",
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_concurrent_provider_poll",
        version_id="ver_concurrent_provider_poll",
        provider="test-provider",
        provider_model="test-model",
        remote_task_id="remote-concurrent-provider-poll",
        status="waiting",
        submitted_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        next_poll_at="2000-01-01T00:00:00+00:00",
        provider_payload_snapshot=plan.provider_payload,
        metadata={
            "attempt_id": "attempt_concurrent_provider_poll",
            "input_fingerprint": first_service._generation_pipeline.input_fingerprint(
                workflow,
                item,
                slot,
            ),
            "generation_plan_snapshot": plan.model_dump(mode="json"),
            "source_action": "global_run",
            "select_generated": True,
            "media_type": "image",
            "slot_type": slot.slot_type,
            "timeout_at": "2099-01-01T00:00:00+00:00",
        },
    )
    task_store = V2ProviderTaskService(v2_media_data_dir)
    task_store.save_task(task)
    first_poll_started = threading.Event()
    release_first_poll = threading.Event()
    remote_task_ids: list[str] = []
    scheduler_calls: list[str] = []

    def complete_after_blocking_first_poll(
        executor: V2ProviderExecutor,
        provider_task: V2ProviderTask,
    ) -> V2ProviderResult:
        remote_task_ids.append(str(provider_task.remote_task_id))
        first_poll_started.set()
        assert release_first_poll.wait(timeout=2)
        return executor.execute_minimal(
            workflow_id=provider_task.workflow_id,
            slot_type=slot.slot_type,
            media_type="image",
            provider_payload={"provider_prompt": "Complete the existing result."},
        )

    def record_scheduler_call(*_args: Any, **_kwargs: Any) -> _SchedulerRunResult:
        scheduler_calls.append("scheduled")
        return _SchedulerRunResult()

    monkeypatch.setattr(V2ProviderExecutor, "poll_task", complete_after_blocking_first_poll)
    monkeypatch.setattr(first_service, "_run_missing_slot_scheduler", record_scheduler_call)
    monkeypatch.setattr(second_service, "_run_missing_slot_scheduler", record_scheduler_call)
    first_result: list[object] = []
    second_result: list[object] = []

    first_thread = threading.Thread(
        target=lambda: first_result.append(
            first_service._poll_provider_task_batch(
                workflow.workflow_id,
                [task],
                execution_id=None,
            )
        )
    )
    second_thread = threading.Thread(
        target=lambda: second_result.append(
            second_service._poll_provider_task_batch(
                workflow.workflow_id,
                [task],
                execution_id=None,
            )
        )
    )
    first_thread.start()
    assert first_poll_started.wait(timeout=2)
    second_thread.start()
    release_first_poll.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert first_result
    assert second_result
    assert remote_task_ids == [task.remote_task_id]
    assert scheduler_calls == ["scheduled"]
    persisted_task = task_store.load_task(workflow.workflow_id, task.task_id)
    persisted_slot = find_v2_slot(first_service.get_workflow(workflow.workflow_id), slot.slot_id)
    assert persisted_task is not None
    assert not isinstance(persisted_slot, dict)
    assert persisted_task.status == "completed"
    assert persisted_slot.status == "completed"
    assert persisted_slot.selected_asset_id
    assert persisted_slot.selected_version_id


def test_v2_due_provider_task_poll_continues_after_one_commit_exception(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_poll_commit_exception",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
        ],
    )
    first_slot = find_v2_slot(workflow, "shot-1:shot_cell_1")
    second_slot = find_v2_slot(workflow, "shot-1:shot_cell_2")
    assert not isinstance(first_slot, dict)
    assert not isinstance(second_slot, dict)
    first_slot.status = "waiting"
    second_slot.status = "waiting"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    task_store = V2ProviderTaskService(v2_media_data_dir)
    submitted_at = "2026-07-16T00:00:00+00:00"
    for task_id, slot in (
        ("task_01_commit_failure", first_slot),
        ("task_02_after_failure", second_slot),
    ):
        task_store.save_task(
            V2ProviderTask(
                task_id=task_id,
                workflow_id=workflow.workflow_id,
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=f"asset_{task_id}",
                version_id=f"ver_{task_id}",
                provider="test-provider",
                remote_task_id=f"remote_{task_id}",
                status="waiting",
                submitted_at=submitted_at,
                updated_at=submitted_at,
                next_poll_at="2000-01-01T00:00:00+00:00",
                metadata={"media_type": "image", "slot_type": slot.slot_type},
            )
        )
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    polled_task_ids: list[str] = []

    def poll_with_first_commit_failure(
        workflow_id: str,
        task_id: str,
        *,
        resume_scheduler: bool = True,
    ) -> V2ProviderTaskPollResponse:
        del resume_scheduler
        polled_task_ids.append(task_id)
        if task_id == "task_01_commit_failure":
            raise RuntimeError("canonical provider result commit failed")
        task = task_store.load_task(workflow_id, task_id)
        assert task is not None
        return V2ProviderTaskPollResponse(
            task=task,
            workflow=service.get_workflow(workflow_id),
            waiting_slot_ids=[task.slot_id],
        )

    monkeypatch.setattr(service, "poll_provider_task", poll_with_first_commit_failure)

    result = service.poll_due_provider_tasks(workflow.workflow_id)

    assert polled_task_ids == ["task_01_commit_failure", "task_02_after_failure"]
    assert result.waiting_task_ids == ["task_01_commit_failure", "task_02_after_failure"]
    failed_task = task_store.load_task(workflow.workflow_id, "task_01_commit_failure")
    assert failed_task is not None
    assert failed_task.status == "waiting"
    assert failed_task.last_error_code == "v2_provider_task_poll_exception"
    assert failed_task.next_poll_at is not None
    events = V2EventStore(v2_media_data_dir).list_events(workflow.workflow_id).events
    assert events[-1].event_type == "provider_task_waiting"
    assert events[-1].payload["error_code"] == "v2_provider_task_poll_exception"


def test_v2_due_provider_tasks_schedule_once_after_batch_commits(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_batch_provider_schedule",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
        ],
    )
    slots = [
        find_v2_slot(workflow, "shot-1:shot_cell_1"),
        find_v2_slot(workflow, "shot-1:shot_cell_2"),
    ]
    assert all(not isinstance(slot, dict) for slot in slots)
    resolved_slots = [slot for slot in slots if not isinstance(slot, dict)]
    for slot in resolved_slots:
        slot.status = "waiting"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    task_store = V2ProviderTaskService(v2_media_data_dir)
    submitted_at = "2026-07-16T00:00:00+00:00"
    for index, slot in enumerate(resolved_slots, start=1):
        task_store.save_task(
            V2ProviderTask(
                task_id=f"task_batch_{index}",
                workflow_id=workflow.workflow_id,
                node_id=slot.node_id,
                item_id=slot.item_id,
                slot_id=slot.slot_id,
                asset_id=f"asset_batch_{index}",
                version_id=f"ver_batch_{index}",
                provider="test-provider",
                remote_task_id=f"remote_batch_{index}",
                status="waiting",
                submitted_at=submitted_at,
                updated_at=submitted_at,
                next_poll_at="2000-01-01T00:00:00+00:00",
                metadata={"media_type": "image", "slot_type": slot.slot_type},
            )
        )
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    scheduler_calls = 0

    def commit_task_without_scheduling(
        workflow_id: str,
        task_id: str,
        *,
        resume_scheduler: bool,
    ) -> V2ProviderTaskPollResponse:
        assert resume_scheduler is False
        task = task_store.load_task(workflow_id, task_id)
        assert task is not None
        completed_task = task_store.save_task(task.model_copy(update={"status": "completed"}))
        return V2ProviderTaskPollResponse(
            task=completed_task,
            workflow=service.get_workflow(workflow_id),
            executed_slot_ids=[completed_task.slot_id],
        )

    def assert_batch_committed_before_scheduler(*_args: Any, **_kwargs: Any) -> _SchedulerRunResult:
        nonlocal scheduler_calls
        scheduler_calls += 1
        assert [task.status for task in task_store.list_tasks(workflow.workflow_id)] == [
            "completed",
            "completed",
        ]
        return _SchedulerRunResult()

    monkeypatch.setattr(service, "poll_provider_task", commit_task_without_scheduling)
    monkeypatch.setattr(
        service, "_run_missing_slot_scheduler", assert_batch_committed_before_scheduler
    )

    result = service.poll_due_provider_tasks(workflow.workflow_id)

    assert result.completed_task_ids == ["task_batch_1", "task_batch_2"]
    assert scheduler_calls == 1


def test_v2_download_timeout_keeps_provider_task_and_slot_waiting(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_download_retry",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
            *[f"shot-1:shot_cell_{index}" for index in range(1, 5)],
        ],
    )
    slot = find_v2_slot(workflow, "shot-1:shot_video_segment")
    assert not isinstance(slot, dict)
    slot.status = "waiting"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    task = V2ProviderTask(
        task_id="task_download_retry",
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_download_retry",
        version_id="ver_download_retry",
        provider="test-provider",
        provider_model="test-model",
        remote_task_id="remote-video-1",
        status="waiting",
        submitted_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        metadata={
            "media_type": "video",
            "slot_type": slot.slot_type,
            "timeout_at": "2099-01-01T00:00:00+00:00",
            "select_generated": True,
        },
    )
    V2ProviderTaskService(v2_media_data_dir).save_task(task)
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_mode="real",
            media_data_dir=v2_media_data_dir,
            v2_provider_download_max_attempts=3,
        )
    )

    def download_timeout(_self: V2ProviderExecutor, _task: V2ProviderTask) -> V2ProviderResult:
        return V2ProviderResult(
            status="failed",
            media_type="video",
            remote_task_id="remote-video-1",
            provider="test-provider",
            provider_model="test-model",
            error_code="provider_download_timeout",
            error_message="Remote media download timed out.",
            metadata={
                "stage": "provider_result_download",
                "download_retryable": True,
                "download_attempted": True,
                "remote_status": "succeeded",
            },
        )

    monkeypatch.setattr(V2ProviderExecutor, "poll_task", download_timeout)

    response = service.poll_provider_task(workflow.workflow_id, task.task_id)

    assert response.task.status == "waiting"
    assert response.provider_result is not None
    assert response.provider_result.status == "waiting"
    assert slot.slot_id in response.waiting_slot_ids
    assert slot.slot_id not in response.failed_slot_ids
    latest = service.get_workflow(workflow.workflow_id)
    latest_slot = find_v2_slot(latest, slot.slot_id)
    assert not isinstance(latest_slot, dict)
    assert latest_slot.status == "waiting"
    events = V2EventStore(v2_media_data_dir).list_events(workflow.workflow_id).events
    retry_events = [event for event in events if event.event_type == "provider_task_waiting"]
    assert retry_events[-1].payload["waiting_reason"] == "provider_result_download_retry"
    assert retry_events[-1].payload["error_code"] == "provider_download_timeout"
    assert retry_events[-1].payload["download_attempt"] == 1
    assert retry_events[-1].payload["max_download_attempts"] == 3
    assert retry_events[-1].payload["remote_status"] == "succeeded"
    assert not {
        "provider_execution_failed",
        "provider_task_failed",
        "slot_generation_failed",
    }.intersection(event.event_type for event in events)


def test_v2_download_retry_budget_exhaustion_uses_terminal_download_code(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_download_retry_exhaustion",
        audio_mode="none",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
            *[f"shot-1:shot_cell_{index}" for index in range(1, 5)],
        ],
    )
    slot = find_v2_slot(workflow, "shot-1:shot_video_segment")
    assert not isinstance(slot, dict)
    slot.status = "waiting"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    task = V2ProviderTask(
        task_id="task_download_retry_exhaustion",
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_download_retry_exhaustion",
        version_id="ver_download_retry_exhaustion",
        provider="test-provider",
        provider_model="test-model",
        remote_task_id="remote-video-exhaustion",
        status="waiting",
        submitted_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        metadata={
            "media_type": "video",
            "slot_type": slot.slot_type,
            "timeout_at": "2099-01-01T00:00:00+00:00",
            "select_generated": True,
            "historical_result_recovery": {
                "original_timeout_at": "2000-01-01T00:00:00+00:00",
                "started_at": "2026-07-16T00:00:00+00:00",
            },
        },
    )
    V2ProviderTaskService(v2_media_data_dir).save_task(task)
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_mode="real",
            media_data_dir=v2_media_data_dir,
            v2_provider_download_max_attempts=3,
        )
    )

    def download_timeout(_self: V2ProviderExecutor, _task: V2ProviderTask) -> V2ProviderResult:
        return V2ProviderResult(
            status="failed",
            media_type="video",
            remote_task_id="remote-video-exhaustion",
            provider="test-provider",
            provider_model="test-model",
            error_code="provider_download_timeout",
            error_message="Remote media download timed out.",
            metadata={
                "stage": "provider_result_download",
                "download_retryable": True,
                "download_attempted": True,
                "download_status": "failed",
                "remote_status": "succeeded",
            },
        )

    monkeypatch.setattr(V2ProviderExecutor, "poll_task", download_timeout)

    first = service.poll_provider_task(workflow.workflow_id, task.task_id)
    second = service.poll_provider_task(workflow.workflow_id, task.task_id)
    third = service.poll_provider_task(workflow.workflow_id, task.task_id)

    assert first.task.status == "waiting"
    assert second.task.status == "waiting"
    assert third.task.status == "failed"
    assert third.provider_result is not None
    assert third.provider_result.error_code == "provider_result_download_exhausted"
    updated_task = V2ProviderTaskService(v2_media_data_dir).load_task(
        workflow.workflow_id,
        task.task_id,
    )
    assert updated_task is not None
    assert updated_task.poll_count == 3
    assert updated_task.retry_count == 0
    assert updated_task.download_attempt_count == 3
    assert updated_task.metadata["historical_result_recovery"]["exhausted"] is True
    assert not service._reopen_historical_provider_result_tasks(
        service.get_workflow(workflow.workflow_id)
    )


def test_v2_global_run_reports_four_image_slots_running_concurrently(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_parallel_four_images",
        audio_mode="none",
    )
    _add_character_item(workflow, item_id="character-2")
    _skip_non_main_generation_slots(workflow)
    persist_v2_workflow_semantic(workflow, v2_media_data_dir, source="structure_edit")
    settings = Settings(
        agent_runtime_mode="fake",
        media_data_dir=v2_media_data_dir,
        v2_max_parallel_image_jobs=4,
        v2_max_parallel_generation_jobs=5,
    )
    service = WorkflowV2Service(settings)
    original_execute = V2ProviderExecutor.execute
    started: list[str] = []
    lock = threading.Lock()
    four_started = threading.Event()
    release = threading.Event()

    def blocking_images(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        slot_id = str(getattr(slot, "slot_id", ""))
        if getattr(slot, "media_type", "") == "image" and slot_id in {
            "product-1:product_main_image",
            "character-1:character_main_image",
            "character-2:character_main_image",
            "scene-1:scene_main_image",
        }:
            with lock:
                started.append(slot_id)
                if len(set(started)) >= 4:
                    four_started.set()
            assert release.wait(timeout=5), "test did not release blocking image provider"
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", blocking_images)

    response = service.run_workflow(workflow.workflow_id, wait=False)
    assert response.status == "queued"
    assert four_started.wait(timeout=2), f"started image slots: {started}"

    runtime = service.runtime_snapshot(workflow.workflow_id)
    running_image_slots = [
        slot_id
        for slot_id in runtime.running_slot_ids
        if runtime.slot_runtime[slot_id]["media_type"] == "image"
    ]
    assert {
        "product-1:product_main_image",
        "character-1:character_main_image",
        "character-2:character_main_image",
        "scene-1:scene_main_image",
    }.issubset(set(running_image_slots))
    assert {"product-generation", "character-generation", "scene-generation"}.issubset(
        set(runtime.running_node_ids)
    )
    started_events = service.list_events(workflow.workflow_id).events
    slot_started = [
        event
        for event in started_events
        if event.event_type == "slot_generation_started"
        and event.slot_id == "character-2:character_main_image"
    ][0]
    assert slot_started.payload["execution_id"]
    assert slot_started.payload["node_id"] == "character-generation"
    assert slot_started.payload["item_id"] == "character-2"
    assert slot_started.payload["slot_type"] == "character_main_image"
    assert slot_started.payload["media_type"] == "image"
    assert slot_started.payload["status"] == "running"

    release.set()
    _wait_for_terminal_runtime(service, workflow.workflow_id)
    latest = service.get_workflow(workflow.workflow_id)
    for slot_id in (
        "product-1:product_main_image",
        "character-1:character_main_image",
        "character-2:character_main_image",
        "scene-1:scene_main_image",
    ):
        slot = find_v2_slot(latest, slot_id)
        assert not isinstance(slot, dict)
        assert slot.selected_asset_id
        assert slot.selected_version_id


def test_v2_scheduler_drains_started_workers_after_coordinator_failure(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preflight failure must not discard manifests from already-started provider workers.

    The 2026-07-13 incident ``adwf_v2_171fb4f7d4d0`` recorded a minimal failed
    execution state after storyboard fallback validation failed, despite prior
    ``slot_generation_started`` events and provider staging output.  This isolated
    fixture reproduces the scheduling boundary without reading that runtime data.
    """
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_scheduler_drain",
        audio_mode="none",
    )
    retained_slot_ids = {
        "product-1:product_main_image",
        "character-1:character_main_image",
    }
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id not in retained_slot_ids:
                    slot.required = False
                    slot.status = "skipped"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_data_dir=v2_media_data_dir,
            v2_max_parallel_generation_jobs=2,
        )
    )
    original_execute = V2ProviderExecutor.execute
    started = threading.Event()
    release = threading.Event()
    started_slot_ids: list[str] = []
    lock = threading.Lock()
    synchronize_calls = 0

    def blocking_provider(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        with lock:
            started_slot_ids.append(str(getattr(slot, "slot_id", "")))
            if len(started_slot_ids) == 2:
                started.set()
        assert release.wait(timeout=5), "test did not release provider workers"
        return original_execute(self, workflow_obj, item, slot, plan)

    def fail_after_first_scheduler_iteration(*_args: object, **_kwargs: object) -> None:
        nonlocal synchronize_calls
        synchronize_calls += 1
        if synchronize_calls > 1:
            raise RuntimeError("deterministic preflight failure")

    monkeypatch.setattr(V2ProviderExecutor, "execute", blocking_provider)
    monkeypatch.setattr(service, "_unlock_dynamic_v2_slots", fail_after_first_scheduler_iteration)
    errors: list[Exception] = []

    def run_scheduler() -> None:
        service._execution_context.execution_id = "exec_scheduler_drain"
        try:
            service._run_missing_slot_scheduler(
                workflow,
                source_action="global_run",
                include_failed_slots=True,
            )
        except Exception as exc:  # noqa: BLE001 - the assertion verifies coordinator failure.
            errors.append(exc)

    thread = threading.Thread(target=run_scheduler)
    thread.start()
    assert started.wait(timeout=2), f"started slots: {started_slot_ids}"
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], WorkflowV2Error)
    assert errors[0].code == "v2_execution_internal_error"
    for slot_id in retained_slot_ids:
        slot = find_v2_slot(workflow, slot_id)
        assert not isinstance(slot, dict)
        assert slot.status == "completed"
        assert slot.selected_asset_id
        assert slot.selected_version_id


def test_v2_scheduler_drains_pending_manifests_after_canonical_commit_failure(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_scheduler_commit_drain",
        audio_mode="none",
    )
    retained_slot_ids = {
        "product-1:product_main_image",
        "character-1:character_main_image",
    }
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id not in retained_slot_ids:
                    slot.required = False
                    slot.status = "skipped"
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_data_dir=v2_media_data_dir,
            v2_max_parallel_generation_jobs=2,
        )
    )

    def fail_canonical_commit(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated canonical metadata write failure")

    monkeypatch.setattr(service, "_commit_slot_execution_result", fail_canonical_commit)
    service._execution_context.execution_id = "exec_scheduler_commit_drain"

    with pytest.raises(WorkflowV2Error) as exc_info:
        service._run_missing_slot_scheduler(
            workflow,
            source_action="global_run",
            include_failed_slots=True,
        )

    assert exc_info.value.code == "v2_execution_internal_error"
    manifests = V2ProviderResultStore(v2_media_data_dir).list_manifests(
        workflow_id=workflow.workflow_id,
        execution_id="exec_scheduler_commit_drain",
    )
    assert {manifest.slot_id for manifest in manifests} == retained_slot_ids
    assert {manifest.commit_status for manifest in manifests} == {"pending"}


def test_v2_global_run_honors_image_concurrency_limit(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_parallel_image_limit",
        audio_mode="none",
    )
    _add_character_item(workflow, item_id="character-2")
    _skip_non_main_generation_slots(workflow)
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    settings = Settings(
        agent_runtime_mode="fake",
        media_data_dir=v2_media_data_dir,
        v2_max_parallel_image_jobs=2,
        v2_max_parallel_generation_jobs=5,
    )
    service = WorkflowV2Service(settings)
    original_execute = V2ProviderExecutor.execute
    started: list[str] = []
    lock = threading.Lock()
    two_started = threading.Event()
    third_started = threading.Event()
    release = threading.Event()

    def blocking_images(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        if getattr(slot, "media_type", "") == "image":
            with lock:
                if str(getattr(slot, "slot_type", "")).endswith("main_image"):
                    started.append(str(getattr(slot, "slot_id", "")))
                    if len(started) == 2:
                        two_started.set()
                    if len(started) >= 3:
                        third_started.set()
            assert release.wait(timeout=5), "test did not release blocking image provider"
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", blocking_images)

    service.run_workflow(workflow.workflow_id, wait=False)
    assert two_started.wait(timeout=2), f"started image slots: {started}"
    assert not third_started.wait(timeout=0.2), f"image limit was exceeded: {started}"

    runtime = service.runtime_snapshot(workflow.workflow_id)
    running_main_images = [
        slot_id
        for slot_id in runtime.running_slot_ids
        if runtime.slot_runtime[slot_id]["slot_type"].endswith("main_image")
    ]
    assert len(running_main_images) == 2

    release.set()
    _wait_for_terminal_runtime(service, workflow.workflow_id)


@pytest.mark.e2e
@pytest.mark.slow
def test_v2_core_visual_to_video_flow_keeps_same_shot_selected_cells(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_core_visual_to_video",
        audio_mode="none",
    )
    _add_character_item(workflow, item_id="character-2")
    _add_scene_item(workflow, item_id="scene-2")
    script_plan = workflow.metadata["script_plan"]
    assert isinstance(script_plan, dict)
    shots = script_plan["shots"]
    assert isinstance(shots, list)
    shots[0].update(
        {
            "character_ids": ["character-1"],
            "scene_ids": ["scene-1"],
            "reference_item_ids": ["product-1", "character-1", "scene-1"],
        }
    )
    shots[1].update(
        {
            "character_ids": ["character-2"],
            "scene_ids": ["scene-2"],
            "reference_item_ids": ["product-1", "character-2", "scene-2"],
        }
    )
    persist_v2_workflow_semantic(workflow, v2_media_data_dir, source="structure_edit")
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_mode="mock",
            media_data_dir=v2_media_data_dir,
        )
    )
    original_execute = V2ProviderExecutor.execute

    def complete_final_video(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        if getattr(slot, "slot_type", "") == "final_video":
            return _completed_final_video_result()
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", complete_final_video)

    response = service.run_workflow(workflow.workflow_id, wait=True)
    state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        response.execution_id,
    )

    assert state["status"] == "completed"
    latest = service.get_workflow(workflow.workflow_id)
    for slot_id in (
        "product-1:product_main_image",
        "product-1:product_multi_view_grid",
        "character-1:character_main_image",
        "character-1:character_three_view",
        "character-2:character_main_image",
        "character-2:character_three_view",
        "scene-1:scene_main_image",
        "scene-1:scene_multi_view_grid",
        "scene-2:scene_main_image",
        "scene-2:scene_multi_view_grid",
    ):
        slot = find_v2_slot(latest, slot_id)
        assert not isinstance(slot, dict)
        assert slot.status == "completed"
        assert slot.selected_asset_id
        assert slot.selected_version_id
    for shot_id in ("shot-1", "shot-2"):
        cell_asset_ids: set[str] = set()
        for index in range(1, 5):
            cell = find_v2_slot(latest, f"{shot_id}:shot_cell_{index}")
            assert not isinstance(cell, dict)
            assert cell.status == "completed"
            assert cell.selected_asset_id
            cell_asset_ids.add(cell.selected_asset_id)
        video = find_v2_slot(latest, f"{shot_id}:shot_video_segment")
        assert not isinstance(video, dict)
        assert video.status == "completed"
        assert video.selected_asset_id and video.selected_version_id
        asset = service._asset_store.load_asset_version(
            video.selected_asset_id,
            video.selected_version_id,
        )
        assert asset is not None
        assert set(asset.reference_asset_ids) == cell_asset_ids
    final_video = find_v2_slot(latest, "final-composition-1:final_video")
    assert not isinstance(final_video, dict)
    assert final_video.status == "completed"
    assert final_video.selected_asset_id and final_video.selected_version_id
    final_asset = service._asset_store.load_asset_version(
        final_video.selected_asset_id,
        final_video.selected_version_id,
    )
    assert final_asset is not None
    assert final_asset.public_url and final_asset.public_url.startswith("/media/")
    assert (v2_media_data_dir / final_asset.file_path).exists()


@pytest.mark.e2e
@pytest.mark.slow
def test_v2_unconfigured_bgm_is_skipped_without_blocking_final_composition(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_unconfigured_bgm",
        audio_mode="bgm_only",
    )
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    original_execute = V2ProviderExecutor.execute

    def skip_unconfigured_bgm(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        if getattr(slot, "slot_type", "") == "bgm_audio":
            return V2ProviderResult(
                status="skipped",
                media_type="audio",
                provider="unconfigured-bgm-provider",
                error_code="bgm_provider_unconfigured",
                error_message="BGM provider is not configured.",
            )
        if getattr(slot, "slot_type", "") == "final_video":
            return _completed_final_video_result()
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", skip_unconfigured_bgm)

    response = service.run_workflow(workflow.workflow_id, wait=True)
    state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        response.execution_id,
    )

    assert state["status"] == "completed"
    latest = service.get_workflow(workflow.workflow_id)
    bgm = find_v2_slot(latest, "bgm-1:bgm_audio")
    final_video = find_v2_slot(latest, "final-composition-1:final_video")
    assert not isinstance(bgm, dict)
    assert not isinstance(final_video, dict)
    assert bgm.status == "skipped"
    assert bgm.metadata["skipped_reason"] == "bgm_provider_unconfigured"
    assert final_video.status == "completed"
    assert final_video.selected_asset_id and final_video.selected_version_id


def test_v2_fill_missing_retries_failed_visual_without_rerunning_valid_branch(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_retry_failed_visual_branch",
        audio_mode="none",
    )
    retained_slot_ids = {
        "product-1:product_main_image",
        "product-1:product_multi_view_grid",
        "scene-1:scene_main_image",
        "scene-1:scene_multi_view_grid",
    }
    _skip_slots_except(workflow, retained_slot_ids)
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    original_execute = V2ProviderExecutor.execute
    provider_calls: list[str] = []
    fail_scene_once = True

    def fail_one_required_visual(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        nonlocal fail_scene_once
        slot_id = str(getattr(slot, "slot_id", ""))
        provider_calls.append(slot_id)
        if slot_id == "scene-1:scene_main_image" and fail_scene_once:
            fail_scene_once = False
            return V2ProviderResult(
                status="failed",
                media_type="image",
                provider="deterministic-test-provider",
                error_code="provider_generation_failed",
                error_message="deterministic scene failure",
            )
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", fail_one_required_visual)

    first_response = service.run_workflow(workflow.workflow_id, wait=True)
    first_state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        first_response.execution_id,
    )

    assert first_state["status"] == "partial_failed"
    first_workflow = service.get_workflow(workflow.workflow_id)
    product_main = find_v2_slot(first_workflow, "product-1:product_main_image")
    product_multiview = find_v2_slot(first_workflow, "product-1:product_multi_view_grid")
    scene_main = find_v2_slot(first_workflow, "scene-1:scene_main_image")
    scene_multiview = find_v2_slot(first_workflow, "scene-1:scene_multi_view_grid")
    assert not isinstance(product_main, dict)
    assert not isinstance(product_multiview, dict)
    assert not isinstance(scene_main, dict)
    assert not isinstance(scene_multiview, dict)
    assert product_main.status == "completed"
    assert product_multiview.status == "completed"
    assert scene_main.status == "failed"
    assert scene_multiview.status == "blocked"
    assert "product-1:product_main_image" in provider_calls
    assert "product-1:product_multi_view_grid" in provider_calls
    assert "scene-1:scene_main_image" in provider_calls
    assert "scene-1:scene_multi_view_grid" not in provider_calls

    provider_calls.clear()
    retry_response = service.run_workflow(workflow.workflow_id, wait=True)
    retry_state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        retry_response.execution_id,
    )

    assert retry_state["status"] == "completed"
    retried_workflow = service.get_workflow(workflow.workflow_id)
    retried_scene_main = find_v2_slot(retried_workflow, "scene-1:scene_main_image")
    retried_scene_multiview = find_v2_slot(retried_workflow, "scene-1:scene_multi_view_grid")
    assert not isinstance(retried_scene_main, dict)
    assert not isinstance(retried_scene_multiview, dict)
    assert retried_scene_main.status == "completed"
    assert retried_scene_multiview.status == "completed"
    assert provider_calls == [
        "scene-1:scene_main_image",
        "scene-1:scene_multi_view_grid",
    ]


def test_v2_last_provider_failure_persists_terminal_slot_status(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_last_provider_failure",
        audio_mode="none",
    )
    retained_slot_id = "scene-1:scene_main_image"
    _skip_slots_except(workflow, {retained_slot_id})
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )

    def fail_only_provider(
        _self: V2ProviderExecutor,
        _workflow_obj: object,
        _item: object,
        _slot: object,
        _plan: object,
    ) -> V2ProviderResult:
        return V2ProviderResult(
            status="failed",
            media_type="image",
            provider="deterministic-test-provider",
            error_code="provider_request_invalid",
            error_message="deterministic terminal provider failure",
            metadata={"stage": "provider_call", "request_summary": {"bounded": True}},
        )

    monkeypatch.setattr(V2ProviderExecutor, "execute", fail_only_provider)

    response = service.run_workflow(workflow.workflow_id, wait=True)
    state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        response.execution_id,
    )

    latest_slot = find_v2_slot(service.get_workflow(workflow.workflow_id), retained_slot_id)
    assert not isinstance(latest_slot, dict)
    assert state["status"] == "failed"
    assert latest_slot.status == "failed"
    assert latest_slot.metadata["error"]["code"] == "provider_request_invalid"


@pytest.mark.e2e
@pytest.mark.slow
def test_v2_scene_lighting_heading_unblocks_dependent_storyboard_cells(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_scene_lighting_unblocks_shots",
        audio_mode="none",
    )
    final_slot = find_v2_slot(workflow, "final-composition-1:final_video")
    assert not isinstance(final_slot, dict)
    final_slot.required = False
    final_slot.status = "skipped"
    persist_v2_workflow_semantic(workflow, v2_media_data_dir, source="structure_edit")
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    original_build_plan = V2GenerationPipeline.build_plan

    def build_plan_with_scene_heading(
        pipeline: V2GenerationPipeline,
        workflow_obj: object,
        item: object,
        slot: object,
        **kwargs: object,
    ) -> object:
        plan = original_build_plan(pipeline, workflow_obj, item, slot, **kwargs)  # type: ignore[arg-type]
        if getattr(slot, "slot_id", "") != "scene-1:scene_main_image":
            return plan
        payload = dict(getattr(plan, "provider_payload"))
        prompt = "Lighting: clean natural daylight defines the scene reference. " + str(
            payload.get("provider_prompt") or ""
        )
        canonical_payload = dict(payload.get("canonical_provider_payload") or {})
        canonical_payload["provider_prompt"] = prompt
        payload["provider_prompt"] = prompt
        payload["canonical_provider_payload"] = canonical_payload
        materialized_prompt = getattr(plan, "materialized_prompt").model_copy(
            update={"provider_prompt": prompt, "provider_payload": payload}
        )
        return getattr(plan, "model_copy")(
            update={"provider_payload": payload, "materialized_prompt": materialized_prompt},
            deep=True,
        )

    monkeypatch.setattr(V2GenerationPipeline, "build_plan", build_plan_with_scene_heading)

    response = service.run_workflow(workflow.workflow_id, wait=True)
    state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        response.execution_id,
    )

    assert state["status"] == "completed"
    latest = service.get_workflow(workflow.workflow_id)
    scene_main = find_v2_slot(latest, "scene-1:scene_main_image")
    assert not isinstance(scene_main, dict)
    assert scene_main.status == "completed"
    for shot_id in ("shot-1", "shot-2"):
        for index in range(1, 5):
            cell = find_v2_slot(latest, f"{shot_id}:shot_cell_{index}")
            assert not isinstance(cell, dict)
            assert cell.status == "completed"


def test_v2_due_provider_task_poll_completes_without_frontend_polling_and_runs_final(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_slots = [
        "product-1:product_main_image",
        "product-1:product_multi_view_grid",
        "character-1:character_main_image",
        "character-1:character_three_view",
        "scene-1:scene_main_image",
        "scene-1:scene_multi_view_grid",
        *[f"shot-1:shot_cell_{index}" for index in range(1, 5)],
    ]
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_provider_task_backend_poll",
        audio_mode="none",
        selected_slots=selected_slots,
    )
    final_node = next(node for node in workflow.nodes if node.node_type == "final-composition")
    final_node.items = []
    _skip_slots(
        workflow,
        {
            *[f"shot-2:shot_cell_{index}" for index in range(1, 5)],
            "shot-2:shot_video_segment",
        },
    )
    persist_v2_workflow_semantic(
        workflow,
        v2_media_data_dir,
        source="structure_edit",
    )
    settings = Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    service = WorkflowV2Service(settings)
    original_execute = V2ProviderExecutor.execute

    def waiting_shot_one_video(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        if getattr(slot, "slot_id", "") == "shot-1:shot_video_segment":
            return V2ProviderResult(
                status="waiting",
                media_type="video",
                remote_task_id="remote-shot-video-1",
                provider="fake-video-provider",
                provider_model="fake-video-model",
                provider_payload_snapshot={"provider_prompt": "shot video"},
                reference_asset_ids=list(getattr(plan, "reference_asset_ids", [])),
                metadata={"waiting_reason": "remote_video_running"},
            )
        if getattr(slot, "slot_type", "") == "final_video":
            return _completed_final_video_result()
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", waiting_shot_one_video)

    run_response = service.run_workflow(workflow.workflow_id, wait=True)
    run_state = wait_for_v2_execution_state(
        v2_media_data_dir,
        workflow.workflow_id,
        run_response.execution_id,
    )
    assert run_state["status"] == "waiting"
    assert run_state["waiting_slot_ids"] == ["shot-1:shot_video_segment"]
    task_store = V2ProviderTaskService(v2_media_data_dir)
    task = task_store.list_nonterminal_tasks(workflow.workflow_id)[0]
    assert (
        task.provider_payload_snapshot["generation_lineage"]["script_version_id"]
        == (workflow.metadata["selected_script_version_id"])
    )
    task_store.save_task(task.model_copy(update={"next_poll_at": "2000-01-01T00:00:00+00:00"}))

    def completed_poll(self: V2ProviderExecutor, provider_task: object) -> V2ProviderResult:
        media_type = str(getattr(provider_task, "metadata", {}).get("media_type") or "video")
        slot_type = str(
            getattr(provider_task, "metadata", {}).get("slot_type") or "shot_video_segment"
        )
        return self.execute_minimal(
            workflow_id=str(getattr(provider_task, "workflow_id")),
            slot_type=slot_type,
            media_type=media_type,  # type: ignore[arg-type]
            provider_payload={"provider_prompt": "completed video"},
        )

    monkeypatch.setattr(V2ProviderExecutor, "poll_task", completed_poll)

    poll_result = service.poll_due_provider_tasks(workflow.workflow_id)

    assert poll_result.completed_task_ids == [task.task_id]
    completed_task = task_store.load_task(workflow.workflow_id, task.task_id)
    assert completed_task is not None
    assert (
        completed_task.provider_payload_snapshot["generation_lineage"]["script_version_id"]
        == workflow.metadata["selected_script_version_id"]
    )
    latest = service.get_workflow(workflow.workflow_id)
    shot_video = find_v2_slot(latest, "shot-1:shot_video_segment")
    final_video = find_v2_slot(latest, "final-composition-1:final_video")
    assert not isinstance(shot_video, dict)
    assert not isinstance(final_video, dict)
    assert shot_video.status == "completed"
    assert shot_video.selected_asset_id
    assert shot_video.selected_version_id
    assert final_video.status == "completed"
    assert final_video.selected_asset_id
    assert final_video.selected_version_id


def test_v2_due_provider_task_retryable_rate_limit_keeps_slot_waiting_and_records_cooldown(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_provider_task_retryable_rate_limit",
        selected_slots=[
            "product-1:product_main_image",
            "character-1:character_main_image",
            "scene-1:scene_main_image",
            *[f"shot-1:shot_cell_{index}" for index in range(1, 5)],
        ],
    )
    _skip_slots(
        workflow,
        {
            "bgm-1:bgm_audio",
            *[f"shot-2:shot_cell_{index}" for index in range(1, 5)],
            "shot-2:shot_video_segment",
            "final-composition-1:final_video",
        },
    )
    V2WorkflowStore(v2_media_data_dir).save_workflow(workflow)
    settings = Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    service = WorkflowV2Service(settings)
    original_execute = V2ProviderExecutor.execute

    def waiting_video(
        self: V2ProviderExecutor,
        workflow_obj: object,
        item: object,
        slot: object,
        plan: object,
    ) -> V2ProviderResult:
        if getattr(slot, "slot_id", "") == "shot-1:shot_video_segment":
            return V2ProviderResult(
                status="waiting",
                media_type="video",
                remote_task_id="remote-rate-limited-video",
                provider="fake-video-provider",
                provider_model="fake-video-model",
                provider_payload_snapshot={"provider_prompt": "waiting video"},
                metadata={"waiting_reason": "remote_video_running"},
            )
        return original_execute(self, workflow_obj, item, slot, plan)

    monkeypatch.setattr(V2ProviderExecutor, "execute", waiting_video)
    run_response = service.run_workflow(workflow.workflow_id, wait=True)
    assert run_response.status == "waiting"
    task_store = V2ProviderTaskService(v2_media_data_dir)
    task = task_store.list_nonterminal_tasks(workflow.workflow_id)[0]
    task_store.save_task(task.model_copy(update={"next_poll_at": "2000-01-01T00:00:00+00:00"}))

    def rate_limited_poll(self: V2ProviderExecutor, provider_task: object) -> V2ProviderResult:
        del self
        return V2ProviderResult(
            status="failed",
            media_type="video",
            remote_task_id=str(getattr(provider_task, "remote_task_id")),
            provider="fake-video-provider",
            provider_model="fake-video-model",
            provider_payload_snapshot={"provider_prompt": "waiting video"},
            error_code="provider_rate_limited",
            error_message="rate limited",
        )

    monkeypatch.setattr(V2ProviderExecutor, "poll_task", rate_limited_poll)

    poll_result = service.poll_due_provider_tasks(workflow.workflow_id)

    assert poll_result.waiting_task_ids == [task.task_id]
    updated_task = task_store.load_task(workflow.workflow_id, task.task_id)
    assert updated_task is not None
    assert updated_task.status == "waiting"
    assert updated_task.attempt_count == 1
    assert updated_task.next_poll_at is not None
    latest = service.get_workflow(workflow.workflow_id)
    shot_video = find_v2_slot(latest, "shot-1:shot_video_segment")
    assert not isinstance(shot_video, dict)
    assert shot_video.status == "waiting"
    cooldowns = latest.metadata["provider_cooldowns"]
    assert cooldowns["video"]["reason"] == "provider_rate_limited"
    assert (
        cooldowns["video"]["reduced_parallel_jobs"]
        == settings.v2_provider_rate_limit_reduced_video_jobs
    )


def test_v2_parallel_scheduler_settings_read_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_MAX_PARALLEL_IMAGE_JOBS", "2")
    monkeypatch.setenv("V2_MAX_PARALLEL_VIDEO_JOBS", "1")
    monkeypatch.setenv("V2_MAX_PARALLEL_AUDIO_JOBS", "1")
    monkeypatch.setenv("V2_MAX_PARALLEL_GENERATION_JOBS", "3")
    monkeypatch.setenv("V2_PROVIDER_TASK_POLL_INTERVAL_SECONDS", "4")
    monkeypatch.setenv("V2_PROVIDER_TASK_MAX_CONCURRENT_POLLS", "1")
    monkeypatch.setenv("V2_PROVIDER_TASK_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("V2_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS", "12")
    monkeypatch.setenv("V2_PROVIDER_RATE_LIMIT_REDUCED_IMAGE_JOBS", "1")
    monkeypatch.setenv("V2_PROVIDER_RATE_LIMIT_REDUCED_VIDEO_JOBS", "1")

    settings = Settings.from_env()

    assert settings.v2_max_parallel_image_jobs == 2
    assert settings.v2_max_parallel_video_jobs == 1
    assert settings.v2_max_parallel_audio_jobs == 1
    assert settings.v2_max_parallel_generation_jobs == 3
    assert settings.v2_provider_task_poll_interval_seconds == 4
    assert settings.v2_provider_task_max_concurrent_polls == 1
    assert settings.v2_provider_task_timeout_seconds == 99
    assert settings.v2_provider_rate_limit_cooldown_seconds == 12
    assert settings.v2_provider_rate_limit_reduced_image_jobs == 1
    assert settings.v2_provider_rate_limit_reduced_video_jobs == 1


def _add_character_item(workflow: Any, *, item_id: str) -> None:
    character_node = next(node for node in workflow.nodes if node.node_id == "character-generation")
    character_node.items.append(
        WorkflowItemV2(
            item_id=item_id,
            node_id="character-generation",
            item_type="character",
            display_name=item_id,
            description=f"{item_id} test character.",
            item_prompt=f"{item_id} prompt.",
            status="empty",
            slots=[
                build_slot(
                    node_id="character-generation",
                    item_id=item_id,
                    slot_type="character_main_image",
                    media_type="image",
                    status="empty",
                    prompt=f"{item_id} main image.",
                ),
                build_slot(
                    node_id="character-generation",
                    item_id=item_id,
                    slot_type="character_three_view",
                    media_type="image",
                    status="blocked",
                    prompt=f"{item_id} three view.",
                    dependency_slot_ids=[f"{item_id}:character_main_image"],
                ),
            ],
        )
    )


def _add_scene_item(workflow: Any, *, item_id: str) -> None:
    scene_node = next(node for node in workflow.nodes if node.node_id == "scene-generation")
    scene_node.items.append(
        WorkflowItemV2(
            item_id=item_id,
            node_id="scene-generation",
            item_type="scene",
            display_name=item_id,
            description=f"{item_id} test scene.",
            item_prompt=f"{item_id} prompt.",
            status="empty",
            slots=[
                build_slot(
                    node_id="scene-generation",
                    item_id=item_id,
                    slot_type="scene_main_image",
                    media_type="image",
                    status="empty",
                    prompt=f"{item_id} main image.",
                ),
                build_slot(
                    node_id="scene-generation",
                    item_id=item_id,
                    slot_type="scene_multi_view_grid",
                    media_type="image",
                    status="blocked",
                    prompt=f"{item_id} multi-view image.",
                    dependency_slot_ids=[f"{item_id}:scene_main_image"],
                ),
            ],
        )
    )


def _skip_non_main_generation_slots(workflow: Any) -> None:
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_type in {
                    "product_main_image",
                    "character_main_image",
                    "scene_main_image",
                }:
                    continue
                slot.required = False
                slot.status = "skipped"


def _skip_slots(workflow: Any, slot_ids: set[str]) -> None:
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id in slot_ids:
                    slot.required = False
                    slot.status = "skipped"


def _skip_slots_except(workflow: Any, retained_slot_ids: set[str]) -> None:
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id not in retained_slot_ids:
                    slot.required = False
                    slot.status = "skipped"


def _wait_for_terminal_runtime(
    service: WorkflowV2Service,
    workflow_id: str,
    *,
    timeout: float = 10.0,
) -> WorkflowV2RuntimeSnapshot:
    deadline = time.monotonic() + timeout
    last_snapshot: WorkflowV2RuntimeSnapshot | None = None
    while time.monotonic() < deadline:
        last_snapshot = service.runtime_snapshot(workflow_id)
        if last_snapshot.active_execution_id is None:
            return last_snapshot
        time.sleep(0.05)
    raise AssertionError(f"execution did not finish: {last_snapshot}")
