"""Paid provider confirmations survive a restart before scheduler completion."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.core.config import Settings
from app.main import _recover_agent_canvas_executions
from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.agent_canvas_result_commit_repository import AgentCanvasResultCommitRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database, create_v2_database, resolve_v2_database_path
from app.persistence.event_repository import EventRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import (
    CanvasRunRequestV2,
    EffectiveMediaParameterSnapshotV2,
    ResolvedModelExecutionV2,
)
from app.schemas.seedance_inputs import SeedanceInputManifestAuditV1, SeedanceInputManifestV1
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_execution_result_commit import (
    AgentCanvasExecutionResultCommitService,
)
from app.services.agent_canvas_node_execution import (
    GeneratedMediaPayload,
    MediaNodeExecutor,
    NodeExecutionContext,
    NodeExecutionOutcome,
    NodeExecutionDispatcher,
)
from app.services.agent_canvas_output_preparation import AgentCanvasOutputPreparationService
from app.services.agent_canvas_provider_recovery import (
    ProviderPollResult,
    ProviderTaskRecoveryService,
)
from app.services.agent_canvas_provider_submission import ProviderSubmissionIntentService
from app.services.agent_canvas_provider_task_checkpoint import provider_task_checkpoint
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_runtime import AgentCanvasRunService, DynamicCanvasScheduler
from app.services.v2_final_composition_renderer import V2MediaProbeResult


NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
RESTART = NOW + timedelta(minutes=5)
PROMPT = "Frozen provider prompt"
VIDEO_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"provider output"
AUDIO_BYTES = b"ID3provider output"


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


@pytest.fixture(scope="module")
def schema_template(tmp_path_factory):
    directory = tmp_path_factory.mktemp("provider-checkpoint-schema")
    (directory / "v2").mkdir()
    database = create_v2_database(directory)
    try:
        # Never let a developer's Alembic override point tests at another DB.
        with patch.dict(os.environ):
            os.environ.pop("DATABASE_URL", None)
            upgrade_v2_schema(database)
    finally:
        database.dispose()
    return resolve_v2_database_path(directory)


@dataclass
class Authorities:
    data: Path
    database: V2Database
    events: EventRepository
    workflows: AgentCanvasWorkflowRepository
    runtime: AgentCanvasRuntimeRepository
    bindings: AgentCanvasBindingService


def open_authorities(data: Path) -> Authorities:
    database = create_v2_database(data)
    events = EventRepository(database)
    workflows = AgentCanvasWorkflowRepository(database, ProjectRepository(database), events)
    runtime = AgentCanvasRuntimeRepository(database, events)
    bindings = AgentCanvasBindingService(
        workflows, AgentCanvasDocumentRepository(database), asset_resolver=Mock()
    )
    return Authorities(data, database, events, workflows, runtime, bindings)


@pytest.fixture
def authorities(tmp_path, schema_template):
    (tmp_path / "v2").mkdir()
    shutil.copy2(schema_template, resolve_v2_database_path(tmp_path))
    result = open_authorities(tmp_path)
    yield result
    result.database.dispose()


def prepare_attempt(authorities: Authorities, kind: str, *, supports_idempotency=False):
    workflow = authorities.workflows.create_empty(
        project=ProjectCreate(
            project_id="project_test",
            name="Checkpoint",
            created_at=NOW.isoformat(),
            updated_at=NOW.isoformat(),
        ),
        workflow_id="workflow_test",
        idempotency_key="project",
        request_fingerprint="project",
    )
    node = CanvasNodeV2(
        node_id="node_test",
        workflow_id=workflow.workflow_id,
        node_type=kind,
        creative_role=f"general_{kind}",
        title="Output",
        generation_prompt=PROMPT,
        status="draft",
        position={"x": 0, "y": 0},
        revision=1,
        created_at=NOW,
        updated_at=NOW,
        parameters={"duration_seconds": 2},
    )
    authorities.workflows.add_node(node, expected_revision=workflow.revision)
    accepted = AgentCanvasRunService(
        authorities.workflows, authorities.runtime, authorities.events, clock=lambda: NOW
    ).start_or_extend(
        workflow.workflow_id,
        CanvasRunRequestV2(scope="selected_nodes", node_ids=(node.node_id,), source_action="test"),
        idempotency_key="run",
    )
    lease = authorities.runtime.claim_lease(
        accepted.execution_id,
        node.node_id,
        owner_id="submitting-worker",
        now=NOW,
        ttl=timedelta(seconds=60),
    )
    assert lease is not None
    member = authorities.runtime.list_members(accepted.execution_id)[0]
    manifest = AgentCanvasResolvedInputCompiler(authorities.bindings).compile(
        workflow_id=workflow.workflow_id,
        target_node_id=node.node_id,
        execution_id=accepted.execution_id,
        node_run_id="node_run_test",
        run_intent_snapshot_id=member.run_intent_snapshot_id,
        binding_snapshots=member.run_intent_snapshot.binding_snapshots,
    )
    resolution = ResolvedModelExecutionV2(
        model_ref=f"provider/{kind}",
        provider_id="provider_test",
        provider_model_id=f"{kind}-v1",
        capability=kind,
        provider_protocol="test",
        credential_revision=1,
        catalog_revision=1,
        adapter_id="adapter_test",
        transport_kind="ark_video_native" if kind == "video" else "test_audio",
        capability_revision="1",
        adapter_revision="1",
        requested_parameter_fingerprint=digest("requested"),
        effective_parameter_fingerprint=digest("effective"),
        capability_metadata={"supports_provider_idempotency_token": supports_idempotency},
    )
    parameters = EffectiveMediaParameterSnapshotV2(
        requested=node.parameters,
        effective=node.parameters,
        provider=resolution.provider_id,
        model_id=resolution.provider_model_id,
        capability_revision=1,
    )
    authorities.runtime.update_member(
        accepted.execution_id,
        node.node_id,
        state="running",
        phase="running",
        now=NOW,
        resolved_input_manifest=manifest.model_dump(mode="json"),
        resolved_input_manifest_id=manifest.manifest_id,
        resolved_input_manifest_digest=manifest.manifest_digest,
        effective_parameters=parameters,
    )
    authorities.runtime.set_execution_status(
        accepted.execution_id, "running", now=NOW, event_type="execution_started"
    )
    authorities.workflows.set_node_runtime_state(
        workflow.workflow_id,
        node.node_id,
        status="working",
        updated_at=NOW,
        event_type="node_generation_started",
        execution_id=accepted.execution_id,
    )
    seedance_manifest = None
    seedance_audit = None
    if kind == "video":
        seedance_manifest = SeedanceInputManifestV1(
            node_id=node.node_id,
            model_id=resolution.provider_model_id,
            prompt=PROMPT,
            aspect_ratio="16:9",
            resolution="720p",
            requested_duration_seconds=2,
            effective_duration_seconds=2,
            generate_audio=False,
        )
        seedance_audit = SeedanceInputManifestAuditV1(
            node_id=node.node_id,
            model_id=resolution.provider_model_id,
            prompt_hash=digest(PROMPT),
            input_counts={"text": 0, "script": 0, "image": 0, "video": 0, "audio": 0},
            aspect_ratio="16:9",
            resolution="720p",
            requested_duration_seconds=2,
            effective_duration_seconds=2,
            generate_audio=False,
        )
    context = NodeExecutionContext(
        execution_id=accepted.execution_id,
        node=node,
        inputs=(),
        model_id=resolution.provider_model_id,
        provider_id=resolution.provider_id,
        model_resolution=resolution,
        input_manifest=manifest,
        effective_parameters=parameters,
        seedance_manifest=seedance_manifest,
        seedance_input_audit=seedance_audit,
    )
    return context, lease


def execute_waiting(authorities, context, lease, *, provider_callback=None, clock=lambda: NOW):
    result = SimpleNamespace(
        status="waiting",
        remote_task_id="remote_paid_test",
        provider="provider_test",
        provider_model=context.model_id,
        provider_payload_snapshot={
            "provider_model_id": context.model_id,
            "request_id": "request_test",
        },
        metadata={
            "prompt_audit": {
                "canonical_provider_prompt_hash": digest(PROMPT),
                "actual_provider_prompt_hash": digest(PROMPT),
                "prompt_match": True,
            }
        },
    )
    provider = Mock()

    def submit(**kwargs):
        if provider_callback is not None:
            provider_callback()
        return result

    provider.execute_minimal.side_effect = submit
    provider.execute_agent_canvas_seedance_video.side_effect = submit
    executor = MediaNodeExecutor(
        provider,
        data_dir=authorities.data,
        settings=Settings(media_data_dir=authorities.data),
        submission_intents=ProviderSubmissionIntentService(authorities.runtime),
        clock=clock,
    )
    scheduler = DynamicCanvasScheduler(
        authorities.workflows,
        authorities.runtime,
        authorities.bindings,
        Mock(),
        NodeExecutionDispatcher(audio_executor=executor, video_executor=executor),
        media_publisher=Mock(),
        clock=clock,
    )
    outcome, latest_lease = scheduler._execute_member_guarded(lease, context)
    return outcome, latest_lease, provider, scheduler


def probe(path: Path, media_type: str) -> V2MediaProbeResult:
    assert path.read_bytes() == (VIDEO_BYTES if media_type == "video" else AUDIO_BYTES)
    return V2MediaProbeResult(
        path=path,
        media_type=media_type,
        width=640,
        height=360,
        duration_seconds=2,
        fps=24,
    )


def recovery_services(authorities, *, clock=lambda: RESTART, status="succeeded"):
    assets = V2AssetLibraryRepository(authorities.database)
    asset_service = AgentCanvasAssetService(
        authorities.data, assets, authorities.workflows, media_facts_probe=probe
    )
    committer = AgentCanvasExecutionResultCommitService(
        AgentCanvasResultCommitRepository(authorities.database, assets, authorities.events)
    )
    poller = Mock(return_value=ProviderPollResult(status=status))

    def download(task):
        video = task.result_descriptor["media_type"] == "video"
        return GeneratedMediaPayload(
            VIDEO_BYTES if video else AUDIO_BYTES,
            "video/mp4" if video else "audio/mpeg",
            "result.mp4" if video else "result.mp3",
            task.result_descriptor,
        )

    downloader = Mock(side_effect=download)
    recovery = ProviderTaskRecoveryService(
        authorities.workflows,
        authorities.runtime,
        poller=poller,
        downloader=downloader,
        media_publisher=Mock(side_effect=AssertionError("Legacy publisher called")),
        output_preparer=AgentCanvasOutputPreparationService(asset_service),
        result_committer=committer,
        clock=clock,
    )
    return SimpleNamespace(
        recovery=recovery,
        committer=committer,
        poller=poller,
        downloader=downloader,
        assets=assets,
    )


def run_full_scheduler(authorities, context, original_lease, *, callback, clock, services):
    # Preparation has already been persisted by prepare_attempt. Let the real
    # scheduler claim and execute it, injecting only the prepared provider context.
    authorities.runtime.complete_lease(original_lease, now=NOW)
    authorities.runtime.update_member(
        context.execution_id, context.node.node_id, state="queued", phase="queued", now=NOW
    )
    provider = Mock()
    provider.execute_minimal.side_effect = lambda **kwargs: callback()
    provider.execute_agent_canvas_seedance_video.side_effect = lambda **kwargs: callback()
    executor = MediaNodeExecutor(
        provider,
        data_dir=authorities.data,
        settings=Settings(media_data_dir=authorities.data),
        submission_intents=ProviderSubmissionIntentService(authorities.runtime),
        clock=clock,
    )
    scheduler = DynamicCanvasScheduler(
        authorities.workflows,
        authorities.runtime,
        authorities.bindings,
        Mock(),
        NodeExecutionDispatcher(audio_executor=executor, video_executor=executor),
        media_publisher=Mock(),
        result_committer=services.committer,
        clock=clock,
    )
    with patch.object(scheduler, "_prepare_member", return_value=context):
        scheduler.resume(context.execution_id)
    return provider


def waiting_result(context):
    return SimpleNamespace(
        status="waiting",
        remote_task_id="remote_paid_test",
        provider="provider_test",
        provider_model=context.model_id,
        provider_payload_snapshot={"request_id": "request_test"},
        metadata={
            "prompt_audit": {
                "canonical_provider_prompt_hash": digest(PROMPT),
                "actual_provider_prompt_hash": digest(PROMPT),
                "prompt_match": True,
            }
        },
    )


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_confirmed_paid_task_recovers_after_exit_before_scheduler_completion(authorities, kind):
    context, lease = prepare_attempt(authorities, kind)
    outcome, _, provider, _ = execute_waiting(authorities, context, lease)
    # Simulate exit after the executor returns, before scheduler._complete_member.
    authorities.database.dispose()
    restarted = open_authorities(authorities.data)
    try:
        intent = restarted.runtime.get_submission_intent(outcome.submission_intent_id)
        assert intent.remote_task_id == "remote_paid_test"
        assets = V2AssetLibraryRepository(restarted.database)
        asset_service = AgentCanvasAssetService(
            authorities.data, assets, restarted.workflows, media_facts_probe=probe
        )
        committer = AgentCanvasExecutionResultCommitService(
            AgentCanvasResultCommitRepository(restarted.database, assets, restarted.events)
        )
        poller = Mock(return_value=ProviderPollResult(status="succeeded"))
        content = VIDEO_BYTES if kind == "video" else AUDIO_BYTES
        downloader = Mock(
            side_effect=lambda current: GeneratedMediaPayload(
                content,
                "video/mp4" if kind == "video" else "audio/mpeg",
                "result.mp4" if kind == "video" else "result.mp3",
                current.result_descriptor,
            )
        )
        recovery = ProviderTaskRecoveryService(
            restarted.workflows,
            restarted.runtime,
            poller=poller,
            downloader=downloader,
            media_publisher=Mock(side_effect=AssertionError("Legacy publisher called")),
            output_preparer=AgentCanvasOutputPreparationService(asset_service),
            result_committer=committer,
            clock=lambda: RESTART,
        )
        no_resubmit = Mock(side_effect=AssertionError("Paid request must not be resubmitted"))
        scheduler = DynamicCanvasScheduler(
            restarted.workflows,
            restarted.runtime,
            restarted.bindings,
            Mock(),
            NodeExecutionDispatcher(audio_executor=no_resubmit, video_executor=no_resubmit),
            media_publisher=no_resubmit,
            clock=lambda: RESTART,
        )
        startup = SimpleNamespace(
            database=restarted.database,
            provider_recovery=recovery,
            post_ready_effects=SimpleNamespace(run_once=lambda: None),
            runtime_repository=restarted.runtime,
            workflows=restarted.workflows,
            scheduler=scheduler,
        )
        _recover_agent_canvas_executions(
            Settings(media_data_dir=authorities.data), runtime_factory=lambda settings: startup
        )
        tasks = restarted.runtime.list_provider_tasks(execution_id=context.execution_id)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.result_descriptor["media_type"] == kind
        assert task.result_descriptor["provider_payload"]["request_id"] == "request_test"
        assert task.result_descriptor["model_resolution"] == context.model_resolution.model_dump(
            mode="json"
        )
        if kind == "video":
            assert task.result_descriptor["provider_payload"]["seedance_input_manifest"] == (
                context.seedance_input_audit.model_dump(mode="json")
            )
        assert restarted.runtime.get_provider_task(task.task_id).status == "succeeded"
        assert restarted.runtime.get_execution(context.execution_id).status == "completed"
        published = restarted.workflows.get_node(context.node.workflow_id, context.node.node_id)
        assert published.status == "ready"
        version = assets.find_version(asset_id=published.output_asset_id)
        assert (authorities.data / version.storage_key).read_bytes() == content
        assert version.metadata["input_manifest_id"] == context.input_manifest.manifest_id
        assert len(committer.list_receipts(context.execution_id)) == 1
        assert recovery.recover_due_tasks() == ()
        assert (
            provider.execute_minimal.call_count
            + provider.execute_agent_canvas_seedance_video.call_count
            == 1
        )
        poller.assert_called_once()
        downloader.assert_called_once()
        no_resubmit.assert_not_called()
    finally:
        restarted.database.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_full_scheduler_retains_paid_checkpoint_when_submission_outlives_lease(authorities, kind):
    context, lease = prepare_attempt(authorities, kind)
    time = [NOW]
    services = recovery_services(authorities, clock=lambda: time[0])

    def paid_response_after_expiry():
        time[0] = RESTART
        return waiting_result(context)

    provider = run_full_scheduler(
        authorities,
        context,
        lease,
        callback=paid_response_after_expiry,
        clock=lambda: time[0],
        services=services,
    )

    task = authorities.runtime.list_provider_tasks(execution_id=context.execution_id)[0]
    assert task.status == "submitted"
    assert authorities.runtime.list_members(context.execution_id)[0].state == "running"
    assert services.committer.list_receipts(context.execution_id) == ()
    assert services.recovery.recover_due_tasks() == (task.task_id,)
    assert authorities.runtime.get_execution(context.execution_id).status == "completed"
    assert (
        provider.execute_minimal.call_count
        + provider.execute_agent_canvas_seedance_video.call_count
        == 1
    )


@pytest.mark.integration
def test_cancellation_during_paid_submission_retains_evidence_without_publication(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    services = recovery_services(authorities, clock=lambda: NOW)
    canceller = DynamicCanvasScheduler(
        authorities.workflows,
        authorities.runtime,
        authorities.bindings,
        Mock(),
        Mock(),
        media_publisher=Mock(),
        clock=lambda: NOW,
    )

    def paid_response_after_cancellation():
        canceller.cancel(context.execution_id, reason="user_cancelled")
        return waiting_result(context)

    provider = run_full_scheduler(
        authorities,
        context,
        lease,
        callback=paid_response_after_cancellation,
        clock=lambda: NOW,
        services=services,
    )

    task = authorities.runtime.list_provider_tasks(execution_id=context.execution_id)[0]
    assert task.status == "cancelled"
    assert task.remote_task_id == "remote_paid_test"
    assert task.result_descriptor["provider_payload"]["request_id"] == "request_test"
    assert authorities.runtime.list_members(context.execution_id)[0].state == "cancelled"
    assert authorities.runtime.get_execution(context.execution_id).status == "cancelled"
    assert services.recovery.recover_due_tasks() == ()
    services.poller.assert_not_called()
    services.downloader.assert_not_called()
    assert services.committer.list_receipts(context.execution_id) == ()
    provider.execute_minimal.assert_called_once()


@pytest.mark.integration
@pytest.mark.parametrize("same_remote", [False, True])
def test_new_lease_owner_is_not_changed_by_late_paid_confirmation(authorities, same_remote):
    context, lease = prepare_attempt(authorities, "audio", supports_idempotency=True)
    time = [NOW]
    successor_member = []
    successor_leases = []

    def take_over():
        time[0] = RESTART
        successor = authorities.runtime.claim_lease(
            context.execution_id,
            context.node.node_id,
            owner_id="successor",
            now=RESTART,
            ttl=timedelta(seconds=60),
        )
        assert successor.generation > lease.generation
        successor_leases.append(successor)
        authorities.runtime.update_member(
            context.execution_id,
            context.node.node_id,
            state="running",
            phase="running",
            now=RESTART,
            prompt_metadata={"successor": True},
        )
        successor_member.append(authorities.runtime.list_members(context.execution_id)[0])

    with pytest.raises(V2PersistenceError, match="lease"):
        execute_waiting(
            authorities, context, lease, provider_callback=take_over, clock=lambda: time[0]
        )

    task = authorities.runtime.list_provider_tasks(execution_id=context.execution_id)[0]
    assert task.status == "cancelled"
    assert task.error.code == "provider_submission_superseded"
    assert task.remote_task_id == "remote_paid_test"
    assert authorities.runtime.list_members(context.execution_id)[0] == successor_member[0]
    services = recovery_services(authorities)
    assert services.recovery.recover_due_tasks() == ()
    services.poller.assert_not_called()

    # Evidence from a stale response must not reserve the authoritative intent
    # before the actual owner's own remote confirmation arrives.
    intent = authorities.runtime.list_submission_intents(execution_id=context.execution_id)[0]
    assert intent.provider_idempotency_token is not None
    successor_task_id = task.task_id if same_remote else "task_successor"
    successor_remote_id = task.remote_task_id if same_remote else "remote_successor"
    successor_outcome = NodeExecutionOutcome(
        provider_task_id=successor_task_id,
        remote_task_id=successor_remote_id,
        provider="provider_test",
        submission_intent_id=intent.intent_id,
        result_descriptor={"media_type": "audio", "provider_payload": {"request_id": "successor"}},
    )
    ProviderSubmissionIntentService(authorities.runtime).confirm_remote_task(
        intent,
        task=provider_task_checkpoint(context, successor_outcome, successor_leases[0], now=RESTART),
        lease=successor_leases[0],
        now=RESTART,
    )
    assert authorities.runtime.get_provider_task(successor_task_id).status == "submitted"
    assert (
        authorities.runtime.get_submission_intent(intent.intent_id).remote_task_id
        == successor_remote_id
    )
    if not same_remote:
        assert authorities.runtime.get_provider_task(task.task_id).status == "cancelled"
    authorities.runtime.complete_lease(successor_leases[0], now=RESTART)
    assert services.recovery.recover_due_tasks() == (successor_task_id,)
    assert authorities.runtime.get_execution(context.execution_id).status == "completed"
    assert len(services.committer.list_receipts(context.execution_id)) == 1


@pytest.mark.integration
def test_checkpoint_replay_and_scheduler_handoff_do_not_reset_polled_state(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    outcome, latest_lease, _, scheduler = execute_waiting(authorities, context, lease)
    task = authorities.runtime.get_provider_task(outcome.provider_task_id)
    advanced = task.model_copy(
        update={"status": "waiting", "next_poll_at": NOW + timedelta(seconds=8)}
    )
    assert authorities.runtime.put_provider_task(advanced, now=NOW)
    cursor = authorities.events.max_seq(context.node.workflow_id)
    intent = authorities.runtime.get_submission_intent(outcome.submission_intent_id)

    ProviderSubmissionIntentService(authorities.runtime).confirm_remote_task(
        intent,
        task=task,
        lease=lease,
        now=NOW,
    )
    scheduler._complete_member(context.node.workflow_id, latest_lease, context, outcome)

    assert authorities.runtime.get_provider_task(task.task_id) == advanced
    assert authorities.events.max_seq(context.node.workflow_id) == cursor
    event = next(
        event
        for event in authorities.events.list_after(context.node.workflow_id)
        if event.event_type == "provider_task_submitted"
    )
    assert event.payload["model_resolution"] == context.model_resolution.model_dump(mode="json")
    assert "parameter_compilation_snapshot_id" in event.payload


@pytest.mark.integration
def test_checkpoint_transaction_rolls_back_task_intent_member_and_event_together(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    cursor = authorities.events.max_seq(context.node.workflow_id)
    append = authorities.events.append_in_transaction

    def fail_after_checkpoint_writes(connection, event):
        if event.transition_key and event.transition_key.startswith("provider-submission:"):
            raise RuntimeError("Injected checkpoint failure")
        return append(connection, event)

    paid_calls = []
    with patch.object(
        authorities.events, "append_in_transaction", side_effect=fail_after_checkpoint_writes
    ):
        with pytest.raises(RuntimeError, match="Injected checkpoint failure"):
            execute_waiting(
                authorities, context, lease, provider_callback=lambda: paid_calls.append(1)
            )

    intent = authorities.runtime.list_submission_intents(execution_id=context.execution_id)[0]
    assert intent.state == "prepared"
    assert intent.remote_task_id is None
    assert intent.provider_task_id is None
    assert authorities.runtime.list_provider_tasks(execution_id=context.execution_id) == ()
    member = authorities.runtime.list_members(context.execution_id)[0]
    assert member.phase == "running"
    assert member.provider_task_id is None
    assert authorities.events.max_seq(context.node.workflow_id) == cursor
    assert paid_calls == [1]


@pytest.mark.integration
def test_late_confirmation_does_not_overwrite_an_existing_remote_winner(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    time = [NOW]
    winner = []

    def confirm_successor_first():
        time[0] = RESTART
        successor = authorities.runtime.claim_lease(
            context.execution_id,
            context.node.node_id,
            owner_id="successor",
            now=RESTART,
            ttl=timedelta(seconds=60),
        )
        intent = authorities.runtime.list_submission_intents(execution_id=context.execution_id)[0]
        outcome = NodeExecutionOutcome(
            provider_task_id="task_winner",
            remote_task_id="remote_winner",
            provider="provider_test",
            submission_intent_id=intent.intent_id,
            result_descriptor={"media_type": "audio", "provider_payload": {"request_id": "winner"}},
        )
        confirmed = ProviderSubmissionIntentService(authorities.runtime).confirm_remote_task(
            intent,
            task=provider_task_checkpoint(context, outcome, successor, now=RESTART),
            lease=successor,
            now=RESTART,
        )
        winner.append((confirmed, authorities.runtime.list_members(context.execution_id)[0]))

    with pytest.raises(V2PersistenceError, match="lease"):
        execute_waiting(
            authorities,
            context,
            lease,
            provider_callback=confirm_successor_first,
            clock=lambda: time[0],
        )

    assert authorities.runtime.get_submission_intent(winner[0][0].intent_id) == winner[0][0]
    assert authorities.runtime.list_members(context.execution_id)[0] == winner[0][1]
    tasks = authorities.runtime.list_provider_tasks(execution_id=context.execution_id)
    assert {(task.remote_task_id, task.status) for task in tasks} == {
        ("remote_winner", "submitted"),
        ("remote_paid_test", "cancelled"),
    }


@pytest.mark.integration
def test_replayed_confirmation_does_not_reset_newer_terminal_provider_task(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    outcome, _, _, _ = execute_waiting(authorities, context, lease)
    original_task = authorities.runtime.get_provider_task(outcome.provider_task_id)
    original_intent = authorities.runtime.get_submission_intent(outcome.submission_intent_id)
    services = recovery_services(authorities, status="failed")
    assert services.recovery.recover_due_tasks() == (original_task.task_id,)
    terminal = authorities.runtime.get_provider_task(original_task.task_id)
    assert terminal.status == "failed"
    assert terminal.lease_generation > lease.generation
    cursor = authorities.events.max_seq(context.node.workflow_id)
    receipts = services.committer.list_receipts(context.execution_id)

    ProviderSubmissionIntentService(authorities.runtime).confirm_remote_task(
        original_intent,
        task=original_task,
        lease=lease,
        now=RESTART,
    )

    assert authorities.runtime.get_provider_task(original_task.task_id) == terminal
    assert authorities.runtime.list_members(context.execution_id)[0].state == "failed"
    assert services.committer.list_receipts(context.execution_id) == receipts
    assert authorities.events.max_seq(context.node.workflow_id) == cursor


@pytest.mark.integration
def test_old_guard_does_not_fail_a_task_claimed_by_newer_recovery_generation(authorities):
    context, lease = prepare_attempt(authorities, "audio")
    time = [NOW]
    services = recovery_services(authorities, clock=lambda: time[0], status="waiting")
    original_confirm = ProviderSubmissionIntentService.confirm_remote_task

    def confirm_then_recover(self, *args, **kwargs):
        result = original_confirm(self, *args, **kwargs)
        time[0] = RESTART
        assert services.recovery.recover_due_tasks()
        return result

    with patch.object(ProviderSubmissionIntentService, "confirm_remote_task", confirm_then_recover):
        provider = run_full_scheduler(
            authorities,
            context,
            lease,
            callback=lambda: waiting_result(context),
            clock=lambda: time[0],
            services=services,
        )

    task = authorities.runtime.list_provider_tasks(execution_id=context.execution_id)[0]
    assert task.status == "waiting"
    assert task.lease_generation > lease.generation + 1
    assert authorities.runtime.list_members(context.execution_id)[0].phase == "waiting_provider"
    assert services.committer.list_receipts(context.execution_id) == ()
    time[0] = RESTART + timedelta(seconds=9)
    services.poller.return_value = ProviderPollResult(status="succeeded")
    assert services.recovery.recover_due_tasks() == (task.task_id,)
    assert authorities.runtime.get_execution(context.execution_id).status == "completed"
    provider.execute_minimal.assert_called_once()
