from __future__ import annotations

import inspect
from pathlib import Path

from app.core.config import Settings
from app.persistence.workflow_authoring_repository import WorkflowAuthoringRepository
from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineService
from app.services.workflow_v2 import WorkflowV2Service
from tests.helpers.v2_factories import make_v2_workflow


def test_deployed_pi_v2_cutover_collaborators_are_present_and_wired(
    tmp_path: Path,
) -> None:
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    )

    publication = service._execution_result_publication

    assert callable(WorkflowAuthoringRepository.get_execution_result_revision)
    assert all(
        callable(getattr(publication, name, None))
        for name in (
            "uses_pending_publication",
            "record_pending_selection",
            "apply_pending_selections",
            "publish_terminal",
        )
    )
    assert "workflow_override" in inspect.signature(
        V2FinalCompositionTimelineService.load_or_create_and_reconcile
    ).parameters


def test_execution_state_starts_with_the_publication_overlay(
    v2_media_data_dir: Path,
) -> None:
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="adwf_v2_parity",
    )

    state = service._initial_execution_state(workflow, "exec_parity")

    assert state["authoring_base_state_version"] == workflow.state_version
    assert state["authoring_base_revision_no"] == workflow.semantic_revision_no
    assert state["pending_selections"] == {}
