from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, ResolvedNodeInputManifestV2
from app.schemas.agent_canvas_ad_media import CompiledProviderPromptV2
from app.schemas.agent_canvas_runtime import (
    CanvasExecutionMembershipV2,
    CanvasProviderTaskV2,
    NodeExecutionLeaseV2,
)
from app.schemas.agent_canvas_runtime_authority import PreparedNodeResultV2
from app.services.agent_canvas_node_execution import GeneratedMediaPayload
from app.services.agent_canvas_provider_recovery import (
    ProviderPollResult,
    ProviderTaskRecoveryService,
)
from app.services.agent_canvas_publication_metadata import project_canvas_publication_metadata


NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def node(prompt: str = "Original user prompt") -> CanvasNodeV2:
    return CanvasNodeV2(
        node_id="node_video",
        workflow_id="workflow_test",
        node_type="video",
        creative_role="general_video",
        title="Video",
        status="working",
        generation_prompt=prompt,
        position={"x": 0, "y": 0},
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )


def compiled_prompt() -> CompiledProviderPromptV2:
    return CompiledProviderPromptV2(
        semantic_role="general_video",
        prompt_registry_ref="video_prompt_v1",
        prompt_registry_digest=digest("registry"),
        render_context_digest=digest("render"),
        prompt_digest=digest("Compiled provider prompt"),
        reference_bundle_digest=digest("references"),
        style_source="platform_default",
        prompt="Compiled provider prompt",
        negative_prompt="",
    )


def manifest() -> ResolvedNodeInputManifestV2:
    return ResolvedNodeInputManifestV2(
        manifest_id="manifest_original",
        workflow_id="workflow_test",
        execution_id="execution_test",
        node_run_id="node_run_original",
        target_node_id="node_video",
        workflow_revision=1,
        run_intent_snapshot_id="snapshot_original",
        manifest_digest=digest("manifest"),
        media_inputs=(
            {
                "binding_id": "binding_image",
                "source_kind": "image_asset",
                "input_role": "image_reference",
                "asset_id": "asset_original",
                "asset_version_id": "version_original",
                "media_type": "image",
                "checksum": digest("image"),
            },
        ),
        delivered_asset_version_ids=("version_original",),
        world_setting_inputs=(
            {
                "binding_id": "binding_world",
                "source_node_id": "node_world",
                "source_node_revision": 1,
                "source_content_digest": digest("world content"),
                "source_core_digest": digest("world core"),
                "required": True,
                "display_order": 0,
                "target_audience": "video",
                "compiler_id": "world_compiler",
                "compiler_digest": digest("compiler"),
                "context_digest": digest("context"),
                "context": {
                    "source_node_id": "node_world",
                    "source_node_revision": 1,
                    "source_content_digest": digest("world content"),
                    "source_core_digest": digest("world core"),
                    "target_audience": "video",
                    "shared_summary": "A consistent world",
                    "compiler_id": "world_compiler",
                    "compiler_digest": digest("compiler"),
                    "context_digest": digest("context"),
                },
            },
        ),
        created_at=NOW,
    )


def recover(*, prompt_metadata=None, input_manifest=None, provider_prompt=None, live_node=None):
    task = CanvasProviderTaskV2(
        task_id="task_test",
        workflow_id="workflow_test",
        execution_id="execution_test",
        node_id="node_video",
        provider="test_provider",
        remote_task_id="remote_test",
        status="waiting",
        lease_generation=1,
        recovery_deadline=NOW + timedelta(hours=1),
    )
    member = CanvasExecutionMembershipV2(
        member_id="member_test",
        execution_id=task.execution_id,
        workflow_id=task.workflow_id,
        node_id=task.node_id,
        state="running",
        phase="waiting_provider",
        prompt_metadata=prompt_metadata or {},
        resolved_input_manifest=input_manifest,
        updated_at=NOW,
    )
    lease = NodeExecutionLeaseV2(
        workflow_id=task.workflow_id,
        execution_id=task.execution_id,
        node_id=task.node_id,
        owner_id="recovery",
        generation=2,
        state="claimed",
        heartbeat_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    runtime = Mock(spec=AgentCanvasRuntimeRepository)
    runtime.get_provider_task.return_value = task
    runtime.claim_lease.return_value = lease
    runtime.renew_lease.side_effect = lambda current, **kwargs: current
    runtime.put_provider_task.return_value = True
    runtime.list_members.return_value = (member,)
    workflows = Mock()
    workflows.get_node.return_value = live_node or node()
    committer = Mock()
    contexts = []
    published_metadata = []
    audit = {}
    if provider_prompt is not None:
        audit = {
            "prompt_audit": {
                "canonical_provider_prompt_hash": digest(provider_prompt),
                "actual_provider_prompt_hash": digest(provider_prompt),
                "prompt_match": True,
            }
        }

    def prepare(context, outcome, **kwargs):
        contexts.append(context)
        metadata = project_canvas_publication_metadata(context, None, outcome.media.metadata)
        published_metadata.append(metadata)
        return PreparedNodeResultV2(
            logical_result_key="result_test",
            payload_digest=digest("result"),
            asset_metadata=metadata,
        )

    preparer = Mock()
    preparer.prepare.side_effect = prepare
    service = ProviderTaskRecoveryService(
        workflows,
        runtime,
        poller=lambda current: ProviderPollResult(status="succeeded"),
        downloader=lambda current: GeneratedMediaPayload(b"video", "video/mp4", "video.mp4", audit),
        media_publisher=Mock(),
        output_preparer=preparer,
        result_committer=committer,
        clock=lambda: NOW,
    )
    return service, task, committer, contexts, published_metadata


@pytest.mark.parametrize("legacy_manifest_location", [False, True])
def test_recovery_publishes_frozen_prompt_and_input_provenance(legacy_manifest_location):
    compiled = compiled_prompt()
    inputs = manifest().model_dump(mode="json")
    prompt_metadata = {
        "frozen_node": node().model_dump(mode="json"),
        "compiled_provider_prompt": compiled.model_dump(mode="json"),
    }
    if legacy_manifest_location:
        prompt_metadata["resolved_input_manifest"] = inputs
    service, task, committer, contexts, metadata = recover(
        prompt_metadata=prompt_metadata,
        input_manifest=None if legacy_manifest_location else inputs,
        provider_prompt=compiled.prompt,
        live_node=node("User edited this while the provider was working"),
    )

    assert service._recover_one(task)

    assert committer.commit.call_args.args[0].outcome == "succeeded"
    assert contexts[0].node.generation_prompt == "Original user prompt"
    assert contexts[0].compiled_prompt == compiled
    assert metadata[0]["prompt_digest"] == compiled.prompt_digest
    assert metadata[0]["node_run_snapshot_id"] == "snapshot_original"
    assert metadata[0]["input_manifest_id"] == "manifest_original"
    assert metadata[0]["source_asset_ids"] == ["asset_original"]
    assert metadata[0]["source_asset_version_ids"] == ["version_original"]
    assert metadata[0]["world_setting_context"]["source_node_id"] == "node_world"


def test_recovery_of_legacy_task_without_snapshots_uses_saved_node():
    saved_node = node("Legacy saved prompt")
    service, task, committer, contexts, _ = recover(
        live_node=saved_node,
        provider_prompt=saved_node.generation_prompt,
    )

    assert service._recover_one(task)

    assert committer.commit.call_args.args[0].outcome == "succeeded"
    assert contexts[0].node == saved_node
    assert contexts[0].compiled_prompt is None
    assert contexts[0].input_manifest is None


def test_recovery_preserves_frozen_uncompiled_prompt_after_an_edit():
    frozen = node()
    service, task, committer, contexts, _ = recover(
        prompt_metadata={"frozen_node": frozen.model_dump(mode="json")},
        live_node=node("A later edit"),
        provider_prompt=frozen.generation_prompt,
    )

    assert service._recover_one(task)

    assert committer.commit.call_args.args[0].outcome == "succeeded"
    assert contexts[0].node == frozen


def test_recovery_does_not_accept_a_different_provider_prompt():
    service, task, committer, _, _ = recover(
        prompt_metadata={
            "frozen_node": node().model_dump(mode="json"),
            "compiled_provider_prompt": compiled_prompt().model_dump(mode="json"),
        },
        provider_prompt="A different prompt",
    )

    assert service._recover_one(task)

    command = committer.commit.call_args.args[0]
    assert command.outcome == "failed"
    assert command.error.code == "node_result_publication_metadata_invalid"


@pytest.mark.parametrize(
    "field", ["frozen_node", "compiled_provider_prompt", "resolved_input_manifest"]
)
def test_recovery_does_not_fall_back_from_invalid_persisted_context(field):
    service, task, committer, _, _ = recover(prompt_metadata={field: {"invalid": True}})

    with pytest.raises(ValidationError):
        service._recover_one(task)

    committer.commit.assert_not_called()


@pytest.mark.parametrize("field", ["execution_id", "target_node_id", "workflow_id"])
def test_recovery_rejects_an_input_manifest_from_another_execution(field):
    inputs = manifest().model_dump(mode="json")
    inputs[field] = "another_identity"
    service, task, committer, _, _ = recover(input_manifest=inputs)

    with pytest.raises(V2PersistenceError, match="does not match the accepted execution"):
        service._recover_one(task)

    committer.commit.assert_not_called()
