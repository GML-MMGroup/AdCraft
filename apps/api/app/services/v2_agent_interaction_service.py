"""Pi-owned cognition for exact V2 Character and Scene interactions."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from app.core.config import Settings
from app.persistence.v2_agent_conversation_repository import (
    V2AgentConversationRepositoryError,
)
from app.schemas.canvas_targets import NormalizedCanvasTarget
from app.schemas.specialist_agents import (
    SpecialistAgentName,
    SpecialistInvocationRequest,
)
from app.schemas.workflow_v2 import (
    SelectSlotVersionRequestV2,
    WorkflowV2,
    WorkflowV2ChatActionRequest,
    WorkflowV2ChatActionResponse,
    WorkflowV2ResolvedChatActionTarget,
    WorkflowV2RunResponse,
    WorkflowV2WorkingVersionView,
)
from app.services.agent_trace import V2AgentTraceWriter, utc_now
from app.services.specialist_agents import SpecialistAgentError, SpecialistAgentService
from app.services.v2_agent_target_resolver import (
    V2AgentTargetResolutionError,
    V2AgentTargetResolver,
)
from app.services.v2_pi_agent_context import (
    ConversationContextSource,
    V2AgentContextBuilder,
)
from app.services.v2_workflow_assets import V2WorkflowAssetError, V2WorkflowAssetService


class V2AgentInteractionDomain(Protocol):
    def get_workflow(self, workflow_id: str) -> WorkflowV2: ...

    def apply_agent_prompt_revision(
        self,
        workflow_id: str,
        slot_id: str,
        *,
        revised_prompt: str,
        negative_prompt: str | None,
        expected_revision: int,
    ) -> WorkflowV2: ...

    def generate_agent_candidate(
        self,
        workflow_id: str,
        slot_id: str,
    ) -> WorkflowV2RunResponse: ...

    def discard_working_version(self, workflow_id: str, slot_id: str) -> WorkflowV2: ...

    def append_agent_interaction_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        node_id: str,
        item_id: str,
        slot_id: str,
        asset_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    def write_agent_interaction_audit(
        self,
        workflow_id: str,
        action_id: str,
        payload: dict[str, Any],
    ) -> None: ...


class V2AgentInteractionError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2AgentInteractionService:
    """Resolve, invoke, validate, and apply one exact Agent chat action."""

    def __init__(
        self,
        settings: Settings,
        *,
        domain: V2AgentInteractionDomain,
        target_resolver: V2AgentTargetResolver | None = None,
        conversation_context_source: ConversationContextSource | None = None,
        specialist_service: SpecialistAgentService | None = None,
    ) -> None:
        self._domain = domain
        self._target_resolver = target_resolver or V2AgentTargetResolver(settings)
        optional_conversation_source = (
            _OptionalConversationContextSource(conversation_context_source)
            if conversation_context_source is not None
            else None
        )
        self._context_builder = V2AgentContextBuilder(
            settings,
            conversation_context_source=optional_conversation_source,
        )
        self._specialist_service = specialist_service or SpecialistAgentService(
            settings,
            trace_writer_factory=V2AgentTraceWriter,
        )
        self._asset_service = V2WorkflowAssetService(settings.media_data_dir)

    def execute_chat_action(
        self,
        workflow_id: str,
        request: WorkflowV2ChatActionRequest,
    ) -> WorkflowV2ChatActionResponse:
        action_mode = _resolve_action_mode(request)
        conversation_id = str(request.metadata.get("conversation_id") or f"conv_{workflow_id}")
        action_id = str(request.metadata.get("action_id") or "").strip() or (
            f"act_{uuid4().hex[:12]}"
        )
        try:
            target = self._target_resolver.resolve(workflow_id, request.target)
        except V2AgentTargetResolutionError as exc:
            raise V2AgentInteractionError(exc.code, str(exc)) from exc
        specialist = _specialist_for_target(target.node_id)
        self._domain.append_agent_interaction_event(
            workflow_id,
            "chat_action_created",
            node_id=target.node_id,
            item_id=target.item_id,
            slot_id=target.slot_id,
            asset_id=target.asset_id,
            payload={
                "action_id": action_id,
                "conversation_id": conversation_id,
                "action_mode": action_mode,
                "target": request.target.model_dump(mode="json"),
            },
        )
        self._domain.append_agent_interaction_event(
            workflow_id,
            "chat_action_resolved",
            node_id=target.node_id,
            item_id=target.item_id,
            slot_id=target.slot_id,
            asset_id=target.asset_id,
            payload={"action_id": action_id, "specialist": specialist},
        )
        events = ["chat_action_created", "chat_action_resolved"]
        working_version: WorkflowV2WorkingVersionView | None = None

        if action_mode in {"revise_prompt", "revise_and_generate"}:
            workflow = self._revise_prompt(
                workflow_id=workflow_id,
                conversation_id=conversation_id,
                action_id=action_id,
                request=request,
                specialist=specialist,
                target=target,
            )
            events.append("slot_prompt_updated")
            if action_mode == "revise_and_generate":
                run = self._domain.generate_agent_candidate(workflow_id, target.slot_id)
                workflow = run.workflow
                slot = _find_slot(workflow, target.slot_id)
                if slot.current_working_asset_id and slot.current_working_version_id:
                    working_version = WorkflowV2WorkingVersionView(
                        asset_id=slot.current_working_asset_id,
                        version_id=slot.current_working_version_id,
                    )
                events.append("slot_working_version_updated")
                message = "Generated a new working version for the target slot."
            else:
                message = "Updated the target slot prompt."
        elif action_mode == "select_version":
            asset_id = request.asset_id or request.target.asset_id or target.asset_id
            version_id = request.version_id or request.target.version_id or target.version_id
            if not asset_id or not version_id:
                raise V2AgentInteractionError("version_not_found")
            try:
                self._asset_service.select_slot_version(
                    workflow_id,
                    target.slot_id,
                    SelectSlotVersionRequestV2(asset_id=asset_id, version_id=version_id),
                )
            except V2WorkflowAssetError as exc:
                raise V2AgentInteractionError(exc.code, str(exc)) from exc
            workflow = self._domain.get_workflow(workflow_id)
            events.append("slot_selected_version_updated")
            message = "Selected the requested version for the target slot."
        else:
            workflow = self._domain.discard_working_version(workflow_id, target.slot_id)
            events.append("slot_working_version_discarded")
            message = "Discarded the current working version for the target slot."

        resolved_target = WorkflowV2ResolvedChatActionTarget(
            node_id=target.node_id,
            item_id=target.item_id,
            slot_id=target.slot_id,
            slot_type=target.slot_type,
        )
        response = WorkflowV2ChatActionResponse(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            action_id=action_id,
            target=request.target,
            resolved_target=resolved_target,
            specialist=specialist,
            action_mode=action_mode,
            applied=True,
            working_version=working_version,
            events=list(dict.fromkeys(events)),
            message=message,
            workflow=workflow,
        )
        self._domain.write_agent_interaction_audit(
            workflow_id,
            action_id,
            {
                "workflow_id": workflow_id,
                "conversation_id": conversation_id,
                "action_id": action_id,
                "original_user_message": request.message,
                "target": request.target.model_dump(mode="json"),
                "resolved_target": resolved_target.model_dump(mode="json"),
                "specialist": specialist,
                "action_mode": action_mode,
                "created_at": utc_now().isoformat(),
                "status": "completed",
                "generated": working_version.model_dump(mode="json") if working_version else None,
                "error_code": None,
            },
        )
        return response

    def _revise_prompt(
        self,
        *,
        workflow_id: str,
        conversation_id: str,
        action_id: str,
        request: WorkflowV2ChatActionRequest,
        specialist: SpecialistAgentName,
        target: Any,
    ) -> WorkflowV2:
        context = self._context_builder.build_targeted_revision(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            target=target,
            user_instruction=request.message,
        )
        requested_revision = request.metadata.get("expected_revision")
        expected_revision = (
            int(requested_revision)
            if requested_revision is not None
            else context.target.expected_revision
        )
        if expected_revision != context.target.expected_revision:
            raise V2AgentInteractionError(
                "workflow_state_conflict",
                "The workflow changed before this Agent action could be applied.",
            )
        normalized_target = NormalizedCanvasTarget(
            workflow_id=workflow_id,
            target_type="item",
            node_id=target.node_id,
            node_type=target.node_id,
            item_id=target.item_id,
            asset_id=target.asset_id,
            semantic_type=target.slot_type,
            display_name=target.display_name,
            metadata={
                "slot_id": target.slot_id,
                "version_id": target.version_id,
                "target_locator": target.target_locator,
            },
        )
        invocation = SpecialistInvocationRequest(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            specialist=specialist,
            action="revise_item_prompt",
            target=normalized_target,
            user_instruction=request.message,
            current_prompt=context.target.current_prompt,
            director_context_summary={
                "style_scope": context.style_scope,
                "continuity_slice": context.continuity_slice,
            },
            script_context_summary={"screenplay_slice": context.screenplay_slice},
            target_item_context=context.target.model_dump(mode="json"),
            target_asset_summary=(
                context.target.selected_version.model_dump(mode="json")
                if context.target.selected_version
                else {}
            ),
            reference_asset_summary=[
                summary.model_dump(mode="json") for summary in context.reference_summaries
            ],
            memory_summary={
                "summary": context.conversation_summary,
                "recent_messages": [
                    message.model_dump(mode="json") for message in context.recent_messages
                ],
            },
            constraints={
                "action_id": action_id,
                "expected_revision": expected_revision,
                "requested_scope": target.requested_scope,
            },
        )
        try:
            outcome = self._specialist_service.invoke(invocation)
        except SpecialistAgentError as exc:
            raise V2AgentInteractionError(exc.code, str(exc)) from exc
        result = outcome.result
        if (
            result.specialist != specialist
            or result.target != normalized_target
            or result.result_type not in {"revised_item_prompt", "revised_node_prompt"}
            or not result.revised_prompt
        ):
            raise V2AgentInteractionError(
                "specialist_output_invalid",
                "The owning expert returned an invalid revision.",
            )
        return self._domain.apply_agent_prompt_revision(
            workflow_id,
            target.slot_id,
            revised_prompt=result.revised_prompt,
            negative_prompt=result.negative_prompt,
            expected_revision=expected_revision,
        )


def _resolve_action_mode(request: WorkflowV2ChatActionRequest) -> str:
    if request.action_mode == "auto":
        raise V2AgentInteractionError(
            "clarification_required",
            "Choose revise, generate, select, or discard.",
        )
    return request.action_mode


def _specialist_for_target(node_id: str) -> SpecialistAgentName:
    if node_id == "character-generation":
        return "character_designer"
    if node_id == "scene-generation":
        return "scene_designer"
    raise V2AgentInteractionError("agent_target_not_supported")


def _find_slot(workflow: WorkflowV2, slot_id: str) -> Any:
    for node in workflow.nodes:
        for item in node.items:
            for slot in item.slots:
                if slot.slot_id == slot_id:
                    return slot
    raise V2AgentInteractionError("slot_not_found")


class _OptionalConversationContextSource:
    def __init__(self, source: ConversationContextSource) -> None:
        self._source = source

    def load_context(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> tuple[str, list[dict[str, object]]]:
        try:
            return self._source.load_context(conversation_id, limit=limit)
        except V2AgentConversationRepositoryError as exc:
            if exc.code != "agent_conversation_not_found":
                raise
            return "", []
