"""Exercise restart recovery through real SQLite authorities and file storage.

Provider transport and the external media probe are injected; the authoring,
snapshot, lease, preparation, content storage, and commit authorities are real.
"""

from base64 import b64decode
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.agent_canvas_result_commit_repository import AgentCanvasResultCommitRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import CanvasBindingCreateRequestV2, CanvasNodeV2
from app.schemas.agent_canvas_ad_media import CompiledProviderPromptV2
from app.schemas.agent_canvas_runtime import (
    CanvasProviderTaskV2,
    CanvasRunRequestV2,
    EffectiveMediaParameterSnapshotV2,
    ResolvedModelExecutionV1,
)
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_execution_result_commit import (
    AgentCanvasExecutionResultCommitService,
)
from app.services.agent_canvas_node_execution import GeneratedMediaPayload
from app.services.agent_canvas_output_preparation import AgentCanvasOutputPreparationService
from app.services.agent_canvas_provider_recovery import (
    ProviderPollResult,
    ProviderTaskRecoveryService,
)
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_run_snapshots import AgentCanvasRunIntentSnapshotService
from app.services.agent_canvas_runtime import AgentCanvasRunService
from app.services.v2_final_composition_renderer import V2MediaProbeResult


NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
SOURCE_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9p0AAAAASUVORK5CYII="
)
# Only transport/storage behavior is under test; decoding is the probe adapter's job.
PROVIDER_VIDEO = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"provider result"


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def media_probe(path: Path, media_type: str) -> V2MediaProbeResult:
    assert path.read_bytes() == PROVIDER_VIDEO
    assert media_type == "video"
    return V2MediaProbeResult(
        path=path, media_type=media_type, width=640, height=360, duration_seconds=2, fps=24
    )


@pytest.mark.integration
@pytest.mark.media
@pytest.mark.parametrize("edit_live_node", [False, True])
def test_provider_recovery_after_restart_commits_once_with_original_provenance(
    tmp_path, monkeypatch, edit_live_node
):
    # Alembic's environment override must not route an isolated test to a user's DB.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "v2").mkdir()
    database = create_v2_database(tmp_path)
    try:
        upgrade_v2_schema(database)
        events = EventRepository(database)
        workflows = AgentCanvasWorkflowRepository(database, ProjectRepository(database), events)
        runtime = AgentCanvasRuntimeRepository(database, events)
        assets = V2AssetLibraryRepository(database)
        asset_service = AgentCanvasAssetService(
            tmp_path, assets, workflows, media_facts_probe=media_probe
        )
        workflow = workflows.create_empty(
            project=ProjectCreate(
                project_id="project_integration",
                name="Recovery integration",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
            workflow_id="workflow_integration",
            idempotency_key="create_integration",
            request_fingerprint="create_integration",
        )
        original_node = CanvasNodeV2(
            workflow_id=workflow.workflow_id,
            node_id="node_video",
            node_type="video",
            creative_role="general_video",
            title="Original video",
            generation_prompt="Original user prompt",
            status="draft",
            position={"x": 0, "y": 0},
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
        workflow = workflows.add_node(original_node, expected_revision=workflow.revision)
        source = asset_service.upload_bytes(
            workflow.workflow_id,
            filename="source.png",
            mime_type="image/png",
            content=SOURCE_PNG,
            title="Original reference",
            media_type="image",
            idempotency_key="upload_source",
        )
        bindings = AgentCanvasBindingService(
            workflows,
            AgentCanvasDocumentRepository(database),
            asset_resolver=asset_service.resolve_asset,
            asset_version_resolver=asset_service.resolve_asset_version,
        )
        bindings.create(
            workflow.workflow_id,
            CanvasBindingCreateRequestV2(
                source={
                    "kind": "image_asset",
                    "source_asset_id": source.asset_id,
                    "source_asset_version_id": source.version_id,
                },
                target_node_id=original_node.node_id,
                input_role="image_reference",
            ),
            expected_revision=workflow.revision,
        )
        accepted = AgentCanvasRunService(
            workflows,
            runtime,
            events,
            run_snapshots=AgentCanvasRunIntentSnapshotService(
                workflows, runtime, bindings=bindings
            ),
            clock=lambda: NOW,
        ).start_or_extend(
            workflow.workflow_id,
            CanvasRunRequestV2(
                scope="selected_nodes", node_ids=(original_node.node_id,), source_action="test"
            ),
            idempotency_key="run_integration",
        )
        member = runtime.list_members(accepted.execution_id)[0]
        manifest = AgentCanvasResolvedInputCompiler(bindings).compile(
            workflow_id=workflow.workflow_id,
            target_node_id=original_node.node_id,
            execution_id=accepted.execution_id,
            node_run_id="node_run_integration",
            run_intent_snapshot_id=member.run_intent_snapshot_id,
            binding_snapshots=member.run_intent_snapshot.binding_snapshots,
        )
        compiled = CompiledProviderPromptV2(
            semantic_role="general_video",
            prompt="Compiled provider prompt using the original reference",
            prompt_registry_ref="video_prompt_v1",
            prompt_registry_digest=digest("registry"),
            render_context_digest=digest("render"),
            prompt_digest=digest("Compiled provider prompt using the original reference"),
            reference_bundle_digest=digest("references"),
            style_source="platform_default",
            negative_prompt="",
        )
        resolution = ResolvedModelExecutionV1(
            model_ref="test/video-v1",
            provider_id="test_provider",
            provider_model_id="test_video_v1",
            capability="video",
            provider_protocol="test_protocol",
            credential_revision=1,
            catalog_revision=1,
        )
        task = CanvasProviderTaskV2(
            task_id="task_integration",
            workflow_id=workflow.workflow_id,
            execution_id=accepted.execution_id,
            node_id=original_node.node_id,
            provider="test_provider",
            remote_task_id="remote_integration",
            status="waiting",
            lease_generation=1,
            next_poll_at=NOW,
            recovery_deadline=NOW + timedelta(hours=1),
            result_descriptor={"model_resolution": resolution.model_dump(mode="json")},
        )
        assert runtime.update_member(
            accepted.execution_id,
            original_node.node_id,
            state="running",
            phase="waiting_provider",
            now=NOW,
            provider_task_id=task.task_id,
            prompt_metadata={
                **member.prompt_metadata,
                "compiled_provider_prompt": compiled.model_dump(mode="json"),
            },
            resolved_input_manifest=manifest.model_dump(mode="json"),
            resolved_input_manifest_id=manifest.manifest_id,
            resolved_input_manifest_digest=manifest.manifest_digest,
            effective_parameters=EffectiveMediaParameterSnapshotV2(
                provider=resolution.provider_id,
                model_id=resolution.provider_model_id,
                capability_revision=resolution.catalog_revision,
                execution_mode=member.run_intent_snapshot.execution_mode,
                semantic_extraction=member.run_intent_snapshot.semantic_extraction,
            ),
        )
        assert runtime.put_provider_task(task, now=NOW)
        if edit_live_node:
            workflow = workflows.get_workflow(workflow.workflow_id)
            workflows.update_node(
                original_node.model_copy(
                    update={"generation_prompt": "Edited while waiting", "revision": 2}
                ),
                expected_revision=workflow.revision,
            )
    finally:
        database.dispose()

    # Reconstruct all authorities from disk: no process-local execution state survives.
    database = create_v2_database(tmp_path)
    try:
        events = EventRepository(database)
        workflows = AgentCanvasWorkflowRepository(database, ProjectRepository(database), events)
        runtime = AgentCanvasRuntimeRepository(database, events)
        assets = V2AssetLibraryRepository(database)
        asset_service = AgentCanvasAssetService(
            tmp_path, assets, workflows, media_facts_probe=media_probe
        )
        committer = AgentCanvasExecutionResultCommitService(
            AgentCanvasResultCommitRepository(database, assets, events)
        )
        poller = Mock(return_value=ProviderPollResult(status="succeeded"))
        downloader = Mock(
            return_value=GeneratedMediaPayload(
                PROVIDER_VIDEO,
                "video/mp4",
                "generated.mp4",
                {
                    "prompt_audit": {
                        "canonical_provider_prompt_hash": compiled.prompt_digest,
                        "actual_provider_prompt_hash": compiled.prompt_digest,
                        "prompt_match": True,
                    }
                },
            )
        )
        service = ProviderTaskRecoveryService(
            workflows,
            runtime,
            poller=poller,
            downloader=downloader,
            media_publisher=Mock(side_effect=AssertionError("Legacy publisher must not run")),
            # This matches provider_recovery wiring in create_agent_canvas_runtime:
            # asynchronous recovery has its own preparer without publication intents.
            output_preparer=AgentCanvasOutputPreparationService(asset_service),
            result_committer=committer,
            clock=lambda: NOW,
        )

        assert service.recover_due_tasks() == (task.task_id,)

        assert runtime.get_provider_task(task.task_id).status == "succeeded"
        assert runtime.list_members(task.execution_id)[0].state == "succeeded"
        assert runtime.get_execution(task.execution_id).status == "completed"
        published = workflows.get_node(task.workflow_id, task.node_id)
        assert published.status == "ready"
        assert published.generation_prompt == (
            "Edited while waiting" if edit_live_node else original_node.generation_prompt
        )
        version = assets.find_version(asset_id=published.output_asset_id)
        assert version is not None
        assert (tmp_path / version.storage_key).read_bytes() == PROVIDER_VIDEO
        assert version.sha256 == sha256(PROVIDER_VIDEO).hexdigest()
        metadata = version.metadata
        provenance = metadata["generated_asset_provenance"]
        assert metadata["prompt_digest"] == compiled.prompt_digest
        assert provenance["compiled_prompt_digest"] == compiled.prompt_digest
        assert provenance["prompt_registry_digest"] == compiled.prompt_registry_digest
        assert provenance["node_run_snapshot_id"] == member.run_intent_snapshot_id
        assert provenance["input_manifest_id"] == manifest.manifest_id
        assert provenance["source_asset_version_ids"] == [source.version_id]
        assert provenance["node_revision"] == original_node.revision
        assert provenance["provider"] == resolution.provider_id
        assert provenance["model_id"] == resolution.provider_model_id
        assert provenance["execution_mode"] == member.run_intent_snapshot.execution_mode
        receipts = committer.list_receipts(task.execution_id)
        assert len(receipts) == 1
        assert receipts[0].asset_id == published.output_asset_id
        assert receipts[0].outcome == "succeeded"
        versions = assets.list_versions_for_workflow(task.workflow_id)
        assert len(versions) == 2  # Uploaded reference and generated result.
        cursor = events.max_seq(task.workflow_id)

        assert service.recover_due_tasks() == ()

        assert committer.list_receipts(task.execution_id) == receipts
        assert assets.list_versions_for_workflow(task.workflow_id) == versions
        assert events.max_seq(task.workflow_id) == cursor
        poller.assert_called_once()
        downloader.assert_called_once()

        # Direct legacy callers that omit an accepted revision retain their
        # existing behavior of taking the saved Node's current authoring revision.
        legacy_prepared = asset_service.prepare_generated_bytes(
            workflow.workflow_id,
            node_id=original_node.node_id,
            execution_id=task.execution_id,
            filename="legacy.mp4",
            mime_type="video/mp4",
            content=PROVIDER_VIDEO,
            fingerprint="legacy_direct_prepare",
        )
        assert legacy_prepared.asset_metadata["generated_asset_provenance"]["node_revision"] == (
            2 if edit_live_node else original_node.revision
        )
    finally:
        database.dispose()
