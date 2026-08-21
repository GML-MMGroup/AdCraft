from collections.abc import Iterator

from fastapi import Depends, HTTPException

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.persistence.database import create_v2_database
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.provider_model_repository import ProviderModelRepository
from app.services.asset_library import AssetLibraryService
from app.services.asset_reference_suggestions import AssetReferenceSuggestionService
from app.services.assets import AssetService
from app.services.canvas_runtime_events import CanvasRuntimeEventService, CanvasRuntimeService
from app.services.front_desk import FrontDeskService
from app.services.final_composition_timeline import FinalCompositionTimelineService
from app.services.media_tasks import MediaTaskService
from app.services.provider_identity_certification import IdentityCertificationRegistry
from app.services.provider_credentials import (
    DotenvCredentialStore,
    LegacyVolcengineCredentialAdapter,
    ProviderConnectionService,
    ProviderCredentialRegistry,
)
from app.services.provider_model_catalog import ProviderModelCatalogService
from app.services.video_editing import VideoEditingService
from app.services.workflow_graph import WorkflowGraphService
from app.services.workflow_input_resolver import WorkflowNodeInputResolver
from app.services.workflow_item_prompts import WorkflowItemPromptService
from app.services.workflow_local_revisions import WorkflowLocalRevisionService
from app.services.workflow_run import WorkflowCanvasExecutionService
from app.services.workflow_nodes import WorkflowNodeExecutionService
from app.services.workflow_plan import AdWorkflowPlanService
from app.services.workflow_quality_review import WorkflowQualityReviewService
from app.services.workflow_working_versions import WorkflowWorkingVersionService
from app.services.v1_workflow_authority import (
    V1WorkflowAuthorityBoundary,
    V1WorkflowAuthorityError,
)


def get_front_desk_service() -> FrontDeskService:
    return FrontDeskService(settings=get_settings())


def get_asset_service() -> AssetService:
    return AssetService(settings=get_settings())


def get_asset_library_service() -> AssetLibraryService:
    return AssetLibraryService(settings=get_settings())


def get_asset_reference_suggestion_service() -> AssetReferenceSuggestionService:
    return AssetReferenceSuggestionService(settings=get_settings())


def get_canvas_runtime_service() -> CanvasRuntimeService:
    return CanvasRuntimeService(settings=get_settings())


def get_canvas_runtime_event_service() -> CanvasRuntimeEventService:
    return CanvasRuntimeEventService(data_dir=get_settings().media_data_dir)


def get_video_editing_service() -> VideoEditingService:
    return VideoEditingService(settings=get_settings())


def get_final_composition_timeline_service() -> FinalCompositionTimelineService:
    return FinalCompositionTimelineService(settings=get_settings())


def get_workflow_node_execution_service() -> WorkflowNodeExecutionService:
    return WorkflowNodeExecutionService(settings=get_settings())


def get_media_task_service() -> MediaTaskService:
    return MediaTaskService(settings=get_settings())


def get_identity_certification_registry() -> IdentityCertificationRegistry:
    return IdentityCertificationRegistry(settings=get_settings())


def get_workflow_canvas_execution_service() -> WorkflowCanvasExecutionService:
    return WorkflowCanvasExecutionService(settings=get_settings())


def get_ad_workflow_plan_service() -> AdWorkflowPlanService:
    return AdWorkflowPlanService(settings=get_settings())


def get_workflow_graph_service() -> WorkflowGraphService:
    return WorkflowGraphService(data_dir=get_settings().media_data_dir)


def get_workflow_node_input_resolver() -> WorkflowNodeInputResolver:
    return WorkflowNodeInputResolver(settings=get_settings())


def get_workflow_item_prompt_service() -> WorkflowItemPromptService:
    return WorkflowItemPromptService(settings=get_settings())


def get_workflow_local_revision_service() -> WorkflowLocalRevisionService:
    return WorkflowLocalRevisionService(settings=get_settings())


def get_workflow_quality_review_service() -> WorkflowQualityReviewService:
    return WorkflowQualityReviewService(settings=get_settings())


def get_workflow_working_version_service() -> WorkflowWorkingVersionService:
    return WorkflowWorkingVersionService(settings=get_settings())


def get_v1_workflow_authority_boundary(
    settings: Settings = Depends(get_settings),
) -> Iterator[V1WorkflowAuthorityBoundary]:
    """Build the read-only SQLite authority boundary for one V1 request."""

    database = create_v2_database(settings.media_data_dir)
    repository = AgentCanvasWorkflowRepository(
        database,
        ProjectRepository(database),
        EventRepository(database),
    )
    try:
        yield V1WorkflowAuthorityBoundary(repository)
    finally:
        database.dispose()


def require_v1_workflow_authority(
    workflow_id: str,
    boundary: V1WorkflowAuthorityBoundary = Depends(get_v1_workflow_authority_boundary),
) -> None:
    """Fail before a legacy route touches an SQLite-owned workflow."""

    try:
        boundary.assert_legacy_workflow(workflow_id)
    except V1WorkflowAuthorityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def get_runtime_credential_service() -> Iterator[LegacyVolcengineCredentialAdapter]:
    """Keep the legacy Volcengine endpoint on the canonical mutation path."""

    settings = get_settings()
    database = create_v2_database(settings.media_data_dir)
    try:
        yield LegacyVolcengineCredentialAdapter(
            _provider_connection_service(settings, ProviderModelRepository(database))
        )
    finally:
        database.dispose()


def get_provider_connection_service(
    settings: Settings = Depends(get_settings),
) -> Iterator[ProviderConnectionService]:
    """Build the canonical local provider configuration service per request."""

    database = create_v2_database(settings.media_data_dir)
    service = _provider_connection_service(settings, ProviderModelRepository(database))
    try:
        yield service
    finally:
        database.dispose()


def get_provider_model_catalog_service(
    settings: Settings = Depends(get_settings),
) -> Iterator[ProviderModelCatalogService]:
    """Build catalog policy from SQLite and current local connection state."""

    database = create_v2_database(settings.media_data_dir)
    repository = ProviderModelRepository(database)
    service = ProviderModelCatalogService(repository)
    try:
        yield service
    finally:
        database.dispose()


def _provider_connection_service(
    settings: Settings,
    repository: ProviderModelRepository,
) -> ProviderConnectionService:
    registry = ProviderCredentialRegistry()
    service = ProviderConnectionService(
        registry=registry,
        dotenv_store=DotenvCredentialStore(
            PROJECT_ROOT,
            allowed_fields={
                binding.dotenv_field
                for provider_id in registry.provider_ids
                for binding in registry.get(provider_id).bindings.values()
            },
        ),
        metadata_repository=repository,
        settings_loader=lambda: get_settings(),
    )
    service.migrate_legacy_siliconflow_text_key()
    return service
