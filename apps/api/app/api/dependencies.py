from app.core.config import PROJECT_ROOT, get_settings
from app.services.ad_workflow import AdWorkflowService
from app.services.agent_conversations import AgentConversationService
from app.services.asset_library import AssetLibraryService
from app.services.asset_reference_suggestions import AssetReferenceSuggestionService
from app.services.assets import AssetService
from app.services.chat_workflow import ChatWorkflowService
from app.services.chat_workflow_stream import ChatWorkflowStreamService
from app.services.canvas_runtime_events import CanvasRuntimeEventService, CanvasRuntimeService
from app.services.front_desk import FrontDeskService
from app.services.final_composition_timeline import FinalCompositionTimelineService
from app.services.media_tasks import MediaTaskService
from app.services.provider_identity_certification import IdentityCertificationRegistry
from app.services.provider_credentials import (
    DotenvCredentialStore,
    ProviderCredentialRegistry,
    RuntimeCredentialService,
)
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


def get_ad_workflow_service() -> AdWorkflowService:
    return AdWorkflowService(settings=get_settings())


def get_front_desk_service() -> FrontDeskService:
    return FrontDeskService(settings=get_settings())


def get_chat_workflow_service() -> ChatWorkflowService:
    return ChatWorkflowService(settings=get_settings())


def get_asset_service() -> AssetService:
    return AssetService(settings=get_settings())


def get_asset_library_service() -> AssetLibraryService:
    return AssetLibraryService(settings=get_settings())


def get_asset_reference_suggestion_service() -> AssetReferenceSuggestionService:
    return AssetReferenceSuggestionService(settings=get_settings())


def get_chat_workflow_stream_service() -> ChatWorkflowStreamService:
    return ChatWorkflowStreamService(settings=get_settings())


def get_canvas_runtime_service() -> CanvasRuntimeService:
    return CanvasRuntimeService(settings=get_settings())


def get_canvas_runtime_event_service() -> CanvasRuntimeEventService:
    return CanvasRuntimeEventService(data_dir=get_settings().media_data_dir)


def get_agent_conversation_service() -> AgentConversationService:
    return AgentConversationService(settings=get_settings())


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


def get_runtime_credential_service() -> RuntimeCredentialService:
    registry = ProviderCredentialRegistry()
    definition = registry.get("volcengine_ark")
    return RuntimeCredentialService(
        registry=registry,
        dotenv_store=DotenvCredentialStore(
            PROJECT_ROOT,
            allowed_fields={binding.dotenv_field for binding in definition.bindings.values()},
        ),
    )
