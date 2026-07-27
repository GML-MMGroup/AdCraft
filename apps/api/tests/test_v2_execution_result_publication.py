from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.schema import upgrade_v2_schema
from app.services.v2_execution_result_publication import V2ExecutionResultPublicationService
from app.services.v2_execution_service import V2ExecutionService
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime
from app.services.workflow_v2 import WorkflowV2Service
from tests.helpers.v2_factories import make_v2_workflow


def test_workflow_v2_service_initializes_execution_result_publication(
    tmp_path: Path,
) -> None:
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    )

    publication = service._execution_result_publication

    assert callable(publication.uses_pending_publication)
    assert callable(publication.record_pending_selection)
    assert callable(publication.apply_pending_selections)
    assert callable(publication.publish_terminal)


def _created_workflow(data_dir: Path, workflow_id: str):
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    try:
        upgrade_v2_schema(database)
    finally:
        database.dispose()
    workflow = make_v2_workflow(data_dir, workflow_id=workflow_id, save=False)
    runtime = create_workflow_authoring_runtime(data_dir)
    try:
        return runtime.service.create_planned_workflow(workflow)
    finally:
        runtime.database.dispose()


def _slot_ids(workflow) -> list[str]:
    return [slot.slot_id for node in workflow.nodes for item in node.items for slot in item.slots]


def _state(data_dir: Path, workflow, execution_id: str) -> V2ExecutionService:
    executions = V2ExecutionService(data_dir)
    executions.save_state(
        workflow.workflow_id,
        execution_id,
        {
            "workflow_id": workflow.workflow_id,
            "execution_id": execution_id,
            "status": "running",
            "authoring_base_state_version": workflow.state_version,
            "authoring_base_revision_no": workflow.semantic_revision_no,
            "pending_selections": {},
        },
    )
    return executions


def test_terminal_publication_commits_all_pending_selections_once(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    workflow = _created_workflow(data_dir, "adwf_v2_publish_batch")
    execution_id = "exec_publish_batch"
    executions = _state(data_dir, workflow, execution_id)
    publisher = V2ExecutionResultPublicationService(data_dir)
    first_slot_id, second_slot_id = _slot_ids(workflow)[:2]

    publisher.record_pending_selection(
        workflow.workflow_id,
        execution_id,
        slot_id=first_slot_id,
        asset_id="asset-first",
        version_id="ver-first",
    )
    publisher.record_pending_selection(
        workflow.workflow_id,
        execution_id,
        slot_id=second_slot_id,
        asset_id="asset-second",
        version_id="ver-second",
    )

    before = create_workflow_authoring_runtime(data_dir)
    try:
        public_before = before.read_model.assemble(workflow.workflow_id)
    finally:
        before.database.dispose()
    assert all(
        slot.selected_asset_id is None
        for node in public_before.nodes
        for item in node.items
        for slot in item.slots
        if slot.slot_id in {first_slot_id, second_slot_id}
    )
    internal = publisher.apply_pending_selections(public_before, execution_id)
    assert {
        slot.slot_id: slot.selected_asset_id
        for node in internal.nodes
        for item in node.items
        for slot in item.slots
        if slot.slot_id in {first_slot_id, second_slot_id}
    } == {first_slot_id: "asset-first", second_slot_id: "asset-second"}

    published = publisher.publish_terminal(
        execution_id=execution_id, workflow_id=workflow.workflow_id
    )
    repeated = publisher.publish_terminal(
        execution_id=execution_id,
        workflow_id=workflow.workflow_id,
    )

    runtime = create_workflow_authoring_runtime(data_dir)
    try:
        current = runtime.repository.load_current(workflow.workflow_id)
        revisions = runtime.repository.list_revisions(workflow.workflow_id).items
    finally:
        runtime.database.dispose()
    selections = {
        slot.slot_id: (slot.selected_asset_id, slot.selected_version_id)
        for node in repeated.nodes
        for item in node.items
        for slot in item.slots
    }
    assert published.semantic_revision_no == 2
    assert repeated.semantic_revision_no == 2
    assert current.state_version == 2
    assert [(item.revision_no, item.source_execution_id) for item in revisions] == [
        (2, execution_id),
        (1, None),
    ]
    assert selections[first_slot_id] == ("asset-first", "ver-first")
    assert selections[second_slot_id] == ("asset-second", "ver-second")
    assert (
        executions.load_state(workflow.workflow_id, execution_id)[
            "execution_result_revision_status"
        ]
        == "published"
    )


def test_terminal_publication_defers_after_concurrent_semantic_edit(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    workflow = _created_workflow(data_dir, "adwf_v2_publish_conflict")
    execution_id = "exec_publish_conflict"
    executions = _state(data_dir, workflow, execution_id)
    publisher = V2ExecutionResultPublicationService(data_dir)
    slot_id = _slot_ids(workflow)[0]
    publisher.record_pending_selection(
        workflow.workflow_id,
        execution_id,
        slot_id=slot_id,
        asset_id="asset-candidate",
        version_id="ver-candidate",
    )

    runtime = create_workflow_authoring_runtime(data_dir)
    try:
        edited = workflow.model_copy(update={"name": "User edit during run"})
        runtime.service.commit_semantic_workflow(
            edited,
            expected_version=1,
            source="prompt_edit",
        )
    finally:
        runtime.database.dispose()

    result = publisher.publish_terminal(
        workflow_id=workflow.workflow_id,
        execution_id=execution_id,
    )
    state = executions.load_state(workflow.workflow_id, execution_id)

    assert result.name == "User edit during run"
    assert result.state_version == 2
    assert (
        next(
            slot
            for node in result.nodes
            for item in node.items
            for slot in item.slots
            if slot.slot_id == slot_id
        ).selected_asset_id
        is None
    )
    assert state["execution_result_revision_status"] == "deferred"
    assert state["pending_selections"][slot_id]["asset_id"] == "asset-candidate"


def test_terminal_publication_with_no_pending_selection_creates_no_revision(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    workflow = _created_workflow(data_dir, "adwf_v2_publish_no_change")
    execution_id = "exec_publish_no_change"
    executions = _state(data_dir, workflow, execution_id)

    result = V2ExecutionResultPublicationService(data_dir).publish_terminal(
        workflow_id=workflow.workflow_id,
        execution_id=execution_id,
    )

    assert result.semantic_revision_no == 1
    assert (
        executions.load_state(workflow.workflow_id, execution_id)[
            "execution_result_revision_status"
        ]
        == "no_change"
    )


@pytest.mark.parametrize("terminal_status", ["completed", "partial_failed"])
def test_execution_terminal_sync_publishes_overlay_and_clears_active_pointer(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    data_dir = tmp_path / "data"
    workflow = _created_workflow(data_dir, "adwf_v2_terminal_sync")
    execution_id = "exec_terminal_sync"
    service = WorkflowV2Service(Settings(agent_runtime_mode="fake", media_data_dir=data_dir))
    executions = V2ExecutionService(data_dir)
    state = service._initial_execution_state(workflow, execution_id)
    executions.save_state(workflow.workflow_id, execution_id, state)
    executions.set_active(workflow.workflow_id, execution_id)
    slot_id = _slot_ids(workflow)[0]
    candidate = workflow.model_copy(deep=True)
    slot = next(
        slot
        for node in candidate.nodes
        for item in node.items
        for slot in item.slots
        if slot.slot_id == slot_id
    )
    slot.selected_asset_id = "asset-terminal"
    slot.selected_version_id = "ver-terminal"
    service._execution_result_publication.record_pending_selection(
        workflow.workflow_id,
        execution_id,
        slot_id=slot_id,
        asset_id="asset-terminal",
        version_id="ver-terminal",
    )
    assert (
        V2AssetStoreService(data_dir).list_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot_id,
            relation_type="selected_for_slot",
        )
        == []
    )

    updated = service._sync_execution_state_from_workflow(
        candidate,
        execution_id,
        extra_completed_slot_ids=[slot_id],
        status_override=terminal_status,
    )

    current = service.get_workflow(workflow.workflow_id)
    relations = V2AssetStoreService(data_dir).list_relations(
        target_workflow_id=workflow.workflow_id,
        target_slot_id=slot_id,
        relation_type="selected_for_slot",
    )
    assert updated is not None
    assert updated["status"] == terminal_status
    assert updated["execution_result_revision_status"] == "published"
    assert current.semantic_revision_no == 2
    assert len(relations) == 1
    assert relations[0].source_asset_id == "asset-terminal"
    assert executions.load_active(workflow.workflow_id) is None
