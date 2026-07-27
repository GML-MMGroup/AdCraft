from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2ProviderResult,
    V2ProviderTask,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_provider_results import (
    V2ProviderExecutionContext,
    V2ProviderOutputDescriptor,
    V2ProviderResultManifest,
)
from app.services.v2_provider_result_store import (
    V2ProviderResultStore,
    V2ProviderResultStoreError,
    slot_key,
)
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_final_composition_publication import (
    V2FinalCompositionPublicationService,
)
from app.services.v2_final_composition_render_service import (
    V2FinalCompositionRenderService,
)
from app.services.v2_event_store import V2EventStore
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_provider_executor import V2_PROMPT_SOURCE_CONTRACT, V2ProviderExecutor
from app.services.v2_provider_tasks import V2ProviderTaskStore
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime
from app.services.workflow_v2 import _SchedulerRunResult, WorkflowV2Error, WorkflowV2Service
from tests.helpers.v2_factories import (
    add_selected_asset_to_slot,
    find_v2_slot,
    make_v2_workflow,
    persist_v2_workflow_operational,
    persist_v2_workflow_semantic,
)

_FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomfinal"


def _final_publication_context(
    data_dir: Path,
    *,
    suffix: str,
) -> tuple[
    Settings,
    V2FinalCompositionPublicationService,
    WorkflowV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    Path,
    str,
    dict[str, Any],
]:
    workflow = make_v2_workflow(
        data_dir,
        workflow_id=f"wf_v2_final_recovery_{suffix}",
        audio_mode="none",
    )
    slot = find_v2_slot(workflow, "final-composition-1:final_video")
    assert isinstance(slot, WorkflowSlotV2)
    item = next(
        candidate
        for node in workflow.nodes
        for candidate in node.items
        if candidate.item_id == slot.item_id
    )
    source = (
        data_dir
        / "v2"
        / "runs"
        / workflow.workflow_id
        / "composition"
        / f"render_{suffix}"
        / "final-ad-video.mp4.part"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(_FAKE_MP4)
    settings = Settings(
        agent_runtime_mode="fake",
        media_mode="mock",
        media_data_dir=data_dir,
    )
    fingerprint = (
        "sha256:"
        + {
            "manifest": "b",
            "asset": "c",
            "relation": "d",
            "manifest_commit": "e",
        }[suffix]
        * 64
    )
    payload = {
        "contract": "v2-final-composition-fingerprint-v1",
        "workflow_id": workflow.workflow_id,
        "slot_id": slot.slot_id,
        "render_mode": "simple_sequence",
        "visual_sources": [],
        "audio_sources": [],
        "audio_mode": "none",
        "audio_mix": {},
        "output": {"width": 1280, "height": 720, "fps": 24},
        "renderer": {
            "contract_version": "final-composition-renderer-v1",
            "toolchain_fingerprint": "sha256:test",
        },
    }
    return (
        settings,
        V2FinalCompositionPublicationService(settings),
        workflow,
        item,
        slot,
        source,
        fingerprint,
        payload,
    )


def test_completed_provider_task_persists_pending_manifest_before_canonical_commit(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_async_manifest")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    task = V2ProviderTask(
        task_id="task_async_manifest",
        workflow_id=workflow.workflow_id,
        execution_id="exec_async_manifest",
        node_id=slot.node_id,
        item_id=item.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_async_manifest",
        version_id="ver_async_manifest",
        provider="test-provider",
        provider_model="test-model",
        remote_task_id="remote_async_manifest",
        status="submitted",
        submitted_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "attempt_id": "attempt_async_manifest",
            "input_fingerprint": "async-input-fingerprint",
            "source_action": "global_run",
            "select_generated": True,
        },
    )
    result = V2ProviderResult(
        status="completed",
        media_type="image",
        asset_bytes=b"\x89PNG\r\n\x1a\nasync-provider-output",
        remote_task_id=task.remote_task_id,
        provider=task.provider,
        provider_model=task.provider_model,
        provider_payload_snapshot={"provider_prompt": "product asset"},
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))

    manifest = service._persist_completed_provider_task_manifest(
        workflow,
        item,
        slot,
        task,
        result,
    )

    assert manifest.commit_status == "pending"
    assert manifest.provider_result_metadata["provider_task_id"] == task.task_id
    assert manifest.provider_result_metadata["remote_task_id"] == task.remote_task_id
    assert (
        V2ProviderResultStore(data_dir).load_manifest(
            workflow_id=workflow.workflow_id,
            execution_id=task.execution_id,
            slot_id=slot.slot_id,
            attempt_id="attempt_async_manifest",
        )
        == manifest
    )


def test_final_composition_pending_publication_recovers_without_rendering_again(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="wf_v2_final_publication_recovery",
        audio_mode="none",
    )
    slot = find_v2_slot(workflow, "final-composition-1:final_video")
    assert not isinstance(slot, dict)
    item = next(
        candidate
        for node in workflow.nodes
        for candidate in node.items
        if candidate.item_id == slot.item_id
    )
    source = (
        v2_media_data_dir
        / "v2"
        / "runs"
        / workflow.workflow_id
        / "composition"
        / "render-recovery"
        / "final-ad-video.mp4"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(_FAKE_MP4)
    settings = Settings(
        agent_runtime_mode="fake",
        media_mode="mock",
        media_data_dir=v2_media_data_dir,
    )
    asset_store = V2AssetStoreService(v2_media_data_dir)
    publication = V2FinalCompositionPublicationService(
        settings,
        asset_store=asset_store,
    )
    fingerprint = "sha256:" + "a" * 64
    payload = {
        "contract": "v2-final-composition-fingerprint-v1",
        "workflow_id": workflow.workflow_id,
        "slot_id": slot.slot_id,
        "render_mode": "simple_sequence",
        "visual_sources": [],
        "audio_sources": [],
        "audio_mode": "none",
        "audio_mix": {},
        "output": {"width": 1280, "height": 720, "fps": 24},
        "renderer": {
            "contract_version": "final-composition-renderer-v1",
            "toolchain_fingerprint": "sha256:test",
        },
    }
    original_save = asset_store.save_asset_version
    save_calls = 0

    def fail_once(record: WorkflowAssetVersionV2) -> WorkflowAssetVersionV2:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            raise RuntimeError("injected interruption after canonical publication")
        return original_save(record)

    monkeypatch.setattr(asset_store, "save_asset_version", fail_once)
    with pytest.raises(RuntimeError, match="injected interruption"):
        publication.publish(
            workflow=workflow,
            item=item,
            slot=slot,
            source_path=source,
            composition_fingerprint=fingerprint,
            fingerprint_payload=payload,
            fingerprint_contract_version="v2-final-composition-fingerprint-v1",
            source_action="editor_export",
            select_result=True,
            source_render_id="render_recovery",
            provider_payload={
                "composition_fingerprint": fingerprint,
                "composition_fingerprint_payload": payload,
                "fingerprint_contract_version": "v2-final-composition-fingerprint-v1",
            },
            result_metadata={"render_mode": "simple_sequence"},
            reference_asset_ids=[],
        )
    manifests = V2ProviderResultStore(v2_media_data_dir).list_manifests(
        workflow_id=workflow.workflow_id
    )
    assert len(manifests) == 1
    assert manifests[0].commit_status == "pending"

    monkeypatch.setattr(asset_store, "save_asset_version", original_save)
    V2FinalCompositionRenderService(settings).recover_interrupted_renders(workflow.workflow_id)

    committed = V2ProviderResultStore(v2_media_data_dir).list_manifests(
        workflow_id=workflow.workflow_id
    )
    assert committed[0].commit_status == "committed"
    recovered_workflow = create_workflow_authoring_runtime(v2_media_data_dir).read_model.assemble(
        workflow.workflow_id
    )
    recovered_slot = find_v2_slot(
        recovered_workflow,
        "final-composition-1:final_video",
    )
    assert not isinstance(recovered_slot, dict)
    assert committed[0].canonical_asset_ids == [recovered_slot.selected_asset_id]
    assert committed[0].canonical_version_ids == [recovered_slot.selected_version_id]
    assert save_calls == 1


@pytest.mark.parametrize("failure_stage", ["manifest", "asset", "relation", "manifest_commit"])
def test_final_composition_publication_recovery_converges_across_commit_boundaries(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    (
        settings,
        publication,
        workflow,
        item,
        slot,
        source,
        fingerprint,
        payload,
    ) = _final_publication_context(v2_media_data_dir, suffix=failure_stage)
    publish_kwargs = {
        "workflow": workflow,
        "item": item,
        "slot": slot,
        "source_path": source,
        "composition_fingerprint": fingerprint,
        "fingerprint_payload": payload,
        "fingerprint_contract_version": "v2-final-composition-fingerprint-v1",
        "source_action": "editor_export",
        "select_result": True,
        "source_render_id": f"render_{failure_stage}",
        "provider_payload": {
            "composition_fingerprint": fingerprint,
            "composition_fingerprint_payload": payload,
            "fingerprint_contract_version": "v2-final-composition-fingerprint-v1",
        },
        "result_metadata": {"render_mode": "simple_sequence"},
        "reference_asset_ids": [],
    }
    if failure_stage == "manifest":
        publication._ensure_editor_manifest(
            workflow=workflow,
            item=item,
            slot=slot,
            source_path=source,
            composition_fingerprint=fingerprint,
            source_render_id="render_manifest",
            source_action="editor_export",
            select_result=True,
            provider_payload=publish_kwargs["provider_payload"],
            result_metadata=publish_kwargs["result_metadata"],
            reference_asset_ids=[],
        )
    elif failure_stage == "asset":
        original_save = publication._asset_store.save_asset_version

        def interrupt_asset_save(
            record: WorkflowAssetVersionV2,
        ) -> WorkflowAssetVersionV2:
            monkeypatch.setattr(publication._asset_store, "save_asset_version", original_save)
            raise RuntimeError("injected asset save interruption")

        monkeypatch.setattr(
            publication._asset_store,
            "save_asset_version",
            interrupt_asset_save,
        )
        with pytest.raises(RuntimeError, match="asset save interruption"):
            publication.publish(**publish_kwargs)
    else:
        record = publication.publish(**publish_kwargs)
        if failure_stage == "relation":
            original_create_relation = publication._asset_store.create_relation

            def interrupt_relation(**kwargs: Any) -> Any:
                monkeypatch.setattr(
                    publication._asset_store,
                    "create_relation",
                    original_create_relation,
                )
                raise RuntimeError("injected relation interruption")

            monkeypatch.setattr(
                publication._asset_store,
                "create_relation",
                interrupt_relation,
            )
            with pytest.raises(RuntimeError, match="relation interruption"):
                publication.apply_relations(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    record=record,
                    source_action="editor_export",
                    select_result=True,
                )
        else:
            monkeypatch.setattr(
                publication,
                "_mark_editor_manifest_committed",
                lambda _record: (_ for _ in ()).throw(
                    RuntimeError("injected manifest commit interruption")
                ),
            )
            with pytest.raises(RuntimeError, match="manifest commit interruption"):
                publication.apply_relations(
                    workflow=workflow,
                    item=item,
                    slot=slot,
                    record=record,
                    source_action="editor_export",
                    select_result=True,
                )

    V2FinalCompositionRenderService(settings).recover_interrupted_renders(workflow.workflow_id)

    manifests = V2ProviderResultStore(v2_media_data_dir).list_manifests(
        workflow_id=workflow.workflow_id
    )
    assert len(manifests) == 1
    assert manifests[0].commit_status == "committed"
    recovered_workflow = create_workflow_authoring_runtime(v2_media_data_dir).read_model.assemble(
        workflow.workflow_id
    )
    recovered_slot = find_v2_slot(
        recovered_workflow,
        "final-composition-1:final_video",
    )
    assert isinstance(recovered_slot, WorkflowSlotV2)
    assert recovered_slot.selected_asset_id == manifests[0].canonical_asset_ids[0]
    assert recovered_slot.selected_version_id == manifests[0].canonical_version_ids[0]
    versions = V2AssetStoreService(v2_media_data_dir).list_asset_versions_for_slot(
        workflow_id=workflow.workflow_id,
        slot_id=slot.slot_id,
    )
    assert len(versions) == 1


def test_completed_provider_task_without_retrievable_output_has_typed_recovery_error(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_async_output_unavailable")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    task = V2ProviderTask(
        task_id="task_output_unavailable",
        workflow_id=workflow.workflow_id,
        execution_id="exec_output_unavailable",
        node_id=slot.node_id,
        item_id=item.item_id,
        slot_id=slot.slot_id,
        asset_id="asset_output_unavailable",
        version_id="ver_output_unavailable",
        provider="test-provider",
        remote_task_id="remote_output_unavailable",
        status="submitted",
        submitted_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "attempt_id": "attempt_output_unavailable",
            "input_fingerprint": "output-unavailable-fingerprint",
        },
    )
    result = V2ProviderResult(
        status="completed",
        media_type="image",
        provider=task.provider,
        remote_task_id=task.remote_task_id,
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))

    with pytest.raises(WorkflowV2Error) as exc_info:
        service._persist_completed_provider_task_manifest(
            workflow,
            item,
            slot,
            task,
            result,
        )

    assert exc_info.value.code == "v2_provider_result_recovery_unavailable"


def test_provider_completion_and_recovery_preserve_concurrent_slot_transitions(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_recovery_provider_race")
    product_slot = find_v2_slot(workflow, "product-1:product_main_image")
    character_slot = find_v2_slot(workflow, "character-1:character_main_image")
    assert not isinstance(product_slot, dict)
    assert not isinstance(character_slot, dict)
    product_asset_id, product_version_id = add_selected_asset_to_slot(
        data_dir,
        workflow,
        product_slot.slot_id,
    )
    product_slot.status = "running"
    character_slot.status = "waiting"
    persist_v2_workflow_operational(workflow, data_dir)
    execution_id = "exec_recovery_provider_race"
    executions = V2ExecutionService(data_dir)
    executions.save_state(
        workflow.workflow_id,
        execution_id,
        {
            "workflow_id": workflow.workflow_id,
            "execution_id": execution_id,
            "mode": "fill_missing_required_slots",
            "source_action": "global_run",
            "status": "running",
            "target_slot_ids": [product_slot.slot_id, character_slot.slot_id],
            "running_slot_ids": [product_slot.slot_id],
            "waiting_slot_ids": [character_slot.slot_id],
            "completed_slot_ids": [],
            "failed_slot_ids": [],
            "slot_runtime": {
                product_slot.slot_id: {
                    "slot_id": product_slot.slot_id,
                    "node_id": product_slot.node_id,
                    "item_id": product_slot.item_id,
                    "slot_type": product_slot.slot_type,
                    "media_type": product_slot.media_type,
                    "status": "running",
                    "runtime_status": "running",
                    "updated_at": "2000-01-01T00:00:00+00:00",
                },
                character_slot.slot_id: {
                    "slot_id": character_slot.slot_id,
                    "node_id": character_slot.node_id,
                    "item_id": character_slot.item_id,
                    "slot_type": character_slot.slot_type,
                    "media_type": character_slot.media_type,
                    "status": "waiting",
                    "runtime_status": "waiting",
                    "updated_at": "2000-01-01T00:00:00+00:00",
                },
            },
            "events_cursor": 0,
            "metadata": {},
        },
    )
    executions.set_active(workflow.workflow_id, execution_id)
    character_item = next(
        item
        for node in workflow.nodes
        if node.node_id == "character-generation"
        for item in node.items
        if item.item_id == "character-1"
    )
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_data_dir=data_dir,
            v2_stale_running_timeout_seconds=0,
        )
    )
    plan = service._generation_pipeline.build_plan(
        workflow,
        character_item,
        character_slot,
        source_action="global_run",
    )
    task = V2ProviderTask(
        task_id="task_recovery_provider_race",
        workflow_id=workflow.workflow_id,
        execution_id=execution_id,
        node_id=character_slot.node_id,
        item_id=character_slot.item_id,
        slot_id=character_slot.slot_id,
        asset_id="asset_recovery_provider_race",
        version_id="ver_recovery_provider_race",
        provider="test-provider",
        provider_model="test-model",
        remote_task_id="remote_recovery_provider_race",
        status="submitted",
        submitted_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        provider_payload_snapshot=plan.provider_payload,
        metadata={
            "attempt_id": "attempt_recovery_provider_race",
            "input_fingerprint": service._generation_pipeline.input_fingerprint(
                workflow,
                character_item,
                character_slot,
            ),
            "generation_plan_snapshot": plan.model_dump(mode="json"),
            "source_action": "global_run",
            "select_generated": True,
        },
    )
    V2ProviderTaskStore(data_dir).save_task(task)
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def completed_result(_task: V2ProviderTask) -> V2ProviderResult:
        start.wait(timeout=2)
        return V2ProviderResult(
            status="completed",
            media_type="image",
            asset_bytes=b"\x89PNG\r\n\x1a\nprovider-race-output",
            provider="test-provider",
            provider_model="test-model",
            remote_task_id=task.remote_task_id,
            provider_payload_snapshot=plan.provider_payload,
            metadata={
                "prompt_audit": {
                    "prompt_match": True,
                    "prompt_source_contract": V2_PROMPT_SOURCE_CONTRACT,
                    "legacy_prompt_fields_used": [],
                }
            },
        )

    def no_scheduler_resume(*_args: object, **_kwargs: object) -> _SchedulerRunResult:
        return _SchedulerRunResult()

    monkeypatch.setattr(service._generation_pipeline, "poll_provider_task", completed_result)
    monkeypatch.setattr(
        service,
        "_resume_missing_slot_scheduler_after_provider_task",
        no_scheduler_resume,
    )

    def recover() -> None:
        try:
            start.wait(timeout=2)
            service._execution_recovery.recover_interrupted_execution(
                workflow.workflow_id,
                trigger="explicit_resume",
            )
        except BaseException as exc:  # noqa: BLE001 - thread errors are test evidence.
            errors.append(exc)

    def poll() -> None:
        try:
            service.poll_provider_task(workflow.workflow_id, task.task_id)
        except BaseException as exc:  # noqa: BLE001 - thread errors are test evidence.
            errors.append(exc)

    recovery_thread = threading.Thread(target=recover)
    provider_thread = threading.Thread(target=poll)
    recovery_thread.start()
    provider_thread.start()
    recovery_thread.join(timeout=5)
    provider_thread.join(timeout=5)

    assert not recovery_thread.is_alive()
    assert not provider_thread.is_alive()
    assert errors == []
    latest = service.get_workflow(workflow.workflow_id)
    latest_product_slot = find_v2_slot(latest, product_slot.slot_id)
    latest_character_slot = find_v2_slot(latest, character_slot.slot_id)
    assert not isinstance(latest_product_slot, dict)
    assert not isinstance(latest_character_slot, dict)
    assert latest_product_slot.status == "completed"
    assert latest_product_slot.selected_asset_id == product_asset_id
    assert latest_product_slot.selected_version_id == product_version_id
    assert latest_character_slot.status == "completed"
    assert latest_character_slot.selected_asset_id
    assert latest_character_slot.selected_version_id
    state = executions.load_state(workflow.workflow_id, execution_id)
    assert state is not None
    assert state["running_slot_ids"] == []
    assert state["waiting_slot_ids"] == []
    assert set(state["completed_slot_ids"]) >= {
        product_slot.slot_id,
        character_slot.slot_id,
    }


def test_provider_result_store_persists_success_atomically(tmp_path: Path) -> None:
    """A provider result must be durable before a worker can report success."""
    data_dir = tmp_path / "data"
    staging_path = data_dir / "assets" / "generated-provider" / "workflow-1" / "output.png"
    staging_path.parent.mkdir(parents=True)
    staging_path.write_bytes(b"\x89PNG\r\n\x1a\nprovider-image-output")
    context = V2ProviderExecutionContext(
        workflow_id="workflow-1",
        execution_id="exec-1",
        attempt_id="attempt-1",
        node_id="character-generation",
        item_id="character-1",
        slot_id="character-1:character_three_view",
        slot_type="character_three_view",
        media_type="image",
        input_fingerprint="fingerprint-1",
        source_action="global_run",
    )

    manifest = V2ProviderResultStore(data_dir).persist_immediate_result(
        context=context,
        provider_name="deterministic-provider",
        provider_model="deterministic-model",
        staging_path=staging_path,
        generation_plan_snapshot={"target": {"slot_id": context.slot_id}},
        provider_payload_snapshot={"provider_prompt": "single subject prompt"},
        provider_result_metadata={"provider_asset_id": "provider-asset-1"},
        reference_asset_ids=["asset_reference_1"],
    )

    assert manifest.provider_status == "succeeded"
    assert manifest.commit_status == "pending"
    assert manifest.outputs[0].is_primary is True
    assert manifest.slot_key == slot_key(context.slot_id)
    assert (
        V2ProviderResultStore(data_dir).load_manifest(
            workflow_id=context.workflow_id,
            execution_id=context.execution_id,
            slot_id=context.slot_id,
            attempt_id=context.attempt_id,
        )
        == manifest
    )


def test_provider_result_store_hashes_colon_slot_id() -> None:
    assert slot_key("shot-1:shot_cell_4") == "c2fc024001753cb1ee8fccc7"


def test_provider_result_store_rejects_path_traversal(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    escaping_output = tmp_path / "outside.png"
    escaping_output.write_bytes(b"\x89PNG\r\n\x1a\nescaping")

    with pytest.raises(V2ProviderResultStoreError) as exc_info:
        V2ProviderResultStore(data_dir).persist_immediate_result(
            context=_context(),
            provider_name="deterministic-provider",
            provider_model=None,
            staging_path=escaping_output,
            generation_plan_snapshot={},
            provider_payload_snapshot={},
            provider_result_metadata={},
            reference_asset_ids=[],
        )

    assert exc_info.value.code == "v2_provider_result_manifest_invalid"


def test_provider_result_store_requires_exactly_one_primary_output(tmp_path: Path) -> None:
    context = _context()
    now = datetime.now(timezone.utc)
    manifest = V2ProviderResultManifest(
        provider_result_id="presult_test",
        workflow_id=context.workflow_id,
        execution_id=context.execution_id,
        attempt_id=context.attempt_id,
        node_id=context.node_id,
        item_id=context.item_id,
        slot_id=context.slot_id,
        slot_key=slot_key(context.slot_id),
        slot_type=context.slot_type,
        media_type=context.media_type,
        input_fingerprint=context.input_fingerprint,
        provider_name="deterministic-provider",
        source_action=context.source_action,
        select_generated=True,
        provider_status="succeeded",
        commit_status="pending",
        outputs=[
            V2ProviderOutputDescriptor(
                output_index=0,
                is_primary=False,
                staging_path="assets/generated-provider/workflow-1/output.png",
                media_type="image",
                mime_type="image/png",
                byte_size=1,
                sha256="a" * 64,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(V2ProviderResultStoreError) as exc_info:
        V2ProviderResultStore(tmp_path / "data").create_manifest(manifest)

    assert exc_info.value.code == "v2_provider_result_manifest_invalid"


def test_provider_result_store_rejects_missing_output(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    missing_output = data_dir / "assets" / "generated-provider" / "workflow-1" / "missing.png"

    with pytest.raises(V2ProviderResultStoreError) as exc_info:
        V2ProviderResultStore(data_dir).persist_immediate_result(
            context=_context(),
            provider_name="deterministic-provider",
            provider_model=None,
            staging_path=missing_output,
            generation_plan_snapshot={},
            provider_payload_snapshot={},
            provider_result_metadata={},
            reference_asset_ids=[],
        )

    assert exc_info.value.code == "v2_provider_result_output_missing"


def test_provider_result_manifest_strips_bytes_base64_and_secrets(tmp_path: Path) -> None:
    data_dir, staging_path = _staging_output(tmp_path)

    manifest = V2ProviderResultStore(data_dir).persist_immediate_result(
        context=_context(),
        provider_name="deterministic-provider",
        provider_model=None,
        staging_path=staging_path,
        generation_plan_snapshot={"raw_bytes": b"not-persisted", "target": {"slot_id": "slot"}},
        provider_payload_snapshot={
            "authorization": "Bearer secret",
            "image_base64": "data:image/png;base64,AAAA",
            "reference_url": "https://provider.example/output.png?signature=secret",
        },
        provider_result_metadata={"api_key": "secret-key"},
        reference_asset_ids=[],
    )

    serialized = manifest.model_dump_json()
    assert "Bearer secret" not in serialized
    assert "secret-key" not in serialized
    assert "data:image/png;base64" not in serialized
    assert "?signature=" not in serialized
    assert manifest.generation_plan_snapshot["raw_bytes"] == "[omitted]"


def test_provider_result_manifest_round_trips_restart_metadata(tmp_path: Path) -> None:
    data_dir, staging_path = _staging_output(tmp_path)
    context = _context()
    store = V2ProviderResultStore(data_dir)

    manifest = store.persist_immediate_result(
        context=context,
        provider_name="deterministic-provider",
        provider_model="deterministic-model",
        staging_path=staging_path,
        generation_plan_snapshot={"target": {"slot_id": context.slot_id}},
        provider_payload_snapshot={"provider_prompt": "single subject prompt"},
        provider_result_metadata={"provider_asset_id": "provider-asset-1"},
        reference_asset_ids=["asset_reference_1"],
    )

    loaded = store.load_manifest(
        workflow_id=context.workflow_id,
        execution_id=context.execution_id,
        slot_id=context.slot_id,
        attempt_id=context.attempt_id,
    )

    assert loaded == manifest
    assert loaded is not None
    assert loaded.generation_plan_snapshot["target"]["slot_id"] == context.slot_id
    assert loaded.provider_payload_snapshot["provider_prompt"] == "single subject prompt"
    assert loaded.reference_asset_ids == ["asset_reference_1"]


def test_provider_result_store_rejects_noncanonical_result_identity(tmp_path: Path) -> None:
    data_dir, staging_path = _staging_output(tmp_path)
    store = V2ProviderResultStore(data_dir)
    manifest = store.persist_immediate_result(
        context=_context(),
        provider_name="deterministic-provider",
        provider_model=None,
        staging_path=staging_path,
        generation_plan_snapshot={},
        provider_payload_snapshot={},
        provider_result_metadata={},
        reference_asset_ids=[],
    )

    with pytest.raises(V2ProviderResultStoreError) as exc_info:
        store.update_manifest(manifest.model_copy(update={"provider_result_id": "presult_wrong"}))

    assert exc_info.value.code == "v2_provider_result_manifest_invalid"


def test_worker_persists_manifest_before_future_returns(v2_media_data_dir: Path) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_worker_manifest")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    worker_events: list[dict[str, object]] = []

    def append_worker_event(
        workflow_id: str,
        event_type: str,
        **kwargs: object,
    ) -> None:
        worker_events.append(
            {
                "workflow_id": workflow_id,
                "event_type": event_type,
                **kwargs,
            }
        )

    result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_worker_manifest",
        append_worker_event=append_worker_event,
    )

    assert result.status == "completed"
    assert result.job.attempt_id
    assert result.provider_result_id
    assert result.manifest_path
    manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_worker_manifest",
        slot_id=slot.slot_id,
        attempt_id=result.job.attempt_id,
    )
    assert manifest is not None
    assert manifest.provider_result_id == result.provider_result_id
    assert manifest.commit_status == "pending"
    assert service._asset_store.find_asset_version(slot_id=slot.slot_id) is None
    assert worker_events == [
        {
            "workflow_id": workflow.workflow_id,
            "event_type": "provider_result_persisted",
            "execution_id": "exec_worker_manifest",
            "node_id": slot.node_id,
            "item_id": item.item_id,
            "slot_id": slot.slot_id,
            "payload": {
                "attempt_id": result.job.attempt_id,
                "provider_result_id": result.provider_result_id,
                "status": "pending",
            },
        }
    ]


def test_provider_result_committer_rejects_digest_mismatch(v2_media_data_dir: Path) -> None:
    from app.services.v2_provider_result_committer import (
        V2ProviderResultCommitError,
        V2ProviderResultCommitter,
    )

    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_digest_rejection")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_digest_rejection",
    )
    manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_digest_rejection",
        slot_id=slot.slot_id,
        attempt_id=str(result.job.attempt_id),
    )
    assert manifest is not None
    (data_dir / manifest.outputs[0].staging_path).write_bytes(b"\x89PNG\r\n\x1a\ntampered")

    with pytest.raises(V2ProviderResultCommitError) as exc_info:
        V2ProviderResultCommitter(data_dir).validate_manifest(
            workflow=workflow,
            item=item,
            slot=slot,
            manifest=manifest,
            expected_input_fingerprint=str(result.job.input_fingerprint),
        )

    assert exc_info.value.code == "v2_provider_result_digest_mismatch"


def test_provider_result_committer_rejects_mismatched_output_media_type(
    v2_media_data_dir: Path,
) -> None:
    from app.services.v2_provider_result_committer import (
        V2ProviderResultCommitError,
        V2ProviderResultCommitter,
    )

    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_media_type_rejection")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_media_type_rejection",
    )
    store = V2ProviderResultStore(data_dir)
    manifest = store.load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_media_type_rejection",
        slot_id=slot.slot_id,
        attempt_id=str(result.job.attempt_id),
    )
    assert manifest is not None
    invalid_manifest = manifest.model_copy(
        update={
            "outputs": [
                manifest.outputs[0].model_copy(
                    update={"media_type": "video", "mime_type": "video/mp4"}
                )
            ]
        }
    )
    store.update_manifest(invalid_manifest)

    with pytest.raises(V2ProviderResultCommitError) as exc_info:
        V2ProviderResultCommitter(data_dir).validate_manifest(
            workflow=workflow,
            item=item,
            slot=slot,
            manifest=invalid_manifest,
            expected_input_fingerprint=str(result.job.input_fingerprint),
        )

    assert exc_info.value.code == "v2_provider_result_manifest_invalid"


def test_provider_result_committer_rejects_non_staging_output_path(
    v2_media_data_dir: Path,
) -> None:
    from app.services.v2_provider_result_committer import (
        V2ProviderResultCommitError,
        V2ProviderResultCommitter,
    )

    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_non_staging_rejection")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_non_staging_rejection",
    )
    store = V2ProviderResultStore(data_dir)
    manifest = store.load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_non_staging_rejection",
        slot_id=slot.slot_id,
        attempt_id=str(result.job.attempt_id),
    )
    assert manifest is not None
    non_staging_path = data_dir / "assets" / "generated" / "other.png"
    non_staging_path.parent.mkdir(parents=True, exist_ok=True)
    non_staging_path.write_bytes((data_dir / manifest.outputs[0].staging_path).read_bytes())
    invalid_manifest = manifest.model_copy(
        update={
            "outputs": [
                manifest.outputs[0].model_copy(
                    update={"staging_path": "assets/generated/other.png"}
                )
            ]
        }
    )
    store.update_manifest(invalid_manifest)

    with pytest.raises(V2ProviderResultCommitError) as exc_info:
        V2ProviderResultCommitter(data_dir).validate_manifest(
            workflow=workflow,
            item=item,
            slot=slot,
            manifest=invalid_manifest,
            expected_input_fingerprint=str(result.job.input_fingerprint),
        )

    assert exc_info.value.code == "v2_provider_result_manifest_invalid"


def test_scheduler_commits_pending_manifest_to_one_canonical_version(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_manifest_commit")
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id != "product-1:product_main_image":
                    slot.required = False
                    slot.status = "skipped"
    persist_v2_workflow_semantic(workflow, data_dir, source="structure_edit")
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))

    response = service.run_workflow(workflow.workflow_id, wait=True)

    assert response.status == "completed"
    manifests = V2ProviderResultStore(data_dir).list_manifests(
        workflow_id=workflow.workflow_id,
        execution_id=response.execution_id,
    )
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.commit_status == "committed"
    assert len(manifest.canonical_asset_ids) == 1
    assert len(manifest.canonical_version_ids) == 1
    asset = service._asset_store.load_asset_version(
        manifest.canonical_asset_ids[0],
        manifest.canonical_version_ids[0],
    )
    assert asset is not None
    assert asset.metadata["source_provider_result_id"] == manifest.provider_result_id
    assert asset.metadata["source_output_index"] == 0
    assert asset.metadata["source_execution_id"] == response.execution_id
    assert asset.metadata["source_attempt_id"] == manifest.attempt_id
    assert asset.metadata["source_input_fingerprint"] == manifest.input_fingerprint


def test_recovery_commits_pending_manifest_without_provider_retry(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_manifest_recovery")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    worker_result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_manifest_recovery",
    )
    assert worker_result.provider_result_id
    slot.status = "running"
    persist_v2_workflow_operational(workflow, data_dir)

    recovered_slot_ids = service._recover_pending_provider_manifests(workflow)

    assert recovered_slot_ids == [slot.slot_id]
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    assert slot.status == "completed"
    assert slot.selected_asset_id
    assert slot.selected_version_id
    manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_manifest_recovery",
        slot_id=slot.slot_id,
        attempt_id=str(worker_result.job.attempt_id),
    )
    assert manifest is not None
    assert manifest.commit_status == "committed"
    assert manifest.canonical_version_ids == [slot.selected_version_id]
    recovery_events = [
        event
        for event in V2EventStore(data_dir).list_events(workflow.workflow_id).events
        if event.event_type.startswith("provider_result_recovery_")
    ]
    assert [event.event_type for event in recovery_events] == [
        "provider_result_recovery_started",
        "provider_result_recovery_completed",
    ]
    assert {event.execution_id for event in recovery_events} == {"exec_manifest_recovery"}


def test_recovery_rejects_pending_manifest_after_slot_input_changes(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_manifest_stale_input")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    worker_result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_manifest_stale_input",
    )
    assert worker_result.job.attempt_id
    slot.slot_prompt = "A deliberately changed product prompt."
    slot.manual_prompt_dirty = True
    persist_v2_workflow_semantic(workflow, data_dir, source="prompt_edit")

    recovered_slot_ids = service._recover_pending_provider_manifests(workflow)

    assert recovered_slot_ids == []
    assert slot.selected_asset_id is None
    manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_manifest_stale_input",
        slot_id=slot.slot_id,
        attempt_id=worker_result.job.attempt_id,
    )
    assert manifest is not None
    assert manifest.commit_status == "rejected"
    assert manifest.error is not None
    assert manifest.error.code == "v2_provider_result_input_mismatch"


def test_recovery_finalizes_manifest_after_canonical_registration_interruption(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_manifest_registration_retry")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    worker_result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_manifest_registration_retry",
    )
    persist_v2_workflow_operational(workflow, data_dir)
    store = V2ProviderResultStore(data_dir)
    initial_manifest = store.load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_manifest_registration_retry",
        slot_id=slot.slot_id,
        attempt_id=str(worker_result.job.attempt_id),
    )
    assert initial_manifest is not None
    assert service._recover_pending_provider_manifests(workflow) == [slot.slot_id]
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    canonical_asset_id = slot.selected_asset_id
    canonical_version_id = slot.selected_version_id
    assert canonical_asset_id and canonical_version_id
    store.update_manifest(
        initial_manifest.model_copy(
            update={
                "commit_status": "pending",
                "canonical_asset_ids": [],
                "canonical_version_ids": [],
                "committed_at": None,
            }
        )
    )

    recovered_slot_ids = service._recover_pending_provider_manifests(workflow)

    assert recovered_slot_ids == [slot.slot_id]
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    assert slot.selected_asset_id == canonical_asset_id
    assert slot.selected_version_id == canonical_version_id
    manifest = store.load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_manifest_registration_retry",
        slot_id=slot.slot_id,
        attempt_id=str(worker_result.job.attempt_id),
    )
    assert manifest is not None
    assert manifest.commit_status == "committed"
    assert manifest.canonical_asset_ids == [canonical_asset_id]
    assert manifest.canonical_version_ids == [canonical_version_id]
    assert len(list((data_dir / "assets" / "metadata" / canonical_asset_id).glob("*.json"))) == 1


def test_recovery_does_not_overwrite_newer_selected_asset_with_pending_manifest(
    v2_media_data_dir: Path,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_manifest_newer_selection")
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    worker_result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id="exec_manifest_newer_selection",
    )
    newer_asset_id, newer_version_id = add_selected_asset_to_slot(data_dir, workflow, slot.slot_id)

    recovered_slot_ids = service._recover_pending_provider_manifests(workflow)

    assert recovered_slot_ids == []
    assert slot.selected_asset_id == newer_asset_id
    assert slot.selected_version_id == newer_version_id
    manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id="exec_manifest_newer_selection",
        slot_id=slot.slot_id,
        attempt_id=str(worker_result.job.attempt_id),
    )
    assert manifest is not None
    assert manifest.commit_status == "rejected"
    assert manifest.error is not None
    assert manifest.error.code == "v2_provider_result_input_mismatch"


def test_run_commits_pending_manifest_before_stale_slot_recovery(
    v2_media_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = v2_media_data_dir
    workflow = make_v2_workflow(data_dir, workflow_id="wf_v2_recover_manifest_before_reset")
    for node in workflow.nodes:
        for item in node.items:
            for candidate in item.slots:
                if candidate.slot_id != "product-1:product_main_image":
                    candidate.required = False
                    candidate.status = "skipped"
    slot = find_v2_slot(workflow, "product-1:product_main_image")
    assert not isinstance(slot, dict)
    item = next(
        item
        for node in workflow.nodes
        if node.node_id == "product-generation"
        for item in node.items
        if item.item_id == "product-1"
    )
    old_execution_id = "exec_pending_manifest_recovery"
    service = WorkflowV2Service(
        Settings(
            agent_runtime_mode="fake",
            media_data_dir=data_dir,
            v2_stale_running_timeout_seconds=0,
        )
    )
    worker_result = service._generation_pipeline.execute_slot_provider(
        workflow,
        item,
        slot,
        source_action="global_run",
        execution_id=old_execution_id,
    )
    assert worker_result.job.attempt_id
    slot.status = "running"
    persist_v2_workflow_operational(workflow, data_dir)
    execution_state = {
        "workflow_id": workflow.workflow_id,
        "execution_id": old_execution_id,
        "status": "running",
        "target_slot_ids": [slot.slot_id],
        "running_slot_ids": [slot.slot_id],
        "waiting_slot_ids": [],
        "completed_slot_ids": [],
        "failed_slot_ids": [],
        "slot_runtime": {
            slot.slot_id: {
                "slot_id": slot.slot_id,
                "node_id": slot.node_id,
                "item_id": slot.item_id,
                "slot_type": slot.slot_type,
                "media_type": slot.media_type,
                "status": "running",
                "runtime_status": "running",
                "updated_at": "2000-01-01T00:00:00+00:00",
            }
        },
        "metadata": {},
        "created_at": "2000-01-01T00:00:00+00:00",
        "updated_at": "2000-01-01T00:00:00+00:00",
    }
    executions = V2ExecutionService(data_dir)
    executions.save_state(workflow.workflow_id, old_execution_id, execution_state)
    executions.set_active(workflow.workflow_id, old_execution_id)

    def unexpected_provider_call(*_args: object, **_kwargs: object) -> V2ProviderResult:
        raise AssertionError("pending manifest recovery must not regenerate the slot")

    monkeypatch.setattr(V2ProviderExecutor, "execute", unexpected_provider_call)

    response = service.run_workflow(workflow.workflow_id, wait=True)
    active_state = executions.load_state(workflow.workflow_id, old_execution_id)
    persisted_manifest = V2ProviderResultStore(data_dir).load_manifest(
        workflow_id=workflow.workflow_id,
        execution_id=old_execution_id,
        slot_id=slot.slot_id,
        attempt_id=worker_result.job.attempt_id,
    )

    assert active_state is not None
    assert active_state["status"] == "completed"
    assert persisted_manifest is not None
    assert persisted_manifest.commit_status == "committed"
    assert response.status == "completed"
    latest = service.get_workflow(workflow.workflow_id)
    latest_slot = find_v2_slot(latest, slot.slot_id)
    assert not isinstance(latest_slot, dict)
    assert latest_slot.status == "completed"
    assert latest_slot.selected_asset_id
    events = V2EventStore(data_dir).list_events(workflow.workflow_id).events
    assert "slot_recovered_ready" not in [event.event_type for event in events]


def _context() -> V2ProviderExecutionContext:
    return V2ProviderExecutionContext(
        workflow_id="workflow-1",
        execution_id="exec-1",
        attempt_id="attempt-1",
        node_id="character-generation",
        item_id="character-1",
        slot_id="character-1:character_three_view",
        slot_type="character_three_view",
        media_type="image",
        input_fingerprint="fingerprint-1",
        source_action="global_run",
    )


def _staging_output(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    staging_path = data_dir / "assets" / "generated-provider" / "workflow-1" / "output.png"
    staging_path.parent.mkdir(parents=True)
    staging_path.write_bytes(b"\x89PNG\r\n\x1a\nprovider-image-output")
    return data_dir, staging_path
