from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.chat_workflow import ChatWorkflowResponse
from app.schemas.front_desk import FrontDeskChatRequest
from app.services.ad_workflow import AdWorkflowService, WorkflowGenerationError
from app.services.front_desk import FrontDeskError, FrontDeskService


class ChatWorkflowError(RuntimeError):
    """Raised when the natural-language workflow orchestration fails."""


def _chat_ad_request_updates(
    request: FrontDeskChatRequest,
    ad_request: AdWorkflowGenerateRequest,
) -> dict[str, object]:
    updates: dict[str, object] = {}
    if request.skip_audio_agents:
        updates["skip_audio_agents"] = True
    if request.selected_assets:
        updates["selected_assets"] = [
            *ad_request.selected_assets,
            *request.selected_assets,
        ]
    if request.asset_references:
        updates["asset_references"] = [
            *ad_request.asset_references,
            *request.asset_references,
        ]
    if request.library_entity_ids:
        updates["library_entity_ids"] = [
            *ad_request.library_entity_ids,
            *request.library_entity_ids,
        ]
    if request.reference_mode != "strict":
        updates["reference_mode"] = request.reference_mode
    return updates


class ChatWorkflowService:
    def __init__(
        self,
        settings: Settings,
        front_desk_service: FrontDeskService | None = None,
        ad_workflow_service: AdWorkflowService | None = None,
    ) -> None:
        self._settings = settings
        self._front_desk_service = front_desk_service or FrontDeskService(settings)
        self._ad_workflow_service = ad_workflow_service or AdWorkflowService(settings)

    def generate_from_chat(self, request: FrontDeskChatRequest) -> ChatWorkflowResponse:
        try:
            front_desk_response = self._front_desk_service.chat(request)
        except FrontDeskError as exc:
            raise ChatWorkflowError(f"front_desk_failed: {exc}") from exc
        except Exception as exc:
            raise ChatWorkflowError(f"front_desk_failed: {exc}") from exc

        if not front_desk_response.should_start_workflow:
            return ChatWorkflowResponse(front_desk=front_desk_response)

        if front_desk_response.ad_request is None:
            raise ChatWorkflowError(
                "invalid_front_desk_state: should_start_workflow=true but ad_request is missing"
            )

        ad_request = front_desk_response.ad_request
        updates = _chat_ad_request_updates(request, ad_request)
        if updates:
            ad_request = ad_request.model_copy(update=updates)

        try:
            workflow = self._ad_workflow_service.generate(ad_request)
        except WorkflowGenerationError as exc:
            raise ChatWorkflowError(f"workflow_generation_failed: {exc}") from exc
        except Exception as exc:
            raise ChatWorkflowError(f"workflow_generation_failed: {exc}") from exc

        return ChatWorkflowResponse(front_desk=front_desk_response, workflow=workflow)
