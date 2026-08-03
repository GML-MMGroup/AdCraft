"""Public V2 Agent Canvas authoring and project-media endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.api.v2.etag import (
    V2PreconditionError,
    parse_project_if_match,
    parse_workflow_if_match,
    project_etag,
    workflow_etag,
)
from app.core.config import Settings, get_settings
from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.agent_canvas_editing_repository import (
    AgentCanvasEditingExportRepository,
)
from app.persistence.agent_canvas_runtime_repository import (
    AgentCanvasRuntimeRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database, create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    AgentTargetResolutionV2,
    CanvasBindingCreateRequestV2,
    CanvasBindingMutationResponseV2,
    CanvasBindingPatchRequestV2,
    CanvasConnectedNodeCreateRequestV2,
    CanvasConnectedNodeCreateResponseV2,
    CanvasConnectionPolicyV2,
    CanvasLayoutPatchRequestV2,
    CanvasLayoutPatchResponseV2,
    CanvasMutationResponseV2,
    CanvasNodeCreateRequestV2,
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
    CanvasVariationDraftResponseV2,
    CanvasVariationDraftUpsertV2,
    CanvasVariationMaterializeRequestV2,
    CanvasVariationMaterializeResponseV2,
    ImageLibraryListResponseV2,
    ProjectAssetListResponseV2,
    ProjectAssetUploadMetadataV2,
    ProjectAssetUploadResponseV2,
    ProjectCreateRequestV2,
    ProjectCreateResponseV2,
    SaveImageToLibraryRequestV2,
)
from app.schemas.agent_canvas_conversation import (
    AgentCommandPlanActionRequestV2,
    ChatMessageRequestV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptProposalV2,
    GuidedActionApplyRequestV2,
    ProposalActionRequestV2,
    VideoSkillRunCreateRequestV2,
    VideoSkillRunV2,
)
from app.schemas.agent_canvas_creative_session import CreativeSessionStateV2
from app.schemas.agent_canvas_video_skills import (
    VideoSkillPublicDetailV2,
    VideoSkillSummaryListV2,
)
from app.schemas.agent_canvas_runtime import (
    CanvasProviderModelCapabilityListV2,
    CanvasRunAcceptedV2,
    CanvasRunCancelRequestV2,
    CanvasRunCancelResponseV2,
    CanvasRunRequestV2,
    CanvasRuntimeEventListV2,
    CanvasRuntimeEventV2,
    CanvasRuntimeSnapshotV2,
)
from app.schemas.agent_canvas_editing import (
    EditingExportAcceptedV2,
    EditingExportCancelResponseV2,
    EditingExportRequestV2,
    EditingManifestV2,
)
from app.schemas.v2_asset_library import AssetLibraryEntityDetailV2
from app.schemas.workflow_v2_projects import (
    ProjectV2,
    ProjectV2ListResponse,
    ProjectV2UpdateRequest,
)
from app.services.agent_canvas_assets import (
    AgentCanvasAssetService,
    deterministic_media_facts_probe,
)
from app.services.agent_canvas_composition_renderer import (
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import EditingInputResolver, EditingNodeService
from app.services.agent_canvas_editing_export import EditingExportService
from app.services.agent_canvas_ad_media import (
    AdMediaDraftValidationService,
    AdMediaRoleRegistry,
)
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_connected_authoring import AgentCanvasConnectedAuthoringService
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_node_execution import (
    GeneratedMediaPayload,
    build_default_node_dispatcher,
    generated_asset_publication_metadata,
)
from app.services.agent_canvas_provider_recovery import (
    ProviderPollResult,
    ProviderTaskRecoveryService,
)
from app.services.agent_canvas_provider_capabilities import (
    ProviderCapabilityError,
    ProviderCapabilityService,
)
from app.services.agent_canvas_provider_prompts import (
    AgentCanvasProviderPromptCompiler,
    list_agent_canvas_prompt_registrations,
)
from app.services.agent_canvas_production_plan import AgentCanvasProductionPlanService
from app.services.agent_canvas_references import AdReferenceBundleResolver
from app.services.agent_canvas_projects import AgentCanvasProjectService
from app.services.agent_canvas_runtime import (
    AgentCanvasRunService,
    CanvasRuntimeSnapshotService,
    DynamicCanvasScheduler,
)
from app.services.agent_canvas_run_snapshots import AgentCanvasRunIntentSnapshotService
from app.services.agent_canvas_command_compiler import AgentCommandPlanCompiler
from app.services.agent_canvas_command_replan import AgentCommandReplanService
from app.services.agent_canvas_commands import AgentCanvasCommandService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_conversation import (
    AgentConversationService,
    DeterministicDirectorGateway,
    PiDirectorGateway,
)
from app.services.agent_canvas_continuation_worker import (
    AgentCanvasContinuationWorker,
)
from app.services.agent_canvas_layout import AgentCanvasLayoutService
from app.services.agent_canvas_targets import AgentCanvasTargetService
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.agent_trace import V2AgentTraceWriter
from app.services.agent_canvas_variations import AgentCanvasVariationService
from app.services.model_selection import ModelSelectionService
from app.services.model_resolution import ModelResolutionService
from app.services.provider_model_bootstrap import ProviderModelBootstrapService
from app.services.provider_model_catalog import ProviderModelCatalogService
from app.services.durable_pi_run import DurablePiRunService
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient
from app.services.v2_provider_executor import V2ProviderExecutor


router = APIRouter(tags=["v2-agent-canvas"])


@dataclass(frozen=True)
class AgentCanvasRuntime:
    database: V2Database
    projects: AgentCanvasProjectService
    workflows: AgentCanvasWorkflowRepository
    nodes: AgentCanvasNodeService
    bindings: AgentCanvasBindingService
    connected_authoring: AgentCanvasConnectedAuthoringService
    connection_policy: AgentCanvasConnectionPolicyService
    assets: AgentCanvasAssetService
    targets: AgentCanvasTargetService
    conversations: AgentConversationService
    commands: AgentCanvasCommandService
    variations: AgentCanvasVariationService
    layout: AgentCanvasLayoutService
    conversation_repository: AgentCanvasConversationRepository
    video_skills: VideoSkillRegistry
    ad_media_validation: AdMediaDraftValidationService
    event_repository: EventRepository
    runtime_repository: AgentCanvasRuntimeRepository
    run_service: AgentCanvasRunService
    scheduler: DynamicCanvasScheduler
    runtime_snapshots: CanvasRuntimeSnapshotService
    provider_capabilities: ProviderCapabilityService
    provider_recovery: ProviderTaskRecoveryService
    editing_nodes: EditingNodeService
    editing_exports: EditingExportService
    editing_export_repository: AgentCanvasEditingExportRepository
    continuation_outbox: AgentCanvasContinuationOutboxRepository
    continuation_worker: AgentCanvasContinuationWorker


def get_agent_canvas_runtime(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AgentCanvasRuntime]:
    runtime = create_agent_canvas_runtime(settings)
    try:
        yield runtime
    finally:
        runtime.database.dispose()


def create_agent_canvas_runtime(settings: Settings) -> AgentCanvasRuntime:
    """Build one request/startup-scoped Agent Canvas runtime."""

    database = create_v2_database(settings.media_data_dir)
    model_repository = ProviderModelRepository(database)
    ProviderModelBootstrapService(settings, model_repository).bootstrap(
        now=datetime.now(timezone.utc).isoformat()
    )
    model_catalog = ProviderModelCatalogService(
        model_repository,
        provider_available=lambda provider_id: (
            provider_id == "fake"
            or (provider_id == "siliconflow" and bool(settings.siliconflow_api_key))
            or (
                provider_id == "volcengine_ark"
                and bool(
                    settings.llm_api_key
                    or settings.image_generation_api_key
                    or settings.video_generation_api_key
                )
            )
            or (provider_id == "tianpuyue" and bool(settings.bgm_api_key))
        ),
    )
    model_selection = ModelSelectionService(model_catalog)
    model_resolution = ModelResolutionService(
        model_selection,
        model_repository,
        allow_fake=(settings.agent_runtime_mode == "fake" or settings.media_mode == "mock"),
    )
    project_repository = ProjectRepository(database)
    event_repository = EventRepository(database)
    workflow_repository = AgentCanvasWorkflowRepository(
        database,
        project_repository,
        event_repository,
    )
    document_repository = AgentCanvasDocumentRepository(database)
    asset_repository = V2AssetLibraryRepository(database)
    asset_service = AgentCanvasAssetService(
        settings.media_data_dir,
        asset_repository,
        workflow_repository,
        media_facts_probe=(
            deterministic_media_facts_probe
            if settings.agent_runtime_mode == "fake" or settings.media_mode == "mock"
            else None
        ),
    )
    conversation_repository = AgentCanvasConversationRepository(
        database,
        event_repository,
    )
    continuation_outbox = AgentCanvasContinuationOutboxRepository(
        database,
        event_repository,
    )
    video_skills = VideoSkillRegistry()
    director_gateway = (
        DeterministicDirectorGateway()
        if settings.agent_runtime_mode == "fake"
        else PiDirectorGateway(
            DurablePiRunService(
                settings=settings,
                client=PiAgentRuntimeClient(
                    base_url=settings.agent_runtime_base_url,
                    internal_token=settings.agent_runtime_internal_token or "",
                    protocol_version=settings.agent_runtime_protocol_version,
                    connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                    read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                    run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                    max_event_bytes=settings.agent_runtime_max_event_bytes,
                    max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                ),
            ),
            timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            model_resolution=model_resolution,
        )
    )
    provider_capabilities = ProviderCapabilityService(model_catalog)
    connection_policy = AgentCanvasConnectionPolicyService()
    binding_service = AgentCanvasBindingService(
        workflow_repository,
        document_repository,
        asset_resolver=asset_service.resolve_asset,
        asset_version_resolver=asset_service.resolve_asset_version,
        binding_capability_validator=lambda target, input_types, reference_count: (
            provider_capabilities.validate_binding(
                target,
                required_input_types=input_types,
                reference_count=reference_count,
            )
        ),
        connection_policy=connection_policy,
    )
    runtime_repository = AgentCanvasRuntimeRepository(database, event_repository)
    editing_export_repository = AgentCanvasEditingExportRepository(database)
    provider_executor = V2ProviderExecutor(
        settings=settings,
        data_dir=settings.media_data_dir,
    )
    dispatcher = build_default_node_dispatcher(
        settings,
        provider_executor=provider_executor,
    )
    role_registry = AdMediaRoleRegistry()
    reference_resolver = AdReferenceBundleResolver(
        workflow_repository,
        asset_resolver=asset_service.resolve_asset,
    )
    prompt_compiler = AgentCanvasProviderPromptCompiler(role_registry)
    compiled_roles = {
        registration.semantic_role for registration in list_agent_canvas_prompt_registrations()
    }

    def prepare_media_context(node: CanvasNodeV2):
        contract = role_registry.get(node.semantic_role)
        bundle = reference_resolver.resolve(
            node.workflow_id,
            node.node_id,
            contract,
        )
        compiled = (
            prompt_compiler.compile(node, contract, bundle)
            if node.semantic_role in compiled_roles
            else None
        )
        return compiled, bundle

    def write_stage_trace(
        context,
        stage,
        output,
        error,
        started_at,
        finished_at,
    ) -> None:
        V2AgentTraceWriter(settings.media_data_dir, context.node.workflow_id).append(
            agent="provider_runtime",
            model=context.model_id,
            prompt="",
            output=output,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(
                0,
                int((finished_at - started_at).total_seconds() * 1_000),
            ),
            metadata={
                "trace_role": stage,
                "provider": context.provider_id,
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "model_resolution": (
                    context.model_resolution.model_dump(mode="json")
                    if context.model_resolution is not None
                    else None
                ),
            },
        )

    run_snapshots = AgentCanvasRunIntentSnapshotService(
        workflow_repository,
        runtime_repository,
    )
    scheduler = DynamicCanvasScheduler(
        workflow_repository,
        runtime_repository,
        binding_service,
        provider_capabilities,
        dispatcher,
        model_resolution=model_resolution,
        media_publisher=lambda context, payload, fingerprint: (
            asset_service.publish_generated_bytes(
                context.node.workflow_id,
                node_id=context.node.node_id,
                execution_id=context.execution_id,
                filename=payload.filename,
                mime_type=payload.mime_type,
                content=payload.content,
                fingerprint=fingerprint,
                source_semantic_role=context.node.semantic_role,
                publication_metadata={
                    **generated_asset_publication_metadata(context),
                    **dict(payload.metadata),
                },
            ).asset_id
        ),
        script_ready_publisher=lambda workflow_id, node_id: (
            conversation_repository.publish_script_artifact(
                workflow_id,
                script_node_id=node_id,
                source_turn_id=None,
            )
        ),
        text_ready_publisher=lambda node: _persist_text_document(
            document_repository,
            node,
        ),
        media_context_preparer=prepare_media_context,
        stage_trace_writer=write_stage_trace,
        run_snapshots=run_snapshots,
        image_limit=settings.v2_max_parallel_image_jobs,
        video_limit=settings.v2_max_parallel_video_jobs,
        audio_limit=settings.v2_max_parallel_audio_jobs,
        total_limit=settings.v2_max_parallel_generation_jobs,
    )

    def poll_provider_task(task) -> ProviderPollResult:
        descriptor = dict(task.result_descriptor)
        media_type = str(descriptor.get("media_type") or "")
        if media_type not in {"image", "video", "audio"} or not task.remote_task_id:
            return ProviderPollResult(
                status="failed",
                remote_task_id=task.remote_task_id,
                error_code="provider_task_invalid",
                error_message="Provider task descriptor is invalid.",
            )
        result = provider_executor.poll_minimal(
            workflow_id=task.workflow_id,
            media_type=media_type,
            remote_task_id=task.remote_task_id,
            provider_payload=dict(descriptor.get("provider_payload") or {}),
            result_descriptor=descriptor,
            download_media=False,
        )
        if result.status == "completed":
            return ProviderPollResult(
                status="succeeded",
                remote_task_id=task.remote_task_id,
                result_descriptor={**descriptor, **result.metadata},
            )
        if result.status == "waiting":
            return ProviderPollResult(
                status="waiting",
                remote_task_id=task.remote_task_id,
                result_descriptor=descriptor,
            )
        if bool(result.metadata.get("retryable")):
            raise RuntimeError(result.error_message or "Provider polling failed.")
        return ProviderPollResult(
            status="failed",
            remote_task_id=task.remote_task_id,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def download_provider_task(task) -> GeneratedMediaPayload:
        descriptor = dict(task.result_descriptor)
        media_type = str(descriptor.get("media_type") or "")
        extension = {"video": "mp4", "audio": "mp3"}.get(media_type)
        if extension is None or not task.remote_task_id:
            raise V2PersistenceError(
                "provider_result_unavailable",
                "Provider result cannot be downloaded.",
                stage="agent_canvas_provider_recovery",
            )
        relative_path = (
            Path("v2")
            / "runs"
            / task.workflow_id
            / "provider-results"
            / f"{task.task_id}.{extension}"
        )
        result = provider_executor.poll_minimal(
            workflow_id=task.workflow_id,
            media_type=media_type,
            remote_task_id=task.remote_task_id,
            provider_payload=dict(descriptor.get("provider_payload") or {}),
            result_descriptor=descriptor,
            download_media=True,
            output_relative_path=relative_path,
        )
        if result.status != "completed" or not result.local_file_path:
            raise V2PersistenceError(
                result.error_code or "provider_result_unavailable",
                result.error_message or "Provider result is unavailable.",
                stage="agent_canvas_provider_recovery",
            )
        path = (settings.media_data_dir / result.local_file_path).resolve()
        data_root = settings.media_data_dir.resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            raise V2PersistenceError(
                "provider_output_invalid",
                "Provider output path is outside managed storage.",
                stage="agent_canvas_provider_recovery",
            )
        return GeneratedMediaPayload(
            content=path.read_bytes(),
            mime_type={"video": "video/mp4", "audio": "audio/mpeg"}[media_type],
            filename=f"{task.node_id}.{extension}",
            metadata=descriptor,
        )

    provider_recovery = ProviderTaskRecoveryService(
        workflow_repository,
        runtime_repository,
        poller=poll_provider_task,
        downloader=download_provider_task,
        media_publisher=lambda context, payload, fingerprint: (
            asset_service.publish_generated_bytes(
                context.node.workflow_id,
                node_id=context.node.node_id,
                execution_id=context.execution_id,
                filename=payload.filename,
                mime_type=payload.mime_type,
                content=payload.content,
                fingerprint=fingerprint,
                source_semantic_role=context.node.semantic_role,
                publication_metadata={
                    **generated_asset_publication_metadata(context),
                    **dict(payload.metadata),
                },
            ).asset_id
        ),
        on_batch_reconciled=lambda execution_ids: [
            scheduler.resume(execution_id) for execution_id in execution_ids
        ],
    )
    editing_nodes = EditingNodeService(workflow_repository, asset_service.resolve_asset)
    editing_exports = EditingExportService(
        data_dir=settings.media_data_dir,
        workflows=workflow_repository,
        nodes=editing_nodes,
        inputs=EditingInputResolver(
            workflow_repository,
            asset_service.resolve_asset,
            asset_service.resolve_asset_path,
        ),
        assets=asset_service,
        exports=editing_export_repository,
        events=event_repository,
        renderer=AgentCanvasCompositionRenderer(settings),
    )

    run_service = AgentCanvasRunService(
        workflow_repository,
        runtime_repository,
        event_repository,
        run_snapshots=run_snapshots,
    )
    command_repository = AgentCanvasCommandRepository(
        database,
        event_repository,
        model_selection_validator=lambda node_type, model_selection_mode, model_ref: (
            model_selection.validate_selection(
                node_type=node_type,
                model_selection_mode=model_selection_mode,
                model_ref=model_ref,
            )
        ),
    )
    command_compiler = AgentCommandPlanCompiler()

    def queue_nodes(
        workflow_id: str,
        node_ids: tuple[str, ...],
        idempotency_key: str,
    ) -> tuple[str, ...]:
        accepted = run_service.start_or_extend(
            workflow_id,
            CanvasRunRequestV2(
                scope="selected_nodes",
                node_ids=node_ids,
                source_action="agent_command",
            ),
            idempotency_key=idempotency_key,
        )
        return (accepted.execution_id,)

    command_replan = (
        AgentCommandReplanService(
            commands=command_repository,
            conversations=conversation_repository,
            workflows=workflow_repository,
            compiler=command_compiler,
            gateway=director_gateway,
        )
        if isinstance(director_gateway, PiDirectorGateway)
        else None
    )
    command_service = AgentCanvasCommandService(
        command_repository,
        run_nodes=queue_nodes,
        replan=command_replan,
    )

    def validate_variation(
        source: CanvasNodeV2,
        request: CanvasVariationDraftUpsertV2,
    ) -> None:
        candidate = source.model_copy(
            update={
                "status": "draft",
                "title": request.title,
                "generation_prompt": request.generation_prompt,
                "model_selection_mode": request.model_selection_mode,
                "model_ref": request.model_ref,
                "parameters": request.parameters,
                "output_asset_id": None,
                "error": None,
            },
            deep=True,
        )
        try:
            model_selection.validate_authoring(candidate)
            provider_capabilities.resolve(
                candidate,
                binding_service.resolve_run_inputs(
                    source.workflow_id,
                    source.node_id,
                ),
            )
        except (ProviderCapabilityError, V2PersistenceError) as error:
            raise V2PersistenceError(
                "variation_model_incompatible",
                "Variation model is incompatible with its inputs.",
                stage="agent_canvas_variation_service",
            ) from error

    variation_service = AgentCanvasVariationService(
        workflow_repository,
        command_repository,
        variation_validator=validate_variation,
        run_node=lambda workflow_id, node_id, idempotency_key: run_service.start_or_extend(
            workflow_id,
            CanvasRunRequestV2(
                scope="selected_nodes",
                node_ids=(node_id,),
                source_action="variation_materialize",
            ),
            idempotency_key=idempotency_key,
        ),
    )
    conversation_service = AgentConversationService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        nodes=AgentCanvasNodeService(
            workflow_repository,
            model_selection=model_selection,
        ),
        gateway=director_gateway,
        video_skills=video_skills,
        context_assembler=AgentLocalContextAssembler(
            workflow_repository,
            asset_resolver=asset_service.resolve_asset,
            project_asset_lister=asset_service.list_project_assets,
        ),
        asset_resolver=asset_service.resolve_asset,
        connection_policy=connection_policy,
        command_compiler=command_compiler,
        command_service=command_service,
        run_nodes=queue_nodes,
        continuation_outbox=continuation_outbox,
    )
    continuation_worker = AgentCanvasContinuationWorker(
        continuation_outbox,
        process_turn=conversation_service.process_turn,
        worker_id=f"agent-canvas-continuation:{uuid4().hex}",
        fail_turn=lambda turn_id, code, message: conversation_repository.fail_turn(
            turn_id,
            code=code,
            message=message,
        ),
    )
    return AgentCanvasRuntime(
        database=database,
        projects=AgentCanvasProjectService(
            project_repository,
            workflow_repository,
            asset_service,
            conversation_repository,
            video_skills,
        ),
        workflows=workflow_repository,
        nodes=AgentCanvasNodeService(
            workflow_repository,
            model_selection=model_selection,
        ),
        bindings=binding_service,
        connected_authoring=AgentCanvasConnectedAuthoringService(
            workflow_repository,
            connection_policy,
            model_selection=model_selection,
            binding_capability_validator=lambda target, input_types, reference_count: (
                provider_capabilities.validate_binding(
                    target,
                    required_input_types=input_types,
                    reference_count=reference_count,
                )
            ),
        ),
        connection_policy=connection_policy,
        assets=asset_service,
        targets=AgentCanvasTargetService(workflow_repository, asset_service),
        conversations=conversation_service,
        commands=command_service,
        variations=variation_service,
        layout=AgentCanvasLayoutService(workflow_repository),
        conversation_repository=conversation_repository,
        video_skills=video_skills,
        ad_media_validation=AdMediaDraftValidationService(role_registry),
        event_repository=event_repository,
        runtime_repository=runtime_repository,
        run_service=run_service,
        scheduler=scheduler,
        runtime_snapshots=CanvasRuntimeSnapshotService(
            workflow_repository,
            runtime_repository,
            event_repository,
        ),
        provider_capabilities=provider_capabilities,
        provider_recovery=provider_recovery,
        editing_nodes=editing_nodes,
        editing_exports=editing_exports,
        editing_export_repository=editing_export_repository,
        continuation_outbox=continuation_outbox,
        continuation_worker=continuation_worker,
    )


@router.post(
    "/projects",
    response_model=ProjectCreateResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProjectCreateResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        created = runtime.projects.create(request, idempotency_key=idempotency_key)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(created.workflow_id, created.revision)
    return created


@router.get("/projects", response_model=ProjectV2ListResponse)
def list_projects(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    project_status: Annotated[
        Literal["active", "archived", "trashed"], Query(alias="status")
    ] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> ProjectV2ListResponse:
    try:
        return runtime.projects.list_projects(
            status=project_status,
            limit=limit,
            cursor=cursor,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get("/projects/{project_id}", response_model=ProjectV2)
def get_project(
    project_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> ProjectV2:
    try:
        project = runtime.projects.get_project(project_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectV2)
def update_project(
    project_id: str,
    request: ProjectV2UpdateRequest,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProjectV2:
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise _http_error("project_update_empty", 422, "Project update is empty.")
    try:
        project = runtime.projects.update_project(
            project_id,
            expected_version=_expected_project_version(if_match, project_id),
            changes=changes,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def trash_project(
    project_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    try:
        project = runtime.projects.trash_project(
            project_id,
            expected_version=_expected_project_version(if_match, project_id),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)


@router.post("/projects/{project_id}/restore", response_model=ProjectV2)
def restore_project(
    project_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProjectV2:
    try:
        project = runtime.projects.restore_project(
            project_id,
            expected_version=_expected_project_version(if_match, project_id),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = project_etag(project_id, project.project_version)
    return project


@router.get("/workflows/{workflow_id}", response_model=AgentCanvasWorkflowV2)
def get_workflow(
    workflow_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> AgentCanvasWorkflowV2:
    try:
        workflow = runtime.projects.get_workflow(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return workflow


@router.get(
    "/workflows/{workflow_id}/locators/resolve",
    response_model=AgentTargetResolutionV2,
)
def resolve_locator(
    workflow_id: str,
    locator: Annotated[str, Query(min_length=1)],
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> AgentTargetResolutionV2:
    try:
        return runtime.targets.resolve(workflow_id, locator)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.patch(
    "/workflows/{workflow_id}/layout",
    response_model=CanvasLayoutPatchResponseV2,
)
def patch_workflow_layout(
    workflow_id: str,
    request: CanvasLayoutPatchRequestV2,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasLayoutPatchResponseV2:
    try:
        return runtime.layout.update_layout(workflow_id, request)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/nodes",
    response_model=CanvasMutationResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    workflow_id: str,
    request: CanvasNodeCreateRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasMutationResponseV2:
    expected = _expected_revision(if_match, workflow_id)
    try:
        runtime.ad_media_validation.validate(
            node_type=request.node_type,
            semantic_role=request.semantic_role,
            structured_content=request.structured_content,
        )
        if request.source_asset_id is not None:
            runtime.assets.validate_asset_backed_node(
                request.source_asset_id,
                request.node_type,
            )
        node = runtime.nodes.create(
            workflow_id,
            request,
            expected_revision=expected,
        )
        workflow = runtime.projects.get_workflow(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow, node=node)


@router.get(
    "/workflows/{workflow_id}/nodes/{node_id}",
    response_model=CanvasNodeV2,
)
def get_node(
    workflow_id: str,
    node_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasNodeV2:
    try:
        node = runtime.workflows.get_node(workflow_id, node_id)
        if node.node_type == "editing":
            return node.model_copy(
                update={
                    "structured_content": runtime.editing_nodes.content(
                        workflow_id, node_id
                    ).model_dump(mode="json")
                }
            )
        return node
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.put(
    "/workflows/{workflow_id}/nodes/{node_id}/variation-draft",
    response_model=CanvasVariationDraftResponseV2,
)
def save_variation_draft(
    workflow_id: str,
    node_id: str,
    request: CanvasVariationDraftUpsertV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasVariationDraftResponseV2:
    try:
        result = runtime.variations.save(
            workflow_id,
            node_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, result.workflow_revision)
    return result


@router.delete(
    "/workflows/{workflow_id}/nodes/{node_id}/variation-draft",
    status_code=status.HTTP_204_NO_CONTENT,
)
def discard_variation_draft(
    workflow_id: str,
    node_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    try:
        runtime.variations.discard(
            workflow_id,
            node_id,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
        workflow = runtime.workflows.get_workflow(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/variation-draft/materialize",
    response_model=CanvasVariationMaterializeResponseV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def materialize_variation_draft(
    workflow_id: str,
    node_id: str,
    request: CanvasVariationMaterializeRequestV2,
    response: Response,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CanvasVariationMaterializeResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        result = runtime.variations.materialize(
            workflow_id,
            node_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if result.run is not None and result.run.get("execution_id"):
        background_tasks.add_task(
            runtime.scheduler.resume,
            str(result.run["execution_id"]),
        )
    response.headers["ETag"] = workflow_etag(workflow_id, result.workflow_revision)
    return result


@router.patch(
    "/workflows/{workflow_id}/nodes/{node_id}",
    response_model=CanvasMutationResponseV2,
)
def patch_node(
    workflow_id: str,
    node_id: str,
    request: CanvasNodePatchRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasMutationResponseV2:
    try:
        current = runtime.workflows.get_node(workflow_id, node_id)
        expected_revision = _expected_revision(if_match, workflow_id)
        if current.node_type == "editing" and request.structured_content is not None:
            raw_manifest = request.structured_content.get("manifest", request.structured_content)
            manifest = EditingManifestV2.model_validate(raw_manifest)
            node = runtime.editing_nodes.update_manifest(
                workflow_id,
                node_id,
                manifest,
                expected_revision=expected_revision,
            )
        else:
            runtime.ad_media_validation.validate(
                node_type=current.node_type,
                semantic_role=current.semantic_role,
                structured_content=(
                    request.structured_content
                    if request.structured_content is not None
                    else current.structured_content
                ),
            )
            node = runtime.nodes.patch(
                workflow_id,
                node_id,
                request,
                expected_revision=expected_revision,
            )
        workflow = runtime.projects.get_workflow(workflow_id)
    except ValueError as error:
        raise _http_error(
            "editing_manifest_invalid",
            422,
            "Editing manifest is invalid.",
        ) from error
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow, node=node)


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/export",
    response_model=EditingExportAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_editing_node(
    workflow_id: str,
    node_id: str,
    request: EditingExportRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EditingExportAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.editing_exports.start(
            workflow_id,
            node_id,
            request,
            idempotency_key=idempotency_key,
        )
        if accepted.status == "queued":
            background_tasks.add_task(
                runtime.editing_exports.resume,
                accepted.export_id,
            )
        return accepted
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/exports/{export_id}/cancel",
    response_model=EditingExportCancelResponseV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_editing_export(
    workflow_id: str,
    node_id: str,
    export_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> EditingExportCancelResponseV2:
    try:
        return runtime.editing_exports.cancel(workflow_id, node_id, export_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.delete(
    "/workflows/{workflow_id}/nodes/{node_id}",
    response_model=CanvasMutationResponseV2,
)
def delete_node(
    workflow_id: str,
    node_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasMutationResponseV2:
    try:
        workflow = runtime.nodes.delete(
            workflow_id,
            node_id,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow)


@router.post(
    "/workflows/{workflow_id}/connected-nodes",
    response_model=CanvasConnectedNodeCreateResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def create_connected_node(
    workflow_id: str,
    request: CanvasConnectedNodeCreateRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CanvasConnectedNodeCreateResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        created = runtime.connected_authoring.create_connected_node(
            workflow_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, created.revision)
    return created


@router.patch(
    "/workflows/{workflow_id}/bindings/{binding_id}",
    response_model=CanvasBindingMutationResponseV2,
)
def patch_binding(
    workflow_id: str,
    binding_id: str,
    request: CanvasBindingPatchRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CanvasBindingMutationResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        mutation = runtime.bindings.patch(
            workflow_id,
            binding_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
            request_fingerprint=sha256(request.model_dump_json().encode()).hexdigest(),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, mutation.revision)
    return mutation


@router.get(
    "/canvas/connection-policy",
    response_model=CanvasConnectionPolicyV2,
)
def get_canvas_connection_policy(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasConnectionPolicyV2:
    return runtime.connection_policy.public_policy()


@router.post(
    "/workflows/{workflow_id}/bindings",
    response_model=CanvasMutationResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def create_binding(
    workflow_id: str,
    request: CanvasBindingCreateRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasMutationResponseV2:
    try:
        binding = runtime.bindings.create(
            workflow_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
        workflow = runtime.projects.get_workflow(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow, binding=binding)


@router.delete(
    "/workflows/{workflow_id}/bindings/{binding_id}",
    response_model=CanvasMutationResponseV2,
)
def delete_binding(
    workflow_id: str,
    binding_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CanvasMutationResponseV2:
    try:
        workflow = runtime.bindings.delete(
            workflow_id,
            binding_id,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow)


@router.post(
    "/workflows/{workflow_id}/assets/upload",
    response_model=ProjectAssetUploadResponseV2,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProjectAssetUploadResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        parsed = ProjectAssetUploadMetadataV2.model_validate_json(metadata)
        runtime.projects.get_workflow(workflow_id)
        asset = runtime.assets.upload_bytes(
            workflow_id,
            filename=file.filename or "upload",
            mime_type=file.content_type or "",
            content=await file.read(),
            title=parsed.title,
            media_type=parsed.media_type,
            idempotency_key=idempotency_key,
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise _http_error("asset_upload_invalid", 422, "Asset metadata is invalid.") from error
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return ProjectAssetUploadResponseV2(workflow_id=workflow_id, asset=asset)


@router.get(
    "/workflows/{workflow_id}/assets",
    response_model=ProjectAssetListResponseV2,
)
def list_project_assets(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> ProjectAssetListResponseV2:
    try:
        runtime.projects.get_workflow(workflow_id)
        assets = runtime.assets.list_project_assets(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return ProjectAssetListResponseV2(workflow_id=workflow_id, assets=assets)


@router.get("/assets/recommended", response_model=ImageLibraryListResponseV2)
def list_recommended_assets(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    category: Annotated[str | None, Query()] = None,
) -> ImageLibraryListResponseV2:
    return _image_library_response(
        runtime.assets.list_images(scope="recommended", category=category)
    )


@router.get("/assets/mine", response_model=ImageLibraryListResponseV2)
def list_my_assets(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    category: Annotated[str | None, Query()] = None,
) -> ImageLibraryListResponseV2:
    return _image_library_response(runtime.assets.list_images(scope="my", category=category))


@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    try:
        content = runtime.assets.open_content(asset_id, range_header=range_header)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return Response(
        content=content.body,
        status_code=content.status_code,
        media_type=content.media_type,
        headers=content.headers,
    )


@router.post(
    "/assets/{asset_id}/save-to-library",
    response_model=AssetLibraryEntityDetailV2,
    status_code=status.HTTP_201_CREATED,
)
def save_asset_to_library(
    asset_id: str,
    request: SaveImageToLibraryRequestV2,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AssetLibraryEntityDetailV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        return runtime.assets.save_image_to_library(
            asset_id,
            category=request.category,
            display_name=request.display_name,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> None:
    try:
        runtime.assets.delete_asset(asset_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/chat/timeline",
    response_model=ChatTimelineListResponseV2,
)
def get_chat_timeline(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ChatTimelineListResponseV2:
    try:
        timeline = runtime.conversations.get_timeline(
            workflow_id,
            after_seq=after_seq,
            limit=limit,
        )
        if timeline.creative_session is None:
            return timeline
        return timeline.model_copy(
            update={
                "creative_session": _creative_session_with_readiness(
                    runtime,
                    timeline.creative_session,
                )
            }
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/chat/messages",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_chat_message(
    workflow_id: str,
    request: ChatMessageRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.conversations.submit_message(
            workflow_id,
            text=request.text,
            mentioned_node_ids=request.mentioned_node_ids,
            mentioned_image_asset_ids=request.mentioned_image_asset_ids,
            video_skill_run_id=request.video_skill_run_id,
            auto_continue=request.auto_continue,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    background_tasks.add_task(
        _process_agent_turn_and_resume,
        runtime,
        workflow_id,
        accepted.turn_id,
    )
    return accepted


@router.get(
    "/workflows/{workflow_id}/chat/proposals/{proposal_id}",
    response_model=ConceptProposalV2,
)
def get_chat_proposal(
    workflow_id: str,
    proposal_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> ConceptProposalV2:
    try:
        return runtime.conversations.get_proposal(workflow_id, proposal_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/chat/turns/{turn_id}",
    response_model=ChatTurnV2,
)
def get_chat_turn(
    workflow_id: str,
    turn_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> ChatTurnV2:
    try:
        turn = runtime.conversations.get_turn(turn_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if turn.workflow_id != workflow_id:
        raise _http_error("chat_turn_not_found", 404, "Chat turn was not found.")
    return turn


@router.post(
    "/workflows/{workflow_id}/chat/proposals/{proposal_id}/actions",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def act_on_chat_proposal(
    workflow_id: str,
    proposal_id: str,
    request: ProposalActionRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.conversations.act_on_proposal(
            workflow_id,
            proposal_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    background_tasks.add_task(
        _process_agent_turn_and_resume,
        runtime,
        workflow_id,
        accepted.turn_id,
    )
    return accepted


@router.post(
    "/workflows/{workflow_id}/chat/command-plans/{plan_id}/actions",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def act_on_command_plan(
    workflow_id: str,
    plan_id: str,
    request: AgentCommandPlanActionRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.conversations.act_on_command_plan(
            workflow_id,
            plan_id,
            action=request.action,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    background_tasks.add_task(
        _process_agent_turn_and_resume,
        runtime,
        workflow_id,
        accepted.turn_id,
    )
    return accepted


@router.post(
    "/workflows/{workflow_id}/chat/guided-actions/{action_id}/apply",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def apply_guided_action(
    workflow_id: str,
    action_id: str,
    request: GuidedActionApplyRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.conversations.act_on_guided_action(
            workflow_id,
            action_id,
            confirmed=request.confirmed,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    background_tasks.add_task(
        _process_agent_turn_and_resume,
        runtime,
        workflow_id,
        accepted.turn_id,
    )
    return accepted


@router.post(
    "/workflows/{workflow_id}/skill-runs",
    response_model=VideoSkillRunV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_video_skill_run(
    workflow_id: str,
    request: VideoSkillRunCreateRequestV2,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> VideoSkillRunV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        runtime.workflows.get_workflow(workflow_id)
        loaded = runtime.video_skills.load(request.skill_id, request.skill_version)
        skill_run = runtime.conversation_repository.create_skill_run(
            workflow_id,
            skill_id=loaded.manifest.skill_id,
            skill_version=loaded.manifest.version,
            recipe_topics=tuple(loaded.recipe["planning_topics"]),
            source_skill_run_id=request.source_skill_run_id,
            idempotency_key=idempotency_key,
        )
        CreativeDirectionService().ensure_snapshot(
            runtime.conversation_repository,
            skill_run,
            loaded,
        )
        return skill_run
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get("/video-skills", response_model=VideoSkillSummaryListV2)
def list_video_skills(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    category: Annotated[str | None, Query(max_length=80)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VideoSkillSummaryListV2:
    try:
        return runtime.video_skills.list_public_catalog(
            category=category,
            cursor=cursor,
            limit=limit,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get("/video-skills/{skill_id}", response_model=VideoSkillPublicDetailV2)
def get_video_skill(
    skill_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> VideoSkillPublicDetailV2:
    try:
        return runtime.video_skills.get_public_detail(skill_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/creative-session",
    response_model=CreativeSessionStateV2,
)
def get_creative_session(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CreativeSessionStateV2:
    try:
        session = runtime.conversation_repository.get_creative_session(workflow_id)
        return _creative_session_with_readiness(runtime, session)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=CanvasRunAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Draft Canvas Nodes",
    description=(
        "Runs Draft Text, Script, Image, Video, and Audio Nodes. Editing Nodes are export-only."
    ),
)
def start_canvas_run(
    workflow_id: str,
    request: CanvasRunRequestV2,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CanvasRunAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.run_service.start_or_extend(
            workflow_id,
            request,
            idempotency_key=idempotency_key,
        )
        background_tasks.add_task(runtime.scheduler.resume, accepted.execution_id)
        return accepted
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/runs/{execution_id}/cancel",
    response_model=CanvasRunCancelResponseV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_canvas_run(
    workflow_id: str,
    execution_id: str,
    request: CanvasRunCancelRequestV2,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasRunCancelResponseV2:
    try:
        execution = runtime.runtime_repository.get_execution(execution_id)
        if execution.workflow_id != workflow_id:
            raise V2PersistenceError(
                "execution_not_found",
                "Execution was not found.",
                stage="agent_canvas_run_api",
            )
        return runtime.scheduler.cancel(execution_id, reason=request.reason)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/runtime",
    response_model=CanvasRuntimeSnapshotV2,
)
def get_canvas_runtime_snapshot(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasRuntimeSnapshotV2:
    try:
        return runtime.runtime_snapshots.get(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/events",
    response_model=CanvasRuntimeEventListV2,
)
def list_canvas_runtime_events(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CanvasRuntimeEventListV2:
    try:
        runtime.workflows.get_workflow(workflow_id)
        _validate_event_cursor(runtime.event_repository, workflow_id, after_seq)
        events = runtime.event_repository.list_after(workflow_id, after_seq)[:limit]
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    items = tuple(
        CanvasRuntimeEventV2(
            sequence_no=event.seq,
            workflow_id=event.workflow_id,
            event_type=event.event_type,
            project_id=event.project_id,
            execution_id=event.execution_id,
            node_id=event.node_id,
            binding_id=event.binding_id,
            asset_id=event.asset_id,
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            action_id=event.action_id,
            trace_id=event.trace_id,
            span_id=event.span_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    )
    return CanvasRuntimeEventListV2(
        items=items,
        next_cursor=items[-1].sequence_no if items else after_seq,
    )


@router.get("/workflows/{workflow_id}/events/stream")
def stream_canvas_runtime_events(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    runtime.workflows.get_workflow(workflow_id)
    _validate_event_cursor(runtime.event_repository, workflow_id, after_seq)

    async def body():
        cursor = after_seq
        while True:
            events = runtime.event_repository.list_after(workflow_id, cursor)
            if not events:
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
                continue
            for event in events:
                item = CanvasRuntimeEventV2(
                    sequence_no=event.seq,
                    workflow_id=event.workflow_id,
                    event_type=event.event_type,
                    project_id=event.project_id,
                    execution_id=event.execution_id,
                    node_id=event.node_id,
                    binding_id=event.binding_id,
                    asset_id=event.asset_id,
                    conversation_id=event.conversation_id,
                    turn_id=event.turn_id,
                    action_id=event.action_id,
                    trace_id=event.trace_id,
                    span_id=event.span_id,
                    payload=event.payload,
                    created_at=event.created_at,
                )
                cursor = event.seq
                yield (
                    f"id: {item.sequence_no}\n"
                    f"event: {item.event_type}\n"
                    f"data: {item.model_dump_json()}\n\n"
                )

    return StreamingResponse(body(), media_type="text/event-stream")


def _validate_event_cursor(
    events: EventRepository,
    workflow_id: str,
    after_seq: int,
) -> None:
    if after_seq == 0:
        return
    oldest = events.min_seq(workflow_id)
    if oldest and oldest > after_seq + 1:
        raise _http_error(
            "event_cursor_expired",
            409,
            "Event cursor is older than the retained event window.",
            details={"runtime_refresh_required": True},
        )


@router.get(
    "/provider-models/capabilities",
    response_model=CanvasProviderModelCapabilityListV2,
    deprecated=True,
    summary="List Canvas Provider Capabilities (Compatibility)",
    description=(
        "Compatibility projection of the canonical provider model catalog. "
        "Use GET /api/v1/models for new integrations."
    ),
)
def list_canvas_provider_capabilities(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    output_type: Annotated[str | None, Query()] = None,
    input_types: Annotated[str, Query()] = "",
    include_unavailable: Annotated[bool, Query()] = False,
) -> CanvasProviderModelCapabilityListV2:
    requested_inputs = frozenset(item.strip() for item in input_types.split(",") if item.strip())
    if output_type is not None and output_type not in {"image", "video", "audio"}:
        raise _http_error(
            "invalid_capability_filter",
            422,
            "Provider capability filter is invalid.",
        )
    if not requested_inputs.issubset({"text", "image", "video", "audio"}):
        raise _http_error(
            "invalid_capability_filter",
            422,
            "Provider capability filter is invalid.",
        )
    return runtime.provider_capabilities.list(
        output_type=output_type,
        input_types=requested_inputs,
        include_unavailable=include_unavailable,
    )


def _process_agent_turn_and_resume(
    runtime: AgentCanvasRuntime,
    workflow_id: str,
    turn_id: str,
) -> None:
    runtime.conversations.process_turn(turn_id)
    active = runtime.runtime_repository.get_active_execution(workflow_id)
    if active is not None:
        runtime.scheduler.resume(active.execution_id)


def _persist_text_document(
    documents: AgentCanvasDocumentRepository,
    node: CanvasNodeV2,
) -> None:
    content = node.structured_content
    if content is None or not isinstance(content.get("content"), str):
        raise V2PersistenceError(
            "text_output_invalid",
            "Text Node output must contain text content.",
            stage="agent_canvas_text_document",
        )
    documents.put(
        workflow_id=node.workflow_id,
        node_id=node.node_id,
        document_kind="text",
        content=content,
        content_hash=sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        node_revision=node.revision,
    )


def _expected_revision(value: str | None, workflow_id: str) -> int:
    try:
        parsed = parse_workflow_if_match(value, workflow_id, required=True)
    except V2PreconditionError as error:
        raise _http_error(error.code, error.status_code, str(error)) from error
    assert parsed is not None
    return parsed


def _expected_project_version(value: str | None, project_id: str) -> int:
    try:
        return parse_project_if_match(value, project_id)
    except V2PreconditionError as error:
        raise _http_error(error.code, error.status_code, str(error)) from error


def _persistence_http_error(error: V2PersistenceError) -> HTTPException:
    status_code = {
        "project_not_found": 404,
        "project_not_trashed": 409,
        "project_state_conflict": 412,
        "project_cursor_invalid": 422,
        "project_page_invalid": 422,
        "project_update_invalid": 422,
        "workflow_not_found": 404,
        "node_not_found": 404,
        "binding_not_found": 404,
        "asset_not_found": 404,
        "asset_not_ready": 409,
        "target_not_found": 404,
        "target_type_not_supported": 422,
        "locator_invalid": 422,
        "unsupported_canvas_model": 422,
        "workflow_revision_conflict": 412,
        "idempotency_conflict": 409,
        "variation_source_not_ready": 409,
        "variation_source_media_type_unsupported": 422,
        "variation_model_incompatible": 409,
        "model_selection_invalid": 422,
        "model_not_found": 409,
        "model_unavailable": 409,
        "model_default_not_configured": 409,
        "model_capability_mismatch": 409,
        "agent_model_incompatible": 409,
        "variation_draft_not_found": 404,
        "variation_materialization_conflict": 409,
        "layout_revision_conflict": 409,
        "layout_node_not_found": 404,
        "layout_position_invalid": 422,
        "agent_command_plan_not_found": 404,
        "agent_command_plan_already_resolved": 409,
        "agent_command_confirmation_required": 409,
        "agent_command_confirmation_invalidated": 409,
        "agent_command_replan_exhausted": 409,
        "guided_action_not_found": 404,
        "guided_action_already_applied": 409,
        "guided_action_invalid": 422,
        "confirmation_required": 409,
        "ready_node_immutable": 409,
        "ready_node_inputs_immutable": 409,
        "binding_cycle_detected": 409,
        "binding_media_incompatible": 422,
        "binding_model_incompatible": 409,
        "canvas_connection_incompatible": 422,
        "canvas_connection_cycle": 409,
        "canvas_connection_duplicate": 409,
        "canvas_input_role_invalid": 422,
        "canvas_reference_limit_exceeded": 422,
        "provider_inputs_unsupported": 409,
        "asset_media_incompatible": 422,
        "asset_library_media_incompatible": 422,
        "invalid_semantic_role": 422,
        "semantic_role_node_type_mismatch": 422,
        "invalid_role_content": 422,
        "scene_design_board_contract_invalid": 422,
        "storyboard_grid_contract_invalid": 422,
        "reference_cardinality_exceeded": 422,
        "asset_is_referenced": 409,
        "node_type_mismatch": 422,
        "editing_manifest_invalid": 422,
        "editing_duplicate_bgm": 409,
        "editing_audio_role_invalid": 422,
        "editing_manifest_revision_conflict": 409,
        "editing_no_ready_video": 409,
        "editing_export_already_active": 409,
        "editing_export_not_found": 404,
        "editing_export_already_terminal": 409,
        "editing_export_cancel_failed": 409,
        "asset_range_invalid": 416,
        "asset_range_unsatisfiable": 416,
        "mentioned_node_not_found": 422,
        "mentioned_asset_not_found": 422,
        "mentioned_asset_media_type_unsupported": 422,
        "chat_turn_not_found": 404,
        "proposal_not_found": 404,
        "proposal_not_pending": 409,
        "proposal_option_not_found": 422,
        "proposal_revision_conflict": 409,
        "video_skill_not_found": 404,
        "skill_not_found": 404,
        "skill_catalog_cursor_invalid": 422,
        "skill_catalog_page_invalid": 422,
        "agent_skill_manifest_invalid": 503,
        "agent_skill_file_missing": 503,
        "agent_skill_digest_mismatch": 503,
        "execution_not_found": 404,
        "execution_already_terminal": 409,
        "execution_cancel_failed": 503,
        "execution_persistence_failed": 503,
        "node_not_runnable": 422,
        "node_already_ready": 409,
        "node_already_working": 409,
        "failed_node_retry_required": 409,
        "node_model_incompatible": 409,
        "upstream_inputs_not_ready": 409,
        "node_executor_unavailable": 503,
    }.get(error.code, 503)
    details = getattr(error, "details", None)
    return _http_error(
        error.code,
        status_code,
        str(error),
        details=details if isinstance(details, dict) else None,
    )


def _http_error(
    code: str,
    status_code: int,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


def _image_library_response(items) -> ImageLibraryListResponseV2:
    return ImageLibraryListResponseV2(items=tuple(item.model_dump(mode="json") for item in items))


def _creative_session_with_readiness(
    runtime: AgentCanvasRuntime,
    session: CreativeSessionStateV2,
) -> CreativeSessionStateV2:
    """Project readiness from canonical workflow, runtime, and Asset facts."""

    if session.active_recipe is None:
        return session
    workflow = runtime.workflows.get_workflow(session.workflow_id)
    readiness = AgentCanvasProductionPlanService().readiness(
        session.active_recipe,
        workflow=workflow,
        runtime=runtime.runtime_snapshots.get(session.workflow_id),
        assets=runtime.assets.list_project_assets(session.workflow_id),
    )
    return session.model_copy(update={"readiness": readiness})
