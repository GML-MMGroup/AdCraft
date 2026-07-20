from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.agent_conversations import (
    VISIBLE_AGENTS,
    AgentConversation,
    AgentConversationEvent,
    AgentConversationMessageRequest,
    AgentConversationRejectActionRequest,
    SuggestedAction,
)
from app.schemas.director_context import DirectorContext
from app.schemas.front_desk import FrontDeskChatRequest, FrontDeskChatResponse
from app.schemas.workflow_graph import (
    WorkflowGraphNodePatchRequest,
)
from app.schemas.workflow_nodes import WorkflowNodeRevisionRequest, WorkflowNodeRunRequest
from app.schemas.workflow_revisions import WorkflowRevisionRequest
from app.services.agent_trace import utc_now
from app.services.director_context import load_director_context, save_director_context
from app.services.workflow_local_revisions import (
    WorkflowLocalRevisionError,
    WorkflowLocalRevisionService,
)
from app.services.workflow_node_identity import resolve_node_identity

from app.services.agent_conversation_common import (
    AgentConversationInputError,
    SPECIALIST_BY_NODE,
    VISIBLE_AGENT_TO_NODE,
    _action_summary,
    _action_title,
    _dict_payload,
    _optional_str,
)


class AgentConversationActionsMixin:
    def apply_action(
        self, conversation_id: str, action_id: str
    ) -> tuple[list[AgentConversationEvent], SuggestedAction]:
        conversation = self._load(conversation_id)
        action = self._require_action(conversation, action_id)
        if action.status == "applied":
            event = self._event(
                conversation=conversation,
                event_type="action_applied",
                speaker_agent="creative_director",
                target_node_id=action.target_node_id,
                text=f"Action already applied: {action.title}",
                metadata={
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "already_applied": True,
                },
            )
            self._append_events(conversation, [event], [])
            return [event], action
        if action.status != "pending":
            event = self._error_event(
                conversation=conversation,
                error_code="action_not_pending",
                message=f"Action is {action.status}.",
                target_agent=action.speaker_agent,
                target_node_id=action.target_node_id,
                recoverable=False,
            )
            self._append_events(conversation, [event], [])
            return [event], action

        try:
            apply_result = self._execute_action(action)
        except Exception as exc:  # noqa: BLE001 - apply failures are conversation events.
            now = utc_now().isoformat()
            action.status = "failed"
            action.updated_at = now
            action.metadata = {**action.metadata, "error": str(exc)}
            event = self._error_event(
                conversation=conversation,
                error_code="apply_failed",
                message=str(exc),
                target_agent=action.speaker_agent,
                target_node_id=action.target_node_id,
                recoverable=True,
            )
            self._append_events(conversation, [event], [])
            return [event], action

        action.status = "applied"
        action.updated_at = utc_now().isoformat()
        action.metadata = {**action.metadata, "apply_result": apply_result}
        event = self._event(
            conversation=conversation,
            event_type="action_applied",
            speaker_agent="creative_director",
            target_agent=action.speaker_agent,
            target_node_id=action.target_node_id,
            text=f"Applied: {action.title}",
            metadata={
                "action_id": action.action_id,
                "action_type": action.action_type,
                "already_applied": False,
            },
        )
        self._append_events(conversation, [event], [])
        return [event], action

    def reject_action(
        self,
        conversation_id: str,
        action_id: str,
        request: AgentConversationRejectActionRequest,
    ) -> tuple[list[AgentConversationEvent], SuggestedAction]:
        conversation = self._load(conversation_id)
        action = self._require_action(conversation, action_id)
        if action.status == "pending":
            action.status = "rejected"
            action.updated_at = utc_now().isoformat()
        event = self._event(
            conversation=conversation,
            event_type="action_rejected",
            speaker_agent="creative_director",
            target_agent=action.speaker_agent,
            target_node_id=action.target_node_id,
            text=f"Rejected: {action.title}",
            metadata={
                "action_id": action.action_id,
                "action_type": action.action_type,
                "reason": request.reason,
            },
        )
        self._append_events(conversation, [event], [])
        return [event], action

    def _front_desk_response(
        self, request: AgentConversationMessageRequest
    ) -> FrontDeskChatResponse:
        return self._front_desk.chat(
            FrontDeskChatRequest(
                message=request.message,
                asset_references=request.asset_references,
            )
        )

    def _target_agent(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        front_desk: FrontDeskChatResponse,
    ) -> str | None:
        mentions = [mention.strip() for mention in request.agent_mentions if mention.strip()]
        self._validate_mentions(mentions)
        if mentions:
            return mentions[0]
        if front_desk.suggested_agent in VISIBLE_AGENTS:
            return front_desk.suggested_agent
        if front_desk.target_node_id and front_desk.workflow_action in {
            "modify_node",
            "run_node",
        }:
            agent = SPECIALIST_BY_NODE.get(front_desk.target_node_id)
            if agent:
                return agent
        inferred = self._infer_agent_from_message(request.message)
        if inferred:
            return inferred
        if conversation.focus_node_id and self._message_requests_node_action(request.message):
            return SPECIALIST_BY_NODE.get(conversation.focus_node_id)
        return "creative_director"

    def _target_node_id(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        target_agent: str | None,
        front_desk: FrontDeskChatResponse,
    ) -> str | None:
        selected = request.context.get("selected_node_id")
        if isinstance(selected, str) and selected:
            return selected
        if target_agent and VISIBLE_AGENT_TO_NODE.get(target_agent):
            return VISIBLE_AGENT_TO_NODE[target_agent]
        if front_desk.target_node_id:
            return front_desk.target_node_id
        return conversation.focus_node_id

    def _suggested_action(
        self,
        *,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        front_desk: FrontDeskChatResponse,
        speaker_agent: str,
        target_node_id: str | None,
    ) -> SuggestedAction | None:
        action_type = self._action_type(request.message, front_desk, speaker_agent)
        if action_type is None:
            return None
        now = utc_now().isoformat()
        action_id = f"act_{uuid4().hex[:12]}"
        asset_references = self._asset_reference_payloads(request.asset_references)
        payload = self._action_payload(
            action_type=action_type,
            action_id=action_id,
            conversation=conversation,
            request=request,
            front_desk=front_desk,
            target_node_id=target_node_id,
            asset_references=asset_references,
        )
        return SuggestedAction(
            action_id=action_id,
            conversation_id=conversation.conversation_id,
            action_type=action_type,
            status="pending",
            speaker_agent=speaker_agent,  # type: ignore[arg-type]
            workflow_id=conversation.workflow_id,
            target_node_id=target_node_id,
            title=_action_title(action_type),
            summary=_action_summary(action_type, target_node_id),
            payload=payload,
            created_at=now,
            updated_at=now,
            metadata={"asset_references": asset_references},
        )

    def _action_type(
        self,
        message: str,
        front_desk: FrontDeskChatResponse,
        speaker_agent: str,
    ) -> str | None:
        lowered = message.lower()
        if front_desk.should_start_workflow:
            return "create_workflow"
        if "update" in lowered and ("director" in lowered or "global" in lowered):
            return "update_director_context"
        if "全局" in message or "整体创意" in message:
            return "update_director_context"
        if speaker_agent == "creative_director":
            return None
        if "optimize" in lowered or "优化" in message:
            return "optimize_node_prompt"
        if "revise" in lowered or "regenerate" in lowered or "局部" in message:
            return "revise_node_asset"
        if "run" in lowered or "generate" in lowered or "运行" in message or "生成" in message:
            return "run_node"
        return "apply_prompt_to_node"

    def _action_payload(
        self,
        *,
        action_type: str,
        action_id: str,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
        front_desk: FrontDeskChatResponse,
        target_node_id: str | None,
        asset_references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        input_context = {
            "user_prompt": request.message,
            "agent_conversation_id": conversation.conversation_id,
            "agent_action_id": action_id,
            "asset_references": asset_references,
        }
        if action_type == "create_workflow":
            if front_desk.ad_request is None:
                raise AgentConversationInputError("create_workflow action requires ad_request.")
            return {"ad_request": front_desk.ad_request.model_dump(mode="json")}
        if action_type == "update_director_context":
            return {
                "creative_direction": {"user_update": request.message},
                "source": {
                    "conversation_id": conversation.conversation_id,
                    "action_id": action_id,
                },
            }
        if action_type == "revise_node_asset":
            return {
                "input_context": input_context,
                "asset_references": asset_references,
                "revision": {
                    "mode": "regenerate_asset",
                    "target_asset_id": str(
                        request.context.get("target_asset_id") or "conversation-target-asset"
                    ),
                    "instruction": request.message,
                    "preserve_other_outputs": True,
                },
            }
        if action_type in {"optimize_node_prompt", "run_node"}:
            return {
                "input_context": input_context,
                "asset_references": asset_references,
                "force_rerun": action_type == "run_node",
            }
        return {
            "prompt": request.message,
            "input_context": input_context,
            "asset_references": asset_references,
        }

    def _execute_action(self, action: SuggestedAction) -> dict[str, Any]:
        if action.action_type == "apply_prompt_to_node":
            return self._apply_prompt_to_node(action)
        if action.action_type == "optimize_node_prompt":
            return self._run_node_action(action, optimize_only=True)
        if action.action_type == "run_node":
            return self._run_node_action(action, optimize_only=False)
        if action.action_type == "revise_node_asset":
            return self._revise_node_asset_action(action)
        if action.action_type == "update_director_context":
            return self._update_director_context(action)
        if action.action_type == "create_workflow":
            ad_request = AdWorkflowGenerateRequest.model_validate(
                action.payload.get("ad_request", {})
            )
            workflow = self._plan_service.plan(ad_request)
            return {"workflow": workflow.model_dump(mode="json")}
        raise AgentConversationInputError(f"unsupported action_type: {action.action_type}")

    def _apply_prompt_to_node(self, action: SuggestedAction) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(action)
        target_node_id = self._require_target_node_id(action)
        graph = self._graph_service.get_graph(workflow_id)
        node = next((item for item in graph.nodes if item.id == target_node_id), None)
        if node is None:
            raise AgentConversationInputError(f"unknown target_node_id: {target_node_id}")
        prompt = str(action.payload.get("prompt") or "")
        input_context = {
            **node.input_context,
            **_dict_payload(action.payload.get("input_context")),
            "user_prompt": prompt,
        }
        metadata = {
            **node.metadata,
            "prompt_source": "user",
            "manual_prompt_dirty": True,
            "has_new_system_suggestion": False,
        }
        patched = self._graph_service.patch_node(
            workflow_id,
            target_node_id,
            WorkflowGraphNodePatchRequest(
                prompt=prompt,
                override_prompt=prompt,
                input_context=input_context,
                metadata=metadata,
                status="stale",
                stale=True,
                stale_reason=f"prompt applied from conversation action {action.action_id}",
            ),
        )
        return {
            "workflow_id": workflow_id,
            "target_node_id": target_node_id,
            "workflow_version": patched.version,
        }

    def _run_node_action(self, action: SuggestedAction, *, optimize_only: bool) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(action)
        target_node_id = self._require_target_node_id(action)
        identity = resolve_node_identity(
            data_dir=self._settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=target_node_id,
            node_type=_optional_str(
                action.payload.get("target_node_type") or action.payload.get("node_type")
            ),
        )
        revision_payload = action.payload.get("revision")
        revision = (
            WorkflowNodeRevisionRequest.model_validate(revision_payload)
            if isinstance(revision_payload, dict)
            else None
        )
        result = self._node_service.run(
            WorkflowNodeRunRequest(
                workflow_id=workflow_id,
                node_id=identity.node_id,
                node_type=identity.node_type,
                input_context=_dict_payload(action.payload.get("input_context")),
                save_outputs=True,
                force_rerun=bool(action.payload.get("force_rerun")) or revision is not None,
                auto_resolve=True,
                optimize_only=optimize_only,
                revision=revision,
                asset_references=action.payload.get("asset_references", []),
            )
        )
        return {"node_run": result.model_dump(mode="json")}

    def _revise_node_asset_action(self, action: SuggestedAction) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(action)
        target_node_id = self._require_target_node_id(action)
        identity = resolve_node_identity(
            data_dir=self._settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=target_node_id,
            node_type=_optional_str(
                action.payload.get("target_node_type") or action.payload.get("node_type")
            ),
        )
        revision_payload = action.payload.get("revision")
        if not isinstance(revision_payload, dict):
            raise AgentConversationInputError("revise_node_asset action requires revision payload.")
        revision = WorkflowRevisionRequest.model_validate(
            {
                **revision_payload,
                "asset_references": action.payload.get(
                    "asset_references",
                    revision_payload.get("asset_references", []),
                ),
                "library_entity_ids": action.payload.get(
                    "library_entity_ids",
                    revision_payload.get("library_entity_ids", []),
                ),
                "provider_hints": action.payload.get(
                    "provider_hints",
                    revision_payload.get("provider_hints", {"priority": "capability_first"}),
                ),
                "metadata": _dict_payload(revision_payload.get("metadata")),
            }
        )
        try:
            state = WorkflowLocalRevisionService(self._settings).create_revision(
                workflow_id,
                identity.node_id,
                revision,
                source_metadata={
                    "source_type": "agent_conversation_action",
                    "source_conversation_id": action.conversation_id,
                    "source_action_id": action.action_id,
                },
            )
        except WorkflowLocalRevisionError as exc:
            message = str(exc.detail.get("message") or exc.detail.get("code") or exc)
            raise AgentConversationInputError(message) from exc
        return {"revision": state.model_dump(mode="json")}

    def _update_director_context(self, action: SuggestedAction) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(action)
        existing = load_director_context(self._settings.media_data_dir, workflow_id)
        now = utc_now().isoformat()
        creative_direction = {
            **(existing.creative_direction if existing is not None else {}),
            **_dict_payload(action.payload.get("creative_direction")),
        }
        source = {
            **(existing.source if existing is not None else {}),
            **_dict_payload(action.payload.get("source")),
            "conversation_id": action.conversation_id,
            "action_id": action.action_id,
        }
        existing_node_briefs = (
            existing.node_briefs.model_dump(mode="json") if existing is not None else {}
        )
        node_briefs = {
            **existing_node_briefs,
            **_dict_payload(action.payload.get("node_briefs")),
        }
        node_briefs_model = (
            existing.node_briefs.model_copy(update=node_briefs)
            if existing is not None
            else node_briefs
        )
        context = (
            existing.model_copy(
                update={
                    "version": existing.version + 1,
                    "updated_at": now,
                    "creative_direction": creative_direction,
                    "node_briefs": node_briefs_model,
                    "source": source,
                }
            )
            if existing is not None
            else DirectorContext(
                workflow_id=workflow_id,
                created_at=now,
                updated_at=now,
                creative_direction=creative_direction,
                node_briefs=node_briefs_model,
                source=source,
            )
        )
        save_director_context(self._settings.media_data_dir, context)
        return {"director_context": context.model_dump(mode="json")}
