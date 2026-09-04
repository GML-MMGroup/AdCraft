"""Public V2 Agent Canvas authoring and project-media endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, cast
from uuid import uuid4
from time import monotonic

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse

from app.api.v2.etag import (
    V2PreconditionError,
    parse_project_if_match,
    parse_requirement_if_match,
    parse_workflow_if_match,
    project_etag,
    requirement_ledger_etag,
    workflow_etag,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.core.config import Settings, get_settings
from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.agent_canvas_editing_repository import (
    AgentCanvasEditingExportRepository,
)
from app.persistence.agent_canvas_editing_commit_repository import (
    AgentCanvasEditingExportCommitRepository,
)
from app.persistence.agent_canvas_runtime_repository import (
    AgentCanvasRuntimeRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_decision_bundle_repository import (
    AgentCanvasDecisionBundleRepository,
)
from app.persistence.agent_canvas_capability_proposal_repository import (
    AgentCanvasCapabilityProposalRepository,
)
from app.persistence.agent_canvas_capability_supersession_repository import (
    AgentCanvasCapabilitySupersessionRepository,
)
from app.services.agent_canvas_internal_document_checkpoint import (
    AgentCanvasInternalDocumentCheckpointPublisher,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.agent_canvas_guided_media_resume_repository import (
    AgentCanvasGuidedMediaResumeRepository,
)
from app.persistence.agent_canvas_production_closure_repository import (
    AgentCanvasProductionClosureRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.agent_canvas_execution_settings_repository import (
    AgentCanvasExecutionSettingsRepository,
)
from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
)
from app.persistence.agent_working_document_repository import (
    AgentWorkingDocumentRepository,
)
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database, create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_presentation_repository import PresentationStreamRepository
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
from app.schemas.agent_canvas_editing_output_reuse import (
    EditingExportOutputReuseRequestV2,
    EditingExportOutputReuseResponseV2,
)
from app.schemas.agent_canvas_conversation import (
    AgentCommandPlanActionRequestV2,
    ChatMessageRequestV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnRetryRequestV1,
    ChatTurnV2,
    ConceptProposalV2,
    DeferTopicActionV2,
    DelegateChoiceActionV2,
    ExcludeElementActionV2,
    GuidedActionApplyRequestV2,
    ProposalActionRequestV2,
    SelectOptionActionV2,
    VideoSkillRunCreateRequestV2,
    VideoSkillRunV2,
)
from app.schemas.agent_canvas_guidance import (
    ContinuationTurnRetrySnapshotV1,
    GuidanceAdvanceRequestV1,
)
from app.schemas.agent_canvas_decision_bundles import (
    DecisionBundleActionAcceptedV1,
    DecisionBundleActionRequestV1,
    DecisionBundleV1,
)
from app.schemas.agent_canvas_creative_session import (
    GuidedSessionStateV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidedAcceptedReferenceV1,
    GuidedConceptChoiceV2,
    GuidedConceptSubmitV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
    GuidedMediaReviewSubmitV1,
)
from app.schemas.agent_canvas_guided_references import (
    ReferenceCandidateKindV2,
    ReferenceCandidateListResponseV2,
    ReferenceCandidateScopeV2,
)
from app.schemas.agent_canvas_guided_product import (
    GuidedProductAssetVersionRefV1,
    GuidedProductInputCommitRequestV1,
    GuidedProductInputCommitResponseV1,
)
from app.schemas.agent_canvas_execution_settings import (
    AgentExecutionSettingsPatchV2,
    AgentExecutionSettingsV2,
)
from app.schemas.agent_canvas_requirements import (
    RequirementLedgerPatchRequestV1,
    RequirementLedgerResponseV1,
)
from app.schemas.agent_working_documents import (
    AgentWorkingDocumentKindV2,
    AgentWorkingDocumentPageV2,
    AgentWorkingDocumentV2,
)
from app.schemas.agent_canvas_video_skills import (
    VideoSkillCatalogResponseV2,
    VideoSkillPublicDetailV2,
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
from app.schemas.agent_canvas_post_ready_checkpoint import CanvasPostReadyCheckpointV2
from app.schemas.agent_canvas_presentation import SafePresentationDeltaV1
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
from app.services.project_cover_authority import ProjectCoverAuthorityService
from app.services.project_cover_renditions import ProjectCoverRenditionPrewarmer
from app.services.agent_canvas_guided_product import GuidedProductInputCommitService
from app.services.agent_canvas_guided_reference import GuidedReferenceSourceService
from app.services.agent_canvas_guided_reference_candidates import (
    GuidedReferenceCandidateService,
)
from app.persistence.agent_canvas_guided_reference_repository import (
    AgentCanvasGuidedReferenceRepository,
)
from app.persistence.agent_canvas_guided_product_repository import (
    AgentCanvasGuidedProductRepository,
)
from app.services.product_upload_multiview_compiler import ProductUploadMultiviewCompiler
from app.tools.ffmpeg import FfmpegTool
from app.services.v2_final_composition_renderer import V2MediaProbe
from app.services.v2_asset_renditions import V2AssetRenditionService
from app.services.agent_canvas_accepted_background import (
    AcceptedBackgroundOperation,
    AcceptedBackgroundResourceType,
    AcceptedBackgroundWork,
    AgentCanvasAcceptedBackgroundRunner,
)
from app.services.agent_canvas_auto_run import AgentCanvasAutoRunDispatcher
from app.services.agent_canvas_composition_renderer import (
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import EditingInputResolver, EditingNodeService
from app.services.agent_canvas_editing_response_projector import EditingResponseProjector
from app.services.agent_canvas_editing_export import EditingExportService
from app.services.agent_canvas_editing_commit import AgentCanvasEditingExportCommitService
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
from app.services.agent_canvas_provider_submission import ProviderSubmissionIntentService
from app.persistence.agent_canvas_post_ready_repository import (
    AgentCanvasPostReadyEffectRepository,
)
from app.persistence.agent_canvas_post_ready_checkpoint_repository import (
    AgentCanvasPostReadyCheckpointRepository,
)
from app.persistence.agent_canvas_result_commit_repository import (
    AgentCanvasResultCommitRepository,
)
from app.services.agent_canvas_execution_result_commit import (
    AgentCanvasExecutionResultCommitService,
)
from app.services.agent_canvas_output_preparation import AgentCanvasOutputPreparationService
from app.services.agent_canvas_post_ready_effects import AgentCanvasPostReadyEffectWorker
from app.services.agent_canvas_post_ready_checkpoint import (
    AgentCanvasPostReadyCheckpointService,
)
from app.schemas.agent_canvas_media_review_authority import (
    CanvasPostReadyEffectDispositionV1,
)
from app.schemas.agent_canvas_prompt_preparation_dispatch import (
    PromptPreparationDispatchV1,
)
from app.services.agent_canvas_provider_capabilities import (
    ProviderCapabilityError,
    ProviderCapabilityService,
)
from app.services.agent_canvas_provider_prompts import (
    AgentCanvasProviderPromptCompiler,
    list_agent_canvas_prompt_registrations,
)
from app.services.agent_canvas_references import AdReferenceBundleResolver
from app.services.agent_canvas_projects import AgentCanvasProjectService
from app.services.agent_canvas_requirements import AgentCanvasRequirementService
from app.services.agent_canvas_runtime import (
    AgentCanvasRunService,
    CanvasRuntimeSnapshotService,
    DynamicCanvasScheduler,
)
from app.services.agent_canvas_run_snapshots import AgentCanvasRunIntentSnapshotService
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_world_setting_context import WorldSettingContextResolverV2
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)
from app.services.agent_canvas_storyboard_progression import (
    ProgressiveStoryboardReadyService,
)
from app.services.agent_canvas_storyboard_fanout_activation import (
    StoryboardFanoutActivationService,
)
from app.services.agent_canvas_command_compiler import AgentCommandPlanCompiler
from app.services.agent_canvas_command_replan import AgentCommandReplanService
from app.services.agent_canvas_commands import AgentCanvasCommandService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_style_activation import StyleSkillActivationService
from app.services.agent_canvas_conversation import (
    AgentConversationService,
    DeterministicVideoAgentGateway,
    PiVideoAgentGateway,
    VideoAgentGateway,
)
from app.services.chat_turn_retry import ChatTurnRetryService
from app.services.agent_canvas_guidance_advance import GuidanceAdvanceService
from app.services.agent_canvas_guided_interactions import GuidedInteractionService
from app.services.agent_canvas_guided_media_confirmation import (
    GuidedMediaConfirmationService,
)
from app.services.agent_canvas_guided_media_review import (
    GuidedMediaPlanActionService,
    GuidedMediaReviewActionService,
    GuidedMediaReviewCoordinator,
)
from app.services.agent_canvas_guided_media_resume import (
    GuidedMediaConfirmationResumeWorker,
)
from app.services.agent_canvas_guided_final_completion import (
    GuidedFinalCompletionService,
)
from app.services.agent_canvas_guided_production_closure import (
    GuidedProductionClosureService,
)
from app.services.agent_canvas_guidance_post_ready import GuidancePostReadyGate
from app.services.agent_canvas_guidance_awaiting import GuidanceAwaitingService
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
from app.services.agent_canvas_prompt_preparation_worker import (
    AgentCanvasPromptPreparationWorker,
)
from app.services.agent_canvas_presentation import PresentationStreamPublisher
from app.services.agent_canvas_continuation_worker import (
    AgentCanvasContinuationWorker,
)
from app.services.agent_canvas_capability_execution import CapabilityExecutionService
from app.services.agent_canvas_capability_execution import capability_context_from_envelope
from app.services.agent_canvas_capability_dispatch import CapabilityDispatchService
from app.services.agent_canvas_materialization_publication import (
    CapabilityMaterializationPublicationService,
)
from app.services.agent_canvas_materialization_prompt_barrier import (
    AgentCanvasMaterializationPromptPreparationBarrier,
)
from app.services.agent_canvas_materialization_commit import (
    AgentCanvasMaterializationCommitService,
)
from app.services.agent_canvas_materialization_runtime import (
    QuickMediaMaterializationRunner,
    materialization_context_from_state,
)
from app.services.agent_canvas_proposal_publication import ProposalPublicationRunner
from app.services.agent_canvas_production_journey_reducer import (
    GuidedProductionJourneyReducer,
)
from app.services.agent_canvas_production_journey_orchestration import (
    GuidedProductionJourneyService,
)
from app.services.agent_canvas_guided_editing import GuidedEditingPreparationService
from app.schemas.agent_canvas_materialization import ProposalPublicationEnvelopeV1
from app.services.agent_canvas_next_action import DurableNextActionExecutionService
from app.services.agent_canvas_execution_settings import (
    AgentCanvasExecutionSettingsService,
)
from app.services.agent_working_documents import AgentWorkingDocumentService
from app.services.agent_canvas_layout import AgentCanvasLayoutService
from app.services.agent_canvas_targets import AgentCanvasTargetService
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.agent_canvas_video_parameter_compiler import (
    AgentCanvasVideoParameterCompiler,
    DeterministicVideoParameterIntentGateway,
    PiVideoParameterIntentGateway,
)
from app.services.agent_trace import V2AgentTraceWriter
from app.services.agent_canvas_variations import AgentCanvasVariationService
from app.services.agent_canvas_editing_output_reuse import EditingExportOutputReuseService
from app.services.model_selection import ModelSelectionService
from app.services.model_resolution import ModelResolutionService
from app.services.provider_adapter_registry import build_trusted_provider_adapter_registry
from app.services.provider_model_bootstrap import ProviderModelBootstrapService
from app.services.provider_model_catalog import ProviderModelCatalogService
from app.services.durable_pi_run import DurablePiRunService
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient
from app.services.v2_provider_executor import V2ProviderExecutor


router = APIRouter(tags=["v2-agent-canvas"])


def _resolve_storyboard_video_audio_constraints(
    requirement_service: object,
    conversation_repository: object,
    workflow_id: str,
) -> dict[str, object]:
    """Load the current typed Video constraints for storyboard fan-out."""

    current = requirement_service.get_current(workflow_id)
    constraints = {str(control.control): control.value for control in current.hard_controls}
    if current.identity_safety_decision is not None:
        constraints["identity_safety_decision"] = current.identity_safety_decision.model_dump(
            mode="json"
        )
    snapshot = conversation_repository.get_active_creative_direction_snapshot(workflow_id)
    public_skill = snapshot.global_direction.get("public_skill")
    if isinstance(public_skill, dict):
        mode = public_skill.get("video_representation_mode")
        if mode is not None:
            constraints["_video_skill_representation_mode"] = mode
            constraints["_video_skill_representation_source_id"] = (
                f"{snapshot.source_skill_id}:{snapshot.source_skill_version}"
            )
    return constraints


@dataclass(frozen=True)
class AgentCanvasRuntime:
    database: V2Database
    projects: AgentCanvasProjectService
    workflows: AgentCanvasWorkflowRepository
    requirements: AgentCanvasRequirementService
    nodes: AgentCanvasNodeService
    bindings: AgentCanvasBindingService
    connected_authoring: AgentCanvasConnectedAuthoringService
    connection_policy: AgentCanvasConnectionPolicyService
    assets: AgentCanvasAssetService
    guided_product_inputs: GuidedProductInputCommitService
    guided_reference_sources: GuidedReferenceSourceService
    guided_reference_candidates: GuidedReferenceCandidateService
    targets: AgentCanvasTargetService
    conversations: AgentConversationService
    turn_retries: ChatTurnRetryService
    guidance_advances: GuidanceAdvanceService
    guided_interactions: GuidedInteractionService
    guided_media_resume_deliveries: AgentCanvasGuidedMediaResumeRepository
    guided_media_resume_worker: GuidedMediaConfirmationResumeWorker
    commands: AgentCanvasCommandService
    variations: AgentCanvasVariationService
    layout: AgentCanvasLayoutService
    conversation_repository: AgentCanvasConversationRepository
    decision_bundles: AgentCanvasDecisionBundleRepository
    video_skills: VideoSkillRegistry
    style_activation: StyleSkillActivationService
    ad_media_validation: AdMediaDraftValidationService
    event_repository: EventRepository
    runtime_repository: AgentCanvasRuntimeRepository
    run_service: AgentCanvasRunService
    scheduler: DynamicCanvasScheduler
    runtime_snapshots: CanvasRuntimeSnapshotService
    provider_capabilities: ProviderCapabilityService
    provider_recovery: ProviderTaskRecoveryService
    post_ready_effects: AgentCanvasPostReadyEffectWorker
    post_ready_checkpoints: AgentCanvasPostReadyCheckpointService
    editing_nodes: EditingNodeService
    editing_responses: EditingResponseProjector
    editing_exports: EditingExportService
    editing_output_reuse: EditingExportOutputReuseService
    editing_export_repository: AgentCanvasEditingExportRepository
    continuation_outbox: AgentCanvasContinuationOutboxRepository
    continuation_worker: AgentCanvasContinuationWorker
    execution_settings: AgentCanvasExecutionSettingsService
    auto_run_dispatcher: AgentCanvasAutoRunDispatcher
    working_documents: AgentWorkingDocumentService
    accepted_background: AgentCanvasAcceptedBackgroundRunner
    presentation_streams: PresentationStreamRepository
    presentation_publisher: PresentationStreamPublisher
    prompt_preparation_worker: AgentCanvasPromptPreparationWorker | None = None


def _resume_prompt_preparation_barrier(
    dispatch: PromptPreparationDispatchV1,
    _result: object,
    *,
    runtime_repository: AgentCanvasRuntimeRepository,
    scheduler: DynamicCanvasScheduler,
    materialization_barrier: (AgentCanvasMaterializationPromptPreparationBarrier | None) = None,
    prompt_ready_activation: Callable[..., object] | None = None,
    notified_dispatch_ids: set[str] | None = None,
) -> None:
    """Wake the existing scheduler after a committed prompt terminal result.

    A preparation completion is only useful to an execution that is currently
    waiting on that source.  Keeping this check at the callback seam avoids
    waking unrelated waves and makes duplicate worker callbacks harmless.  The
    optional set is process-local notification bookkeeping; durable execution
    state remains the authority and is re-evaluated by ``resume``.
    """

    if dispatch.status not in {"completed", "failed"}:
        return
    materialization_owned = False
    if materialization_barrier is not None:
        materialization_owned = materialization_barrier.owns_dispatch(dispatch)
        materialization_barrier.reconcile_terminal_dispatch(dispatch)
    dispatch_id = getattr(dispatch, "dispatch_id", None)
    if notified_dispatch_ids is not None and dispatch_id and dispatch_id in notified_dispatch_ids:
        return
    activation_result: object | None = None
    if (
        dispatch.status == "completed"
        and prompt_ready_activation is not None
        and not materialization_owned
    ):
        operation_id = getattr(dispatch, "operation_id", None)
        if isinstance(operation_id, str) and operation_id:
            activation_result = prompt_ready_activation(
                dispatch.workflow_id,
                (dispatch.node_id,),
                source_id=operation_id,
            )

    active = runtime_repository.get_active_execution(dispatch.workflow_id)
    if active is None:
        activation_succeeded = bool(
            activation_result is not None
            and (
                getattr(activation_result, "automatic_run_command_ids", ())
                or getattr(activation_result, "manual_awaiting_id", None)
            )
        )
        if activation_succeeded and notified_dispatch_ids is not None and dispatch_id:
            notified_dispatch_ids.add(dispatch_id)
        return

    # Older lightweight test repositories do not expose members.  Preserve
    # their compatibility while production repositories use the durable wait
    # projection to fence unrelated wake-ups.
    list_members = getattr(runtime_repository, "list_members", None)
    if callable(list_members):
        members = list_members(active.execution_id)
        relevant = any(
            member.state in {"queued", "waiting"}
            and (
                member.node_id == dispatch.node_id
                or dispatch.node_id in member.waiting_for_node_ids
            )
            for member in members
        )
        if not relevant:
            return

    scheduler.resume(active.execution_id)
    if notified_dispatch_ids is not None and dispatch_id:
        notified_dispatch_ids.add(dispatch_id)


def get_agent_canvas_runtime(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[AgentCanvasRuntime]:
    runtime = create_agent_canvas_runtime(settings)
    try:
        yield runtime
    finally:
        runtime.database.dispose()


def create_agent_canvas_runtime(
    settings: Settings,
    *,
    video_agent_gateway_override: VideoAgentGateway | None = None,
    provider_executor_override: V2ProviderExecutor | None = None,
    fake_media_bytes_override: Callable[[str], bytes | None] | None = None,
) -> AgentCanvasRuntime:
    """Build one request/startup-scoped Agent Canvas runtime."""

    database = create_v2_database(settings.media_data_dir)
    model_repository = ProviderModelRepository(database)
    ProviderModelBootstrapService(settings, model_repository).bootstrap(
        now=datetime.now(timezone.utc).isoformat()
    )
    model_catalog = ProviderModelCatalogService(model_repository)
    model_selection = ModelSelectionService(model_catalog)
    adapter_registry = build_trusted_provider_adapter_registry(
        model_catalog.list_models(include_unavailable=True),
        settings=settings,
    )
    model_resolution = ModelResolutionService(
        model_selection,
        model_repository,
        allow_fake=(settings.agent_runtime_mode == "fake" or settings.media_mode == "mock"),
        adapter_registry=adapter_registry,
    )
    project_repository = ProjectRepository(database)
    event_repository = EventRepository(database)
    presentation_streams = PresentationStreamRepository(database)
    presentation_publisher = PresentationStreamPublisher(presentation_streams)
    workflow_repository = AgentCanvasWorkflowRepository(
        database,
        project_repository,
        event_repository,
    )
    requirement_repository = AgentCanvasRequirementRepository(database)
    decision_bundles = AgentCanvasDecisionBundleRepository(database, event_repository)
    requirement_service = AgentCanvasRequirementService(
        database,
        requirement_repository,
        event_repository,
    )
    execution_settings = AgentCanvasExecutionSettingsService(
        workflow_repository,
        AgentCanvasExecutionSettingsRepository(database, event_repository),
    )
    document_repository = AgentCanvasDocumentRepository(database)
    asset_repository = V2AssetLibraryRepository(database)
    cover_renditions = V2AssetRenditionService(
        settings.media_data_dir,
        ffmpeg_path=settings.ffmpeg_path,
    )
    project_cover_authority = ProjectCoverAuthorityService(
        project_repository,
        asset_repository,
        workflow_repository,
        ProjectCoverRenditionPrewarmer(settings.media_data_dir, cover_renditions),
    )
    asset_service = AgentCanvasAssetService(
        settings.media_data_dir,
        asset_repository,
        workflow_repository,
        media_facts_probe=(
            deterministic_media_facts_probe
            if settings.agent_runtime_mode == "fake" or settings.media_mode == "mock"
            else None
        ),
        rendition_service=cover_renditions,
        on_version_published=project_cover_authority.consider_published_version,
    )
    guided_product_inputs = GuidedProductInputCommitService(
        assets=asset_service,
        asset_repository=asset_repository,
        workflows=workflow_repository,
        commits=AgentCanvasGuidedProductRepository(workflow_repository, event_repository),
        compiler=ProductUploadMultiviewCompiler(
            ffmpeg=FfmpegTool(ffmpeg_path=settings.ffmpeg_path),
            probe=V2MediaProbe(),
            staging_root=settings.media_data_dir / "v2" / "staging",
            max_total_bytes=64 * 1024 * 1024,
            max_total_pixels=80_000_000,
            timeout_seconds=30,
        ),
        events=event_repository,
    )
    conversation_repository = AgentCanvasConversationRepository(
        database,
        event_repository,
    )
    guided_product_inputs.set_continuation_writer(
        conversation_repository.insert_continuation_in_transaction
    )
    guided_interaction_repository = AgentCanvasGuidedInteractionRepository(
        database,
        event_repository,
    )
    guided_media_resume_deliveries = AgentCanvasGuidedMediaResumeRepository(
        database,
        event_repository,
    )
    guidance_awaiting = GuidanceAwaitingService(
        guided_interaction_repository,
        conversation_repository,
    )
    working_documents = AgentWorkingDocumentService(
        workflows=workflow_repository,
        documents=AgentWorkingDocumentRepository(database, event_repository),
        assets=asset_repository,
        conversations=conversation_repository,
    )
    production_closure_receipts = AgentCanvasProductionClosureRepository(database)

    storyboard_authoring = StoryboardSequenceAuthoringService(
        documents=working_documents,
        events=event_repository,
        workflows=workflow_repository,
    )
    continuation_outbox = AgentCanvasContinuationOutboxRepository(
        database,
        event_repository,
    )
    video_skills = VideoSkillRegistry()
    video_skills.validate_startup()
    style_activation = StyleSkillActivationService(
        workflow_repository,
        conversation_repository,
        video_skills,
    )
    video_agent_gateway = video_agent_gateway_override or (
        DeterministicVideoAgentGateway()
        if settings.agent_runtime_mode == "fake"
        else PiVideoAgentGateway(
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
            on_provider_waiting=conversation_repository.mark_turn_provider_waiting,
            on_presentation=lambda event: presentation_publisher.publish_delta(
                SafePresentationDeltaV1(
                    stream_id=_presentation_stream_id(
                        event.workflow_id, event.turn_id or event.generation_id
                    ),
                    workflow_id=event.workflow_id,
                    stream_kind=event.channel,
                    generation_id=event.generation_id,
                    turn_id=event.turn_id,
                    node_id=event.node_id,
                    node_revision=event.node_revision,
                    response_locale=event.response_locale,
                    text=event.text,
                )
            ),
        )
    )
    prompt_dispatches = AgentCanvasPromptPreparationDispatchRepository(
        database,
        event_repository,
    )
    prompt_preparation_service = NodePromptPreparationService(
        workflow_repository,
        role_brief_author=lambda role_context, request_identity: (
            video_agent_gateway.author_role_brief(
                role_context,
                request_identity=request_identity,
            )
        ),
        asset_resolver=asset_service.resolve_asset,
        presentation_publisher=presentation_publisher,
    )
    provider_capabilities = ProviderCapabilityService(model_catalog)
    connection_policy = AgentCanvasConnectionPolicyService()
    editing_nodes = EditingNodeService(workflow_repository, asset_service.resolve_asset)
    editing_responses = EditingResponseProjector(editing_nodes)
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
        candidate_validator=editing_responses.validate_workflow,
    )
    world_setting_context = WorldSettingContextResolverV2(workflow_repository)
    runtime_repository = AgentCanvasRuntimeRepository(database, event_repository)

    def guided_asset_readable(asset) -> bool:
        try:
            return asset_service.resolve_asset_path(asset.asset_id).is_file()
        except (OSError, V2PersistenceError):
            return False

    def guided_media_work_active(workflow_id: str, node_ids: tuple[str, ...]) -> bool:
        selected = set(node_ids)
        active = runtime_repository.get_active_execution(workflow_id)
        if active is not None and any(
            member.node_id in selected
            for member in runtime_repository.list_members(active.execution_id)
        ):
            return True
        return any(
            task.workflow_id == workflow_id and task.node_id in selected
            for task in runtime_repository.list_recoverable_tasks()
        )

    guided_closure = GuidedProductionClosureService(
        workflows=workflow_repository,
        documents=working_documents,
        assets=asset_service.resolve_asset,
        asset_readable=guided_asset_readable,
        receipts=production_closure_receipts,
        has_active_work=guided_media_work_active,
        events=event_repository,
    )
    guided_editing = GuidedEditingPreparationService(
        workflows=workflow_repository,
        documents=working_documents,
        conversations=conversation_repository,
        events=event_repository,
        asset_resolver=asset_service.resolve_asset,
        closure=guided_closure,
        receipts=production_closure_receipts,
    )

    def prepare_current_editing(workflow_id: str) -> object:
        plans = working_documents.list_documents(
            workflow_id,
            kind="storyboard_production_plan",
            limit=2,
        ).items
        if len(plans) != 1:
            raise V2PersistenceError(
                "editing_preparation_plan_missing",
                "Editing preparation requires one current Storyboard production plan.",
                stage="guided_editing_preparation",
            )
        plan = plans[0]
        return guided_editing.prepare(
            workflow_id,
            plan.document_id,
            expected_plan_revision=plan.revision,
        )

    editing_export_repository = AgentCanvasEditingExportRepository(database)
    provider_executor = provider_executor_override or V2ProviderExecutor(
        settings=settings,
        data_dir=settings.media_data_dir,
        adapter_registry=adapter_registry,
    )
    dispatcher = build_default_node_dispatcher(
        settings,
        provider_executor=provider_executor,
        fake_media_bytes_override=fake_media_bytes_override,
        submission_intents=ProviderSubmissionIntentService(runtime_repository),
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

    def prepare_media_context(node: CanvasNodeV2, world_setting):
        contract = role_registry.get(node.semantic_role)
        bundle = reference_resolver.resolve(
            node.workflow_id,
            node.node_id,
            contract,
        )
        compiled = (
            prompt_compiler.compile(
                node,
                contract,
                bundle,
                world_setting=world_setting,
            )
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
                "effective_parameters": (
                    context.effective_parameters.effective
                    if context.effective_parameters is not None
                    else {}
                ),
            },
        )

    run_snapshots = AgentCanvasRunIntentSnapshotService(
        workflow_repository,
        runtime_repository,
        bindings=binding_service,
    )
    production_journey = GuidedProductionJourneyService(
        conversation_repository,
        awaiting=guidance_awaiting,
    )

    def resolve_storyboard_video_resolution(workflow_id: str) -> str | None:
        return next(
            (
                str(control.value)
                for control in requirement_service.get_current(workflow_id).hard_controls
                if control.control == "output_resolution"
            ),
            None,
        )

    def resolve_storyboard_video_audio_constraints(workflow_id: str) -> dict[str, object]:
        return _resolve_storyboard_video_audio_constraints(
            requirement_service,
            conversation_repository,
            workflow_id,
        )

    storyboard_progression = ProgressiveStoryboardReadyService(
        workflows=workflow_repository,
        authoring=storyboard_authoring,
        gateway=video_agent_gateway,
        receipts=production_closure_receipts,
        asset_resolver=asset_service.resolve_asset,
        events=event_repository,
        video_resolution_resolver=resolve_storyboard_video_resolution,
        video_audio_constraints_resolver=resolve_storyboard_video_audio_constraints,
        binding_capability_validator=lambda target, input_types, reference_count: (
            provider_capabilities.validate_binding(
                target,
                required_input_types=input_types,
                reference_count=reference_count,
            )
        ),
    )
    output_preparer = AgentCanvasOutputPreparationService(asset_service)
    result_commit_repository = AgentCanvasResultCommitRepository(
        database,
        asset_repository,
        event_repository,
    )
    result_committer = AgentCanvasExecutionResultCommitService(result_commit_repository)
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
        media_context_preparer=prepare_media_context,
        input_compiler=AgentCanvasResolvedInputCompiler(
            binding_service,
            world_settings=world_setting_context,
        ),
        world_settings=world_setting_context,
        stage_trace_writer=write_stage_trace,
        run_snapshots=run_snapshots,
        video_parameter_compiler=AgentCanvasVideoParameterCompiler(
            gateway=(
                DeterministicVideoParameterIntentGateway()
                if settings.agent_runtime_mode == "fake"
                else PiVideoParameterIntentGateway()
            ),
            authoring_repository=workflow_repository,
            runtime_repository=runtime_repository,
        ),
        image_limit=settings.v2_max_parallel_image_jobs,
        video_limit=settings.v2_max_parallel_video_jobs,
        audio_limit=settings.v2_max_parallel_audio_jobs,
        total_limit=settings.v2_max_parallel_generation_jobs,
        output_preparer=output_preparer,
        result_committer=result_committer,
        terminal_member_reconciler=guidance_awaiting.reconcile_terminal_member,
        prompt_preparation=prompt_preparation_service,
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
            raise V2PersistenceError(
                "provider_poll_temporary_failure",
                result.error_message or "Provider polling failed.",
                stage="agent_canvas_provider_recovery",
                details={"retryable": True},
            )
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
            mime_type=_provider_download_mime_type(media_type, path),
            filename=f"{task.node_id}{path.suffix.lower() or '.' + extension}",
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
        output_preparer=output_preparer,
        result_committer=result_committer,
    )
    editing_commit_service = AgentCanvasEditingExportCommitService(
        AgentCanvasEditingExportCommitRepository(
            database,
            asset_repository,
            event_repository,
        )
    )
    guided_final_completion = GuidedFinalCompletionService(
        workflows=workflow_repository,
        exports=editing_export_repository,
        commits=editing_commit_service,
        assets=asset_service.resolve_asset,
        asset_readable=guided_asset_readable,
        receipts=production_closure_receipts,
        conversations=conversation_repository,
        events=event_repository,
    )
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
        commit_service=editing_commit_service,
        on_completed=guided_final_completion.complete,
    )
    editing_output_reuse = EditingExportOutputReuseService(
        database,
        workflow_repository,
        asset_service,
        event_repository,
        data_dir=settings.media_data_dir,
        connection_policy=connection_policy,
    )

    run_service = AgentCanvasRunService(
        workflow_repository,
        runtime_repository,
        event_repository,
        run_snapshots=run_snapshots,
    )
    automatic_run_repository = AgentCanvasAutomaticRunRepository(
        database,
        event_repository,
    )
    fanout_activation = StoryboardFanoutActivationService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        requirements=requirement_service,
        documents=working_documents,
        receipts=production_closure_receipts,
        prompt_preparation=prompt_preparation_service,
        progression=production_journey,
        execution_settings=execution_settings.get_or_create,
        awaiting=guidance_awaiting,
        automatic_runs=automatic_run_repository,
    )
    guided_media_confirmations = GuidedMediaConfirmationService(
        workflows=workflow_repository,
        plans=storyboard_authoring,
        assets=asset_service.resolve_asset,
        asset_readable=guided_asset_readable,
        receipts=production_closure_receipts,
        events=event_repository,
        progression=storyboard_progression,
    )

    def resume_media_confirmation(confirmation_id: str):
        result = fanout_activation.resume_confirmation(confirmation_id)
        confirmation = production_closure_receipts.get_confirmation(confirmation_id)
        guided_media_reviews.reconcile_current_plan(confirmation.workflow_id)
        continuation_worker.run_once()
        return result

    guided_media_reviews = GuidedMediaReviewCoordinator(
        interactions=guided_interaction_repository,
        conversations=conversation_repository,
        plans=storyboard_authoring,
        assets=asset_service.resolve_asset,
        confirmations=guided_media_confirmations,
        result_commits=result_commit_repository,
        receipts=production_closure_receipts,
        events=event_repository,
        resume_media_confirmation=resume_media_confirmation,
        node_resolver=workflow_repository.get_node,
        execution_settings=execution_settings.get_or_create,
    )

    def persist_script_document(effect) -> CanvasPostReadyEffectDispositionV1:
        conversation_repository.publish_script_artifact(
            effect.workflow_id,
            script_node_id=effect.node_id,
            source_turn_id=None,
        )
        return CanvasPostReadyEffectDispositionV1(
            outcome="applied",
            reason_code="script_document_persisted",
        )

    def persist_text_document(effect) -> CanvasPostReadyEffectDispositionV1:
        _persist_text_document(
            document_repository,
            workflow_repository.get_node(effect.workflow_id, effect.node_id),
        )
        return CanvasPostReadyEffectDispositionV1(
            outcome="applied",
            reason_code="text_document_persisted",
        )

    def handle_storyboard_progression(effect) -> CanvasPostReadyEffectDispositionV1:
        return guided_media_reviews.publish_from_effect(effect)

    post_ready_effects = AgentCanvasPostReadyEffectWorker(
        AgentCanvasPostReadyEffectRepository(database, event_repository),
        handlers={
            "persist_script_document": persist_script_document,
            "persist_text_document": persist_text_document,
            "advance_storyboard_progression": handle_storyboard_progression,
        },
        worker_id=f"agent-canvas-post-ready:{uuid4().hex}",
    )
    post_ready_checkpoints = AgentCanvasPostReadyCheckpointService(
        AgentCanvasPostReadyCheckpointRepository(database)
    )
    auto_run_dispatcher = AgentCanvasAutoRunDispatcher(
        automatic_run_repository,
        start_or_extend=run_service.start_or_extend,
        resume_execution=scheduler.resume,
        worker_id=f"agent-canvas-auto-run:{uuid4().hex}",
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
            gateway=video_agent_gateway,
        )
        if isinstance(video_agent_gateway, PiVideoAgentGateway)
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
    guided_media_plan_actions = GuidedMediaPlanActionService(
        workflows=workflow_repository,
        plan_reader=storyboard_authoring,
        plan_writer=working_documents,
        variations=variation_service,
    )
    conversation_service = AgentConversationService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        nodes=AgentCanvasNodeService(
            workflow_repository,
            model_selection=model_selection,
            candidate_validator=editing_responses.validate_workflow,
        ),
        gateway=video_agent_gateway,
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
        model_selection=model_selection,
        requirements=requirement_service,
        production_journey=production_journey,
    )

    capability_execution = CapabilityExecutionService(
        database=database,
        gateway=video_agent_gateway,
        context_loader=capability_context_from_envelope,
        current_session_revision=lambda envelope: (
            conversation_repository.get_guidance_session(envelope.workflow_id).revision
            if envelope.expected_session_revision is not None
            else None
        ),
        publisher=AgentCanvasCapabilityProposalRepository(
            database,
            event_repository,
        ).publish,
        internal_document_publisher=AgentCanvasInternalDocumentCheckpointPublisher(
            database,
            event_repository,
        ).publish,
    )
    capability_supersession = AgentCanvasCapabilitySupersessionRepository(
        database,
        event_repository,
    )
    durable_next_action = DurableNextActionExecutionService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        outbox=continuation_outbox,
        capability_dispatch=CapabilityDispatchService(
            database=database,
            events=event_repository,
        ),
        gateway=video_agent_gateway,
        asset_resolver=asset_service.resolve_asset,
        model_selection=model_selection,
        decision_bundles=decision_bundles,
        editing_preparer=prepare_current_editing,
    )
    materialization_repository = AgentCanvasMaterializationRepository(
        database,
        event_repository,
    )
    guided_reference_sources = GuidedReferenceSourceService(
        assets=asset_service,
        asset_repository=asset_repository,
        workflows=workflow_repository,
        commits=AgentCanvasGuidedReferenceRepository(
            workflow_repository,
            event_repository,
            interactions=guided_interaction_repository,
        ),
    )
    guided_reference_sources.set_continuation_writer(
        conversation_repository.insert_continuation_in_transaction
    )
    guided_reference_candidates = GuidedReferenceCandidateService(
        assets=asset_service,
        workflows=workflow_repository,
    )

    def guided_reference_snapshot(
        workflow_id: str,
        reference: ProposedDraftReferenceV2,
    ) -> tuple[int | None, str | None]:
        """Freeze the same source versions for guided and compatibility routes."""

        return (
            (
                workflow_repository.get_node(workflow_id, reference.source_id).revision
                if reference.source_kind == "node"
                else None
            ),
            (
                asset_service.resolve_asset(reference.source_id).version_id
                if reference.source_kind == "image_asset"
                else None
            ),
        )

    guided_interactions = GuidedInteractionService(
        guided_interaction_repository,
        conversation_repository,
        materialization_repository,
        reference_snapshot=guided_reference_snapshot,
        media_submit=GuidedMediaReviewActionService(
            interactions=guided_interaction_repository,
            conversations=conversation_repository,
            plans=storyboard_authoring,
            confirmations=guided_media_confirmations,
            retry=guided_media_plan_actions.retry,
            replace=guided_media_plan_actions.replace,
            exclude=guided_media_plan_actions.exclude,
        ).submit,
    )
    guided_interactions.set_product_submitter(guided_product_inputs.submit_interaction)
    guided_interactions.set_reference_submitter(guided_reference_sources.submit_interaction)
    materialization_prompt_barrier = AgentCanvasMaterializationPromptPreparationBarrier(
        dispatches=prompt_dispatches,
        continuations=continuation_outbox,
        events=event_repository,
    )
    materialization_publisher = CapabilityMaterializationPublicationService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        asset_resolver=asset_service.resolve_asset,
        storyboard_authoring=storyboard_authoring,
        storyboard_gateway=video_agent_gateway,
        prompt_ready_activation=fanout_activation.activate_prompt_ready_nodes,
        reference_source_opener=guided_reference_sources.open_for_materialized_main,
        commit_service=AgentCanvasMaterializationCommitService(
            materialization_repository,
            GuidedProductionJourneyReducer(),
        ),
        prompt_dispatch=prompt_dispatches,
        prompt_preparation_barrier=materialization_prompt_barrier,
    )

    def resume_reference_materialization(
        envelope_id: str,
        source_turn_id: str,
        lease_guard,
    ) -> object:
        envelope = materialization_repository.get_envelope(envelope_id)
        recovered = materialization_publisher.resume_committed(
            envelope,
            lease_guard,
            continuation_source_turn_id=source_turn_id,
        )
        if recovered is None:
            raise V2PersistenceError(
                "materialization_resume_not_found",
                "Committed reference materialization could not be resumed.",
                stage="capability_materialization_publication",
            )
        return recovered

    durable_next_action.set_materialization_resumer(resume_reference_materialization)
    materialization_runner = QuickMediaMaterializationRunner(
        gateway=video_agent_gateway,
        context_loader=lambda envelope: materialization_context_from_state(
            envelope,
            conversations=conversation_repository,
            workflows=workflow_repository,
            asset_resolver=asset_service.resolve_asset,
        ),
        publisher=materialization_publisher.publish,
    )
    publication_runner = ProposalPublicationRunner(
        context_loader=lambda envelope: materialization_context_from_state(
            envelope,
            conversations=conversation_repository,
            workflows=workflow_repository,
            asset_resolver=asset_service.resolve_asset,
        ),
        publisher=materialization_publisher.publish,
    )

    def execute_materialization(envelope_id: str, lease_guard) -> object:
        envelope = materialization_repository.get_envelope(envelope_id)
        recovered = materialization_publisher.resume_committed(envelope, lease_guard)
        if recovered is not None:
            return recovered
        materialization_repository.mark_working(envelope)
        if isinstance(envelope, ProposalPublicationEnvelopeV1):
            return publication_runner.execute(envelope, lease_guard=lease_guard)
        return materialization_runner.execute(envelope, lease_guard=lease_guard)

    def fail_continuation_turn(
        turn_id: str,
        code: str,
        message: str,
        explicit_retryable: bool,
    ) -> object:
        if materialization_repository.fail_for_turn(
            turn_id,
            error_code=code,
            error_message=message,
        ):
            return conversation_repository.get_turn(turn_id)
        if explicit_retryable:
            try:
                ContinuationTurnRetrySnapshotV1.model_validate(
                    conversation_repository.get_retry_snapshot(turn_id)
                )
            except ValueError:
                explicit_retryable = False
        return conversation_repository.fail_turn(
            turn_id,
            code=code,
            message=message,
            retryable=explicit_retryable,
        )

    continuation_worker = AgentCanvasContinuationWorker(
        continuation_outbox,
        next_action=durable_next_action.execute,
        capability_command=capability_execution.execute,
        replace_superseded_capability=(durable_next_action.requeue_superseded_capability),
        supersede_capability=lambda continuation_id, worker_id, lease_generation: (
            capability_supersession.publish(
                continuation_id,
                worker_id=worker_id,
                lease_generation=lease_generation,
                now=datetime.now(timezone.utc),
            )
        ),
        capability_materialization=execute_materialization,
        worker_id=f"agent-canvas-continuation:{uuid4().hex}",
        fail_turn=fail_continuation_turn,
        dependency_reconciler=lambda delivery, materialization_id: (
            materialization_prompt_barrier.reconcile_dependency_wait(
                workflow_id=delivery.workflow_id,
                continuation_id=delivery.continuation_id,
                materialization_id=materialization_id,
            )
        ),
    )

    def activate_prompt_ready_nodes(
        workflow_id: str,
        node_ids: tuple[str, ...],
        *,
        source_id: str,
    ) -> object | None:
        """Re-admit only current prompt-ready Storyboard media authority."""

        setting = execution_settings.get_or_create(workflow_id)
        node = workflow_repository.get_node(workflow_id, node_ids[0]) if node_ids else None
        if node is None or node.creative_role not in {
            "storyboard_sequence",
            "storyboard_video",
        }:
            return None
        if setting.media_execution_mode == "manual":
            return fanout_activation.activate_prompt_ready_nodes(
                workflow_id,
                node_ids,
                source_id=source_id,
            )
        return fanout_activation.activate_prompt_ready_nodes(
            workflow_id,
            node_ids,
            source_id=source_id,
        )

    notified_prompt_dispatch_ids: set[str] = set()
    prompt_preparation_worker = AgentCanvasPromptPreparationWorker(
        prompt_dispatches,
        prepare=lambda dispatch, context: prompt_preparation_service.prepare(
            dispatch.workflow_id,
            dispatch.node_id,
            operation_id=dispatch.operation_id,
            context=context,
        ),
        # Production recovery must reconstruct only the immutable snapshot
        # persisted with the dispatch row.  The test-only loader hook remains
        # intentionally unset here so incomplete legacy rows fail closed.
        context_loader=None,
        stale_dispatch_reconciler=(
            lambda dispatch, worker_id, lease_generation, reason, timestamp: (
                workflow_repository.reconcile_stale_prompt_preparation_dispatch(
                    dispatch,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    reason=reason,
                    now=timestamp,
                )
            )
        ),
        worker_id=f"agent-canvas-prompt-preparation:{uuid4().hex}",
        barrier_callback=lambda dispatch, result: _resume_prompt_preparation_barrier(
            dispatch,
            result,
            runtime_repository=runtime_repository,
            scheduler=scheduler,
            materialization_barrier=materialization_prompt_barrier,
            prompt_ready_activation=activate_prompt_ready_nodes,
            notified_dispatch_ids=notified_prompt_dispatch_ids,
        ),
    )
    guided_media_resume_worker = GuidedMediaConfirmationResumeWorker(
        guided_media_resume_deliveries,
        resume_confirmation=resume_media_confirmation,
        worker_id=f"agent-canvas-guided-media-resume:{uuid4().hex}",
    )
    turn_retries = ChatTurnRetryService(
        workflow_repository,
        conversation_repository,
        asset_resolver=asset_service.resolve_asset,
    )
    guidance_advances = GuidanceAdvanceService(
        workflows=workflow_repository,
        conversations=conversation_repository,
        requirements=requirement_repository,
        continuations=continuation_outbox,
        decision_bundles=decision_bundles,
        retries=turn_retries,
        events=event_repository,
        post_ready_gate=GuidancePostReadyGate(
            result_commits=result_commit_repository,
            checkpoints=post_ready_checkpoints,
        ),
    )
    return AgentCanvasRuntime(
        database=database,
        projects=AgentCanvasProjectService(
            project_repository,
            workflow_repository,
            asset_service,
            conversation_repository,
            style_activation,
        ),
        workflows=workflow_repository,
        requirements=requirement_service,
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
            candidate_validator=editing_responses.validate_workflow,
        ),
        connection_policy=connection_policy,
        assets=asset_service,
        guided_product_inputs=guided_product_inputs,
        guided_reference_sources=guided_reference_sources,
        guided_reference_candidates=guided_reference_candidates,
        targets=AgentCanvasTargetService(workflow_repository, asset_service),
        conversations=conversation_service,
        turn_retries=turn_retries,
        guidance_advances=guidance_advances,
        guided_interactions=guided_interactions,
        guided_media_resume_deliveries=guided_media_resume_deliveries,
        guided_media_resume_worker=guided_media_resume_worker,
        commands=command_service,
        variations=variation_service,
        layout=AgentCanvasLayoutService(workflow_repository),
        conversation_repository=conversation_repository,
        decision_bundles=decision_bundles,
        video_skills=video_skills,
        style_activation=style_activation,
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
        post_ready_effects=post_ready_effects,
        post_ready_checkpoints=post_ready_checkpoints,
        editing_nodes=editing_nodes,
        editing_responses=editing_responses,
        editing_exports=editing_exports,
        editing_output_reuse=editing_output_reuse,
        editing_export_repository=editing_export_repository,
        continuation_outbox=continuation_outbox,
        continuation_worker=continuation_worker,
        execution_settings=execution_settings,
        auto_run_dispatcher=auto_run_dispatcher,
        working_documents=working_documents,
        accepted_background=AgentCanvasAcceptedBackgroundRunner(),
        presentation_streams=presentation_streams,
        presentation_publisher=presentation_publisher,
        prompt_preparation_worker=prompt_preparation_worker,
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
        if error.code in {
            "agent_skill_manifest_invalid",
            "agent_skill_digest_mismatch",
            "style_skill_context_budget_exceeded",
            "style_skill_snapshot_invalid",
        }:
            raise _http_error(error.code, 422, str(error)) from error
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(created.workflow_id, created.revision)
    return created


@router.get("/projects", response_model=ProjectV2ListResponse)
def list_projects(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    response: Response,
    project_status: Annotated[
        Literal["active", "archived", "trashed"], Query(alias="status")
    ] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> ProjectV2ListResponse | Response:
    try:
        listing = runtime.projects.list_projects(
            status=project_status,
            limit=limit,
            cursor=cursor,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    etag = f'"projects-{sha256(listing.model_dump_json().encode()).hexdigest()}"'
    cache_control = "private, max-age=10, stale-while-revalidate=30"
    if if_none_match and if_none_match.strip() == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Cache-Control": cache_control,
            },
        )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = cache_control
    return listing


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
        workflow = runtime.editing_responses.project_workflow(
            runtime.projects.get_workflow(workflow_id)
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return workflow


@router.get(
    "/workflows/{workflow_id}/requirements",
    response_model=RequirementLedgerResponseV1,
)
def get_requirements(
    workflow_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> RequirementLedgerResponseV1:
    try:
        requirements = runtime.requirements.get_current(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = requirement_ledger_etag(
        workflow_id,
        requirements.revision_no,
    )
    return requirements


@router.patch(
    "/workflows/{workflow_id}/requirements",
    response_model=RequirementLedgerResponseV1,
)
def patch_requirements(
    workflow_id: str,
    request: RequirementLedgerPatchRequestV1,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RequirementLedgerResponseV1:
    if not idempotency_key or len(idempotency_key) > 256:
        raise _http_error(
            "idempotency_key_required",
            422,
            "A non-empty Idempotency-Key of at most 256 characters is required.",
        )
    try:
        expected_revision = parse_requirement_if_match(if_match, workflow_id)
        requirements = runtime.requirements.apply_manual_patch(
            workflow_id,
            expected_revision_no=expected_revision,
            idempotency_key=idempotency_key,
            request=request,
        )
    except V2PreconditionError as error:
        raise _http_error(error.code, error.status_code, str(error)) from error
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = requirement_ledger_etag(
        workflow_id,
        requirements.revision_no,
    )
    return requirements


@router.get(
    "/workflows/{workflow_id}/agent-settings",
    response_model=AgentExecutionSettingsV2,
)
def get_agent_execution_settings(
    workflow_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> AgentExecutionSettingsV2:
    try:
        settings = runtime.execution_settings.get_or_create(workflow_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = _agent_settings_etag(settings.revision)
    return settings


@router.patch(
    "/workflows/{workflow_id}/agent-settings",
    response_model=AgentExecutionSettingsV2,
)
def update_agent_execution_settings(
    workflow_id: str,
    request: AgentExecutionSettingsPatchV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AgentExecutionSettingsV2:
    expected_revision = _agent_settings_expected_revision(if_match)
    try:
        settings = runtime.execution_settings.update(
            workflow_id,
            request,
            expected_revision=expected_revision,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = _agent_settings_etag(settings.revision)
    return settings


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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
        runtime.editing_responses.validate_content_payload(
            workflow_id=workflow_id,
            node_id="pending",
            node_type=request.node_type,
            structured_content=request.structured_content,
        )
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
        workflow = runtime.editing_responses.project_workflow(workflow)
        node = _projected_node(workflow, node.node_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, workflow.revision)
    return CanvasMutationResponseV2(workflow=workflow, node=node)


@router.post(
    "/workflows/{workflow_id}/nodes/{editing_node_id}/import-export",
    response_model=EditingExportOutputReuseResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def import_editing_export(
    workflow_id: str,
    editing_node_id: str,
    request: EditingExportOutputReuseRequestV2,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EditingExportOutputReuseResponseV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        result = runtime.editing_output_reuse.import_export(
            workflow_id,
            editing_node_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, result.revision)
    return result


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
        workflow = runtime.projects.get_workflow(workflow_id)
        node = _projected_node(workflow, node_id)
        return runtime.editing_responses.project_snapshot_node(workflow, node)
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
        execution_id = str(result.run["execution_id"])
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.VARIATION_EXECUTION_RESUME,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.EXECUTION,
                resource_id=execution_id,
                callback=runtime.scheduler.resume,
                args=(execution_id,),
            ),
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
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
            source_only_product = (
                current.node_type == "image"
                and current.creative_role == "product"
                and current.execution_mode == "source_only"
                and current.metadata.get("source_input_kind") in {"main", "multiview"}
            )
            if not source_only_product:
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
        workflow = runtime.editing_responses.project_workflow(workflow)
        node = _projected_node(workflow, node.node_id)
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
                runtime.accepted_background.run,
                AcceptedBackgroundWork(
                    operation=AcceptedBackgroundOperation.EDITING_EXPORT_RESUME,
                    workflow_id=workflow_id,
                    resource_type=AcceptedBackgroundResourceType.EDITING_EXPORT,
                    resource_id=accepted.export_id,
                    callback=runtime.editing_exports.resume,
                    args=(accepted.export_id,),
                ),
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
        workflow = runtime.nodes.delete(
            workflow_id,
            node_id,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
        workflow = runtime.editing_responses.project_workflow(workflow)
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
        runtime.editing_responses.validate_content_payload(
            workflow_id=workflow_id,
            node_id="pending",
            node_type=request.node.node_type,
            structured_content=request.node.structured_content,
        )
        created = runtime.connected_authoring.create_connected_node(
            workflow_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
        created = created.model_copy(
            update={"node": runtime.editing_responses.project_node(created.node)}
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
        binding = runtime.bindings.create(
            workflow_id,
            request,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
        workflow = runtime.projects.get_workflow(workflow_id)
        workflow = runtime.editing_responses.project_workflow(workflow)
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
        runtime.editing_responses.validate_workflow(runtime.projects.get_workflow(workflow_id))
        workflow = runtime.bindings.delete(
            workflow_id,
            binding_id,
            expected_revision=_expected_revision(if_match, workflow_id),
        )
        workflow = runtime.editing_responses.project_workflow(workflow)
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
            source_semantic_role=parsed.semantic_role,
        )
        pending_handoff_id = None
        if parsed.semantic_role == "product_main":
            session = runtime.conversation_repository.get_guidance_session_or_none(workflow_id)
            if session is not None and asset.version_id is not None:
                pending_handoff_id = runtime.guided_product_inputs.create_pending_handoff(
                    workflow_id=workflow_id,
                    session_id=session.session_id,
                    input_kind="main",
                    asset_versions=(
                        GuidedProductAssetVersionRefV1(
                            asset_id=asset.asset_id,
                            version_id=asset.version_id,
                        ),
                    ),
                    idempotency_key=f"{idempotency_key}:product-main-handoff",
                )
    except (ValueError, json.JSONDecodeError) as error:
        raise _http_error("asset_upload_invalid", 422, "Asset metadata is invalid.") from error
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return ProjectAssetUploadResponseV2(
        workflow_id=workflow_id,
        asset=asset,
        pending_handoff_id=pending_handoff_id,
    )


@router.post(
    "/workflows/{workflow_id}/guided/product-inputs",
    response_model=GuidedProductInputCommitResponseV1,
)
def commit_guided_product_input(
    workflow_id: str,
    request: GuidedProductInputCommitRequestV1,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GuidedProductInputCommitResponseV1:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        committed = runtime.guided_product_inputs.commit(
            workflow_id,
            request,
            expected_workflow_revision=_expected_revision(if_match, workflow_id),
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    response.headers["ETag"] = workflow_etag(workflow_id, committed.workflow_revision)
    return committed


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


@router.get(
    "/workflows/{workflow_id}/reference-candidates",
    response_model=ReferenceCandidateListResponseV2,
)
def list_guided_reference_candidates(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    reference_kind: Annotated[ReferenceCandidateKindV2, Query()],
    scope: Annotated[ReferenceCandidateScopeV2, Query()],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    query: Annotated[str | None, Query(max_length=128)] = None,
) -> ReferenceCandidateListResponseV2:
    try:
        return runtime.guided_reference_candidates.list(
            workflow_id,
            reference_kind=reference_kind,
            scope=scope,
            cursor=cursor,
            query=query,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


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


@router.get("/assets/{asset_id}/preview")
@router.get("/assets/{asset_id}/poster")
def get_asset_rendition(
    asset_id: str,
    request: Request,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    version_id: Annotated[str, Query(alias="v", min_length=1, max_length=160)],
    size: Annotated[int | None, Query(ge=320, le=640, multiple_of=320)] = None,
) -> Response:
    kind = request.url.path.rsplit("/", 1)[-1]
    try:
        rendition = runtime.assets.open_rendition(
            asset_id,
            version_id,
            kind=kind,
            max_dimension=size,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return Response(
        content=rendition.body,
        status_code=rendition.status_code,
        media_type=rendition.media_type,
        headers=rendition.headers,
    )


@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    response: Response,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    version_id: Annotated[str | None, Query(alias="v", min_length=1, max_length=160)] = None,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    download: Annotated[bool, Query()] = False,
) -> Response:
    try:
        content = runtime.assets.open_content(
            asset_id,
            version_id=version_id,
            range_header=range_header,
            download=download,
        )
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
    "/workflows/{workflow_id}/agent-documents",
    response_model=AgentWorkingDocumentPageV2,
)
def list_agent_working_documents(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    kind: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> AgentWorkingDocumentPageV2:
    if kind is not None and kind not in {
        "anchor_registry",
        "storyboard_production_plan",
    }:
        raise _http_error(
            "agent_document_kind_unsupported",
            422,
            "Agent working document kind is unsupported.",
        )
    resolved_kind = cast(AgentWorkingDocumentKindV2 | None, kind)
    try:
        return runtime.working_documents.list_documents(
            workflow_id,
            kind=resolved_kind,
            cursor=cursor,
            limit=limit,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.get(
    "/workflows/{workflow_id}/agent-documents/{document_id}",
    response_model=AgentWorkingDocumentV2,
)
def get_agent_working_document(
    workflow_id: str,
    document_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> AgentWorkingDocumentV2:
    try:
        return runtime.working_documents.get_document(workflow_id, document_id)
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
        return timeline
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
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    stream_id = _presentation_stream_id(workflow_id, accepted.turn_id)
    stream = runtime.presentation_publisher.create_assistant_stream(
        workflow_id=workflow_id,
        turn_id=accepted.turn_id,
        stream_id=stream_id,
        generation_id=accepted.turn_id,
        idempotency_key=f"assistant:{workflow_id}:{accepted.turn_id}",
    )
    if stream is not None:
        runtime.presentation_publisher.started(stream)
        accepted = accepted.model_copy(update={"presentation_stream_id": stream.stream_id})
    if (
        not accepted.replayed
        and runtime.conversations.get_turn(accepted.turn_id).status == "queued"
    ):
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.CHAT_TURN_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
        )
    return accepted


@router.post(
    "/workflows/{workflow_id}/chat/guidance/advance",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def advance_guidance(
    workflow_id: str,
    request: GuidanceAdvanceRequestV1,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.guidance_advances.submit(
            workflow_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if not accepted.replayed:
        if accepted.retry_of_turn_id is not None:
            background_tasks.add_task(
                runtime.accepted_background.run,
                AcceptedBackgroundWork(
                    operation=AcceptedBackgroundOperation.GUIDANCE_RETRY_TURN_PROCESS,
                    workflow_id=workflow_id,
                    resource_type=AcceptedBackgroundResourceType.TURN,
                    resource_id=accepted.turn_id,
                    callback=_process_agent_turn_and_resume,
                    args=(runtime, workflow_id, accepted.turn_id),
                ),
            )
        else:
            background_tasks.add_task(
                runtime.accepted_background.run,
                AcceptedBackgroundWork(
                    operation=AcceptedBackgroundOperation.GUIDANCE_CONTINUATION_DRAIN,
                    workflow_id=workflow_id,
                    resource_type=AcceptedBackgroundResourceType.TURN,
                    resource_id=accepted.turn_id,
                    callback=runtime.continuation_worker.run_once,
                ),
            )
    return accepted


@router.get(
    "/workflows/{workflow_id}/chat/decision-bundles/{bundle_id}",
    response_model=DecisionBundleV1,
)
def get_decision_bundle(
    workflow_id: str,
    bundle_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> DecisionBundleV1:
    try:
        return runtime.decision_bundles.get(workflow_id, bundle_id)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error


@router.post(
    "/workflows/{workflow_id}/chat/decision-bundles/{bundle_id}/answers",
    response_model=DecisionBundleActionAcceptedV1,
    status_code=status.HTTP_202_ACCEPTED,
)
def act_on_decision_bundle(
    workflow_id: str,
    bundle_id: str,
    request: DecisionBundleActionRequestV1,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DecisionBundleActionAcceptedV1:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.decision_bundles.apply_action(
            workflow_id=workflow_id,
            bundle_id=bundle_id,
            action=request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if not accepted.replayed:
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.DECISION_BUNDLE_TURN_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
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
    "/workflows/{workflow_id}/chat/turns/{turn_id}/retry",
    response_model=ChatTurnAcceptedV2,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_chat_turn(
    workflow_id: str,
    turn_id: str,
    request: ChatTurnRetryRequestV1,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChatTurnAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.turn_retries.retry(
            workflow_id,
            turn_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if not accepted.replayed:
        typed_delivery = runtime.continuation_outbox.get_for_turn(accepted.turn_id)
        if typed_delivery is not None and typed_delivery.operation in {
            "next_action",
            "capability_command",
        }:
            background_tasks.add_task(
                runtime.accepted_background.run,
                AcceptedBackgroundWork(
                    operation=AcceptedBackgroundOperation.GUIDANCE_CONTINUATION_DRAIN,
                    workflow_id=workflow_id,
                    resource_type=AcceptedBackgroundResourceType.TURN,
                    resource_id=accepted.turn_id,
                    callback=runtime.continuation_worker.run_once,
                ),
            )
            return accepted
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.FAILED_TURN_RETRY_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
        )
    return accepted


@router.post(
    "/workflows/{workflow_id}/chat/interactions/{interaction_id}/submit",
    response_model=GuidedInteractionAcceptedV1,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_guided_interaction(
    workflow_id: str,
    interaction_id: str,
    request: GuidedInteractionSubmitRequestV1,
    background_tasks: BackgroundTasks,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GuidedInteractionAcceptedV1:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.guided_interactions.submit_interaction(
            workflow_id,
            interaction_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if isinstance(request, GuidedMediaReviewSubmitV1) and request.action == "accept":
        delivery = runtime.guided_media_resume_deliveries.get_for_submission(accepted.submission_id)
        if delivery is None:
            raise _http_error(
                "guided_media_resume_delivery_unavailable",
                503,
                "Guided media resume delivery is unavailable.",
            )
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.GUIDED_MEDIA_CONFIRMATION_RESUME,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.DELIVERY,
                resource_id=delivery.delivery_id,
                callback=runtime.guided_media_resume_worker.run_one,
                args=(delivery.delivery_id,),
            ),
        )
    elif not accepted.replayed:
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.GUIDED_INTERACTION_SUBMIT,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.INTERACTION,
                resource_id=interaction_id,
                callback=runtime.continuation_worker.run_once,
            ),
        )
    return accepted


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
        replayed_interaction = runtime.guided_interactions.replay_proposal_action(
            workflow_id,
            proposal_id,
            request,
            idempotency_key=idempotency_key,
        )
        if replayed_interaction is not None:
            proposal = runtime.conversation_repository.get_private_proposal(proposal_id)
            source_turn = runtime.conversation_repository.get_turn(proposal.turn_id)
            if proposal.materialization is None:
                raise V2PersistenceError(
                    "guided_interaction_incomplete",
                    "Guided interaction replay is missing its Materialization.",
                    stage="agent_canvas_api",
                )
            return ChatTurnAcceptedV2(
                workflow_id=workflow_id,
                conversation_id=source_turn.conversation_id,
                message_id=None,
                turn_id=proposal.materialization.turn_id,
                events_cursor=replayed_interaction.events_cursor,
                replayed=True,
            )
        closed_replay = runtime.guided_interactions.replay_closed_storyboard_action(
            workflow_id,
            proposal_id,
            request,
            idempotency_key=idempotency_key,
        )
        if closed_replay is not None:
            if not closed_replay.replayed:
                background_tasks.add_task(
                    runtime.accepted_background.run,
                    AcceptedBackgroundWork(
                        operation=AcceptedBackgroundOperation.GUIDED_INTERACTION_SUBMIT,
                        workflow_id=workflow_id,
                        resource_type=AcceptedBackgroundResourceType.TURN,
                        resource_id=closed_replay.turn_id,
                        callback=runtime.continuation_worker.run_once,
                    ),
                )
            return closed_replay
        interaction = runtime.guided_interactions.get_current(workflow_id)
        if (
            interaction is not None
            and isinstance(interaction.content, GuidedConceptChoiceV2)
            and interaction.content.proposal_id == proposal_id
            and isinstance(
                request,
                (
                    SelectOptionActionV2,
                    DelegateChoiceActionV2,
                    DeferTopicActionV2,
                    ExcludeElementActionV2,
                ),
            )
        ):
            accepted_interaction = runtime.guided_interactions.submit_interaction(
                workflow_id,
                interaction.interaction_id,
                GuidedConceptSubmitV2(
                    submission_kind="concept_choice",
                    expected_interaction_revision=interaction.revision,
                    expected_session_revision=request.expected_session_revision,
                    action=(
                        "select"
                        if isinstance(request, SelectOptionActionV2)
                        else (
                            "delegate"
                            if isinstance(request, DelegateChoiceActionV2)
                            else ("defer" if isinstance(request, DeferTopicActionV2) else "exclude")
                        )
                    ),
                    option_id=(
                        request.option_id if isinstance(request, SelectOptionActionV2) else None
                    ),
                    accepted_references=(
                        tuple(
                            GuidedAcceptedReferenceV1.model_validate(reference.model_dump())
                            for reference in request.accepted_references
                        )
                        if isinstance(request, SelectOptionActionV2)
                        else ()
                    ),
                ),
                idempotency_key=idempotency_key,
            )
            proposal = runtime.conversation_repository.get_private_proposal(proposal_id)
            source_turn = runtime.conversation_repository.get_turn(proposal.turn_id)
            if proposal.materialization is None and isinstance(
                request, (SelectOptionActionV2, DelegateChoiceActionV2)
            ):
                raise V2PersistenceError(
                    "guided_interaction_incomplete",
                    "Guided interaction did not queue Materialization.",
                    stage="agent_canvas_api",
                )
            accepted = ChatTurnAcceptedV2(
                workflow_id=workflow_id,
                conversation_id=source_turn.conversation_id,
                message_id=None,
                turn_id=(
                    proposal.materialization.turn_id
                    if proposal.materialization is not None
                    else source_turn.turn_id
                ),
                events_cursor=accepted_interaction.events_cursor,
                replayed=accepted_interaction.replayed,
            )
            if not accepted.replayed and proposal.materialization is not None:
                background_tasks.add_task(
                    runtime.accepted_background.run,
                    AcceptedBackgroundWork(
                        operation=AcceptedBackgroundOperation.GUIDED_INTERACTION_SUBMIT,
                        workflow_id=workflow_id,
                        resource_type=AcceptedBackgroundResourceType.INTERACTION,
                        resource_id=interaction.interaction_id,
                        callback=runtime.continuation_worker.run_once,
                    ),
                )
            return accepted
        accepted = runtime.conversations.act_on_proposal(
            workflow_id,
            proposal_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if not accepted.replayed:
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.PROPOSAL_TURN_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
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
    if not accepted.replayed:
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.COMMAND_PLAN_TURN_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
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
            action_type=request.action,
            authority=request.authority,
            expected_session_revision=request.expected_session_revision,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    if not accepted.replayed:
        background_tasks.add_task(
            runtime.accepted_background.run,
            AcceptedBackgroundWork(
                operation=AcceptedBackgroundOperation.GUIDED_ACTION_TURN_PROCESS,
                workflow_id=workflow_id,
                resource_type=AcceptedBackgroundResourceType.TURN,
                resource_id=accepted.turn_id,
                callback=_process_agent_turn_and_resume,
                args=(runtime, workflow_id, accepted.turn_id),
            ),
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
        return runtime.style_activation.activate(
            workflow_id,
            request,
            idempotency_key=idempotency_key,
        )
    except V2PersistenceError as error:
        if error.code in {
            "agent_skill_manifest_invalid",
            "agent_skill_digest_mismatch",
            "style_skill_context_budget_exceeded",
            "style_skill_snapshot_invalid",
        }:
            raise _http_error(error.code, 422, str(error)) from error
        raise _persistence_http_error(error) from error


@router.get("/video-skills", response_model=VideoSkillCatalogResponseV2)
def list_video_skills(
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    category: Annotated[str | None, Query(max_length=80)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VideoSkillCatalogResponseV2:
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


@router.get("/video-skills/{skill_id}/preview", response_class=FileResponse)
def get_video_skill_preview(
    skill_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    version: Annotated[str, Query(alias="v", min_length=1, max_length=80)],
) -> FileResponse:
    try:
        preview = runtime.video_skills.get_preview_file(skill_id, version)
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error
    return FileResponse(
        preview.path,
        media_type=preview.media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{preview.digest}"',
        },
    )


@router.get(
    "/workflows/{workflow_id}/creative-session",
    response_model=GuidedSessionStateV2,
)
def get_creative_session(
    workflow_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> GuidedSessionStateV2:
    try:
        return runtime.conversation_repository.get_guidance_session(workflow_id)
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
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CanvasRunAcceptedV2:
    if not idempotency_key:
        raise _http_error("idempotency_key_required", 422, "Idempotency-Key is required.")
    try:
        accepted = runtime.run_service.start_or_extend(
            workflow_id,
            request,
            idempotency_key=idempotency_key,
            expected_workflow_revision=_expected_revision(if_match, workflow_id),
        )
        if accepted.accepted_node_ids or accepted.joined_node_ids:
            background_tasks.add_task(
                runtime.accepted_background.run,
                AcceptedBackgroundWork(
                    operation=AcceptedBackgroundOperation.CANVAS_RUN_RESUME,
                    workflow_id=workflow_id,
                    resource_type=AcceptedBackgroundResourceType.EXECUTION,
                    resource_id=accepted.execution_id,
                    callback=runtime.scheduler.resume,
                    args=(accepted.execution_id,),
                ),
            )
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
    "/workflows/{workflow_id}/executions/{execution_id}/post-ready-checkpoint",
    response_model=CanvasPostReadyCheckpointV2,
)
def get_post_ready_checkpoint(
    workflow_id: str,
    execution_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
) -> CanvasPostReadyCheckpointV2:
    try:
        return runtime.post_ready_checkpoints.get(workflow_id, execution_id)
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


@router.get(
    "/workflows/{workflow_id}/presentation/streams/{stream_id}",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {"schema": {"type": "string"}},
            }
        }
    },
)
def stream_agent_presentation(
    workflow_id: str,
    stream_id: str,
    runtime: Annotated[AgentCanvasRuntime, Depends(get_agent_canvas_runtime)],
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Replay one bounded workflow-owned presentation stream over SSE."""

    initial_cursor = _presentation_cursor(last_event_id, after_seq)
    try:
        events = runtime.presentation_streams.list_after(
            workflow_id,
            stream_id,
            after_seq=initial_cursor,
        )
    except V2PersistenceError as error:
        raise _persistence_http_error(error) from error

    async def body():
        cursor = initial_cursor
        last_heartbeat = monotonic()
        pending = events
        while True:
            for event in pending:
                cursor = event.sequence_no
                yield (
                    f"id: {event.sequence_no}\n"
                    f"event: {event.event_type}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )
            current = runtime.presentation_streams.get(workflow_id, stream_id)
            if current.status != "open":
                return
            await asyncio.sleep(1)
            pending = runtime.presentation_streams.list_after(
                workflow_id,
                stream_id,
                after_seq=cursor,
            )
            if not pending and monotonic() - last_heartbeat >= 15:
                last_heartbeat = monotonic()
                yield ": keepalive\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _presentation_cursor(last_event_id: str | None, after_seq: int | None) -> int:
    value = last_event_id if last_event_id is not None else after_seq
    if value is None:
        return 0
    try:
        cursor = int(value)
    except (TypeError, ValueError) as error:
        raise _http_error(
            "presentation_stream_cursor_invalid",
            422,
            "Presentation stream cursor must be a non-negative integer.",
        ) from error
    if cursor < 0:
        raise _http_error(
            "presentation_stream_cursor_invalid",
            422,
            "Presentation stream cursor must be a non-negative integer.",
        )
    return cursor


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
    turn = runtime.conversations.process_turn(turn_id)
    stream_id = _presentation_stream_id(workflow_id, turn_id)
    try:
        presentation_streams = getattr(runtime, "presentation_streams", None)
        presentation_publisher = getattr(runtime, "presentation_publisher", None)
        stream = (
            presentation_streams.get(workflow_id, stream_id)
            if presentation_streams is not None and presentation_publisher is not None
            else None
        )
        if stream is not None and turn.status == "completed":
            persisted_result = _persisted_assistant_result(runtime, workflow_id, turn_id)
            authoritative_id, message = persisted_result or (turn.turn_id, "")
            presentation_publisher.publish_validated_text(stream, message)
            presentation_publisher.commit(
                stream,
                authoritative_id=authoritative_id,
                content=message,
            )
        elif stream is not None and turn.status == "failed":
            presentation_publisher.fail(stream, turn.error_code or "presentation_stream_failed")
    except V2PersistenceError:
        pass
    runtime.auto_run_dispatcher.run_once()
    active = runtime.runtime_repository.get_active_execution(workflow_id)
    if active is not None:
        runtime.scheduler.resume(active.execution_id)


def _persisted_assistant_result(
    runtime: AgentCanvasRuntime,
    workflow_id: str,
    turn_id: str,
) -> tuple[str, str] | None:
    timeline = runtime.conversations.get_timeline(workflow_id)
    for entry in reversed(timeline.items):
        if (
            entry.entry_type == "message"
            and entry.speaker == "adcraft_video_agent"
            and entry.metadata.get("turn_id") == turn_id
        ):
            return entry.entry_id, entry.content
    return None


def _presentation_stream_id(workflow_id: str, generation_id: str) -> str:
    """Derive a stable opaque identity without exposing request content."""

    digest = sha256(f"assistant:{workflow_id}:{generation_id}".encode("utf-8")).hexdigest()[:32]
    return f"prs_{digest}"


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


def _agent_settings_etag(revision: int) -> str:
    return f'"{revision}"'


def _agent_settings_expected_revision(value: str | None) -> int:
    if value is None:
        raise _http_error(
            "agent_settings_precondition_required",
            428,
            "If-Match is required for Agent execution settings updates.",
        )
    normalized = value.strip()
    if normalized.startswith("W/") or len(normalized) < 3:
        raise _http_error(
            "agent_settings_revision_conflict",
            412,
            "Agent execution settings ETag is invalid.",
        )
    token = normalized[1:-1] if normalized.startswith('"') and normalized.endswith('"') else ""
    try:
        revision = int(token)
    except ValueError as error:
        raise _http_error(
            "agent_settings_revision_conflict",
            412,
            "Agent execution settings ETag is invalid.",
        ) from error
    if revision < 1:
        raise _http_error(
            "agent_settings_revision_conflict",
            412,
            "Agent execution settings ETag is invalid.",
        )
    return revision


def _persistence_http_error(error: V2PersistenceError) -> HTTPException:
    status_code = {
        "project_not_found": 404,
        "project_not_trashed": 409,
        "project_state_conflict": 412,
        "project_cursor_invalid": 422,
        "project_page_invalid": 422,
        "project_update_invalid": 422,
        "project_cover_version_required": 422,
        "project_cover_media_invalid": 422,
        "workflow_not_found": 404,
        "workflow_not_agent_canvas": 409,
        "presentation_stream_not_found": 404,
        "presentation_stream_cursor_expired": 409,
        "presentation_stream_cursor_invalid": 422,
        "presentation_stream_superseded": 409,
        "presentation_stream_backpressure_exceeded": 409,
        "presentation_stream_identity_conflict": 409,
        "presentation_stream_unavailable": 503,
        "presentation_timing_invalid": 422,
        "agent_settings_revision_conflict": 412,
        "agent_document_not_found": 404,
        "agent_document_workflow_mismatch": 409,
        "agent_document_kind_unsupported": 422,
        "agent_document_revision_conflict": 409,
        "agent_document_patch_invalid": 422,
        "agent_document_anchor_source_invalid": 422,
        "agent_document_anchor_alias_conflict": 409,
        "agent_document_storyboard_sequence_invalid": 422,
        "agent_document_cross_workflow_reference": 409,
        "pagination_invalid": 422,
        "node_not_found": 404,
        "binding_not_found": 404,
        "asset_not_found": 404,
        "guided_interaction_action_not_allowed": 422,
        "guided_interaction_submission_conflict": 409,
        "guided_interaction_not_found": 404,
        "guided_interaction_stale": 409,
        "guided_reference_source_kind_invalid": 409,
        "guided_reference_source_target_invalid": 409,
        "guided_reference_source_revision_conflict": 409,
        "guided_reference_source_asset_required": 422,
        "guided_reference_source_asset_not_found": 404,
        "guided_reference_source_asset_foreign_workflow": 409,
        "guided_reference_source_asset_unreadable": 422,
        "guided_reference_source_asset_not_image": 422,
        "reference_candidate_not_found": 404,
        "reference_candidate_cursor_invalid": 422,
        "reference_candidates_unavailable": 503,
        "guided_product_asset_not_found": 404,
        "guided_product_asset_foreign_workflow": 409,
        "guided_product_asset_not_image": 422,
        "guided_product_asset_unreadable": 422,
        "guided_product_input_invalid": 422,
        "guided_product_stage_invalid": 409,
        "guided_product_main_required": 422,
        "guided_product_multiview_count_invalid": 422,
        "guided_product_ffmpeg_unavailable": 503,
        "guided_product_multiview_compilation_failed": 422,
        "guided_product_input_already_committed": 409,
        "guided_product_persistence_unavailable": 503,
        "guided_product_source_only_not_runnable": 409,
        "asset_not_ready": 409,
        "canvas_asset_reference_version_required": 422,
        "canvas_asset_reference_media_type_invalid": 422,
        "asset_reference_version_required": 422,
        "editing_export_workflow_mismatch": 409,
        "editing_export_not_ready": 409,
        "editing_export_asset_unreadable": 409,
        "editing_export_import_conflict": 409,
        "editing_manifest_projection_invalid": 500,
        "source_only_node_not_runnable": 409,
        "target_not_found": 404,
        "target_type_not_supported": 422,
        "locator_invalid": 422,
        "unsupported_canvas_model": 422,
        "workflow_revision_conflict": 412,
        "workflow_state_conflict": 409,
        "requirement_ledger_not_found": 404,
        "requirement_revision_conflict": 412,
        "requirement_patch_invalid": 422,
        "character_occurrence_reconciliation_conflict": 409,
        "character_occurrence_cardinality_mismatch": 409,
        "requirement_scope_invalid": 422,
        "requirement_directive_not_found": 422,
        "requirement_projection_budget_exceeded": 422,
        "idempotency_key_required": 422,
        "idempotency_conflict": 409,
        "decision_bundle_not_found": 404,
        "decision_bundle_closed": 409,
        "decision_bundle_revision_conflict": 409,
        "decision_bundle_answer_invalid": 422,
        "decision_bundle_effect_invalid": 422,
        "style_skill_activation_conflict": 409,
        "style_skill_snapshot_invalid": 422,
        "style_skill_context_budget_exceeded": 422,
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
        "editing_timeline_duration_invalid": 422,
        "editing_timeline_out_of_bounds": 422,
        "editing_timeline_overlap": 422,
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
        "chat_turn_not_failed": 409,
        "chat_turn_not_retryable": 409,
        "chat_turn_retry_stale": 409,
        "chat_turn_retry_in_progress": 409,
        "guidance_advance_stale": 409,
        "guidance_advance_not_available": 409,
        "guidance_advance_blocked_by_failed_turn": 409,
        "guidance_action_lineage_invalid": 409,
        "active_continuation_conflict": 409,
        "guidance_state_inconsistent": 409,
        "guidance_post_ready_pending": 409,
        "post_ready_progression_failed": 409,
        "post_ready_checkpoint_unavailable": 409,
        "guidance_session_not_found": 404,
        "guidance_revision_conflict": 409,
        "journey_transition_invalid": 422,
        "journey_revision_conflict": 409,
        "journey_policy_unsupported": 409,
        "journey_state_invalid": 422,
        "journey_stage_action_mismatch": 409,
        "journey_stage_exclusion_not_allowed": 422,
        "journey_custom_input_invalid": 422,
        "journey_action_in_progress": 409,
        "journey_evidence_invalid": 422,
        "guidance_goal_required": 422,
        "guidance_topic_conflict": 409,
        "guidance_topic_owner_invalid": 422,
        "proposal_not_found": 404,
        "proposal_not_pending": 409,
        "proposal_option_not_found": 422,
        "proposal_revision_conflict": 409,
        "proposal_materialization_conflict": 409,
        "materialization_payload_conflict": 409,
        "proposal_reference_plan_invalid": 422,
        "proposal_target_revision_stale": 409,
        "proposal_reference_revision_stale": 409,
        "proposal_publication_invalid": 422,
        "proposal_publication_failed": 503,
        "capability_materialization_context_invalid": 422,
        "capability_materialization_contract_invalid": 422,
        "capability_materialization_failed": 503,
        "capability_materialization_unavailable": 503,
        "video_skill_not_found": 404,
        "video_skill_preview_not_found": 404,
        "skill_not_found": 404,
        "skill_catalog_cursor_invalid": 422,
        "skill_catalog_page_invalid": 422,
        "agent_skill_manifest_invalid": 503,
        "agent_skill_file_missing": 503,
        "agent_skill_digest_mismatch": 503,
        "execution_not_found": 404,
        "execution_workflow_mismatch": 409,
        "execution_already_terminal": 409,
        "execution_cancel_failed": 503,
        "execution_persistence_failed": 503,
        "node_not_runnable": 422,
        "node_already_ready": 409,
        "node_already_working": 409,
        "failed_node_retry_required": 409,
        "node_model_incompatible": 409,
        "node_prompt_empty": 409,
        "node_prompt_preparation_incomplete": 409,
        "prompt_preparation_revision_conflict": 409,
        "prompt_preparation_failed": 503,
        "stage_content_mismatch": 422,
        "storyboard_sequence_invalid": 422,
        "storyboard_anchor_resolution_failed": 422,
        "storyboard_fanout_invalid": 422,
        "storyboard_visual_anchor_stale": 409,
        "execution_required_dependency_failed": 409,
        "guided_media_confirmation_required": 409,
        "guided_media_confirmation_stale": 409,
        "guided_media_asset_unreadable": 409,
        "identity_safety_decision_required": 409,
        "identity_safety_decision_invalid": 422,
        "identity_safety_decision_stale": 409,
        "guided_media_replacement_instruction_required": 422,
        "guided_closure_blocked": 409,
        "guided_closure_plan_stale": 409,
        "editing_preparation_plan_conflict": 409,
        "editing_preparation_plan_invalid": 422,
        "guided_export_not_completed": 409,
        "guided_export_commit_mismatch": 409,
        "guided_export_preparation_stale": 409,
        "guided_final_asset_unreadable": 409,
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


def _projected_node(workflow: AgentCanvasWorkflowV2, node_id: str) -> CanvasNodeV2:
    node = next((node for node in workflow.nodes if node.node_id == node_id), None)
    if node is None:
        raise V2PersistenceError(
            "node_not_found",
            "Node was not found.",
            stage="agent_canvas_editing_response_projector",
        )
    return node


def _provider_download_mime_type(media_type: str, path: Path | str) -> str:
    """Keep canonical publication aligned with validated provider bytes."""

    if media_type == "video":
        return "video/mp4"
    if media_type == "audio":
        return "audio/wav" if Path(path).suffix.lower() == ".wav" else "audio/mpeg"
    raise V2PersistenceError(
        "provider_output_invalid",
        "Provider output has an unsupported media type.",
        stage="agent_canvas_provider_recovery",
    )


def _image_library_response(items) -> ImageLibraryListResponseV2:
    return ImageLibraryListResponseV2(items=tuple(item.model_dump(mode="json") for item in items))
