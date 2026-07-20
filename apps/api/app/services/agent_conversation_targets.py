from __future__ import annotations

import re
from typing import Any

from app.schemas.agent_conversations import (
    HIDDEN_AGENT_ALIASES,
    VISIBLE_AGENTS,
    AgentConversation,
    AgentConversationMessageRequest,
    NodeReference,
    SuggestedAction,
)
from app.schemas.workflow_graph import (
    WorkflowGraph,
)
from app.services.workflow_graph import WorkflowGraphError

from app.services.agent_conversation_common import (
    AgentConversationInputError,
    PROMPT_UPDATE_KEYWORDS,
    _NodeMentionError,
    _ResolvedNodeMention,
    _message_mentions_node_id,
    _node_is_user_targetable,
    _optional_str,
    _string_list,
)


class AgentConversationTargetsMixin:
    def _resolve_node_prompt_update_target(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
    ) -> _ResolvedNodeMention | _NodeMentionError | None:
        graph = self._node_prompt_update_graph(conversation)
        if isinstance(graph, _NodeMentionError):
            return graph

        explicit = self._resolve_explicit_node_prompt_target(graph, request)
        if explicit is not None:
            return explicit
        contextual = self._resolve_context_node_prompt_target(graph, conversation, request)
        if contextual is not None:
            return contextual
        return self._infer_node_prompt_target(graph, request.message)

    def _node_prompt_update_graph(
        self, conversation: AgentConversation
    ) -> WorkflowGraph | _NodeMentionError:
        workflow_id = conversation.workflow_id
        if not workflow_id:
            return _NodeMentionError(
                error_code="workflow_graph_not_found",
                message="A workflow_id is required before updating a node prompt.",
            )
        try:
            return self._graph_service.get_graph(workflow_id)
        except WorkflowGraphError:
            return _NodeMentionError(
                error_code="workflow_graph_not_found",
                message=f"Workflow graph not found: {workflow_id}.",
            )

    def _resolve_explicit_node_prompt_target(
        self,
        graph: WorkflowGraph,
        request: AgentConversationMessageRequest,
    ) -> _ResolvedNodeMention | _NodeMentionError | None:
        if request.node_references:
            if len(request.node_references) != 1:
                return _NodeMentionError(
                    error_code="node_reference_ambiguous",
                    message="Mention exactly one workflow node before updating its prompt.",
                    metadata={
                        "matching_node_ids": [
                            reference.node_id for reference in request.node_references
                        ]
                    },
                )
            return self._validate_node_reference(graph, request.node_references[0])
        return None

    def _resolve_context_node_prompt_target(
        self,
        graph: WorkflowGraph,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
    ) -> _ResolvedNodeMention | _NodeMentionError | None:
        mentioned_node_ids = _string_list(request.context.get("mentioned_node_ids"))
        if mentioned_node_ids:
            if len(mentioned_node_ids) != 1:
                return _NodeMentionError(
                    error_code="node_reference_ambiguous",
                    message="Mention exactly one workflow node before updating its prompt.",
                    metadata={"matching_node_ids": mentioned_node_ids},
                )
            return self._validate_node_reference(
                graph,
                NodeReference(
                    node_id=mentioned_node_ids[0],
                    source="mention",
                ),
            )

        selected_node_id = _optional_str(request.context.get("selected_node_id"))
        if selected_node_id:
            return self._validate_node_reference(
                graph,
                NodeReference(node_id=selected_node_id, source="selected_node"),
            )

        if conversation.focus_node_id:
            return self._validate_node_reference(
                graph,
                NodeReference(node_id=conversation.focus_node_id, source="selected_node"),
            )
        return None

    def _infer_node_prompt_target(
        self,
        graph: WorkflowGraph,
        message: str,
    ) -> _ResolvedNodeMention | _NodeMentionError | None:
        inferred = [
            node
            for node in graph.nodes
            if _node_is_user_targetable(node) and _message_mentions_node_id(message, node.id)
        ]
        if not inferred:
            return None
        if len(inferred) != 1:
            return _NodeMentionError(
                error_code="node_reference_ambiguous",
                message="The message mentions multiple workflow nodes.",
                metadata={"matching_node_ids": [node.id for node in inferred]},
            )
        node = inferred[0]
        return _ResolvedNodeMention(
            node=node,
            source="inferred",
            mention_text=f"@{node.id}",
        )

    def _validate_node_reference(
        self,
        graph: WorkflowGraph,
        reference: NodeReference,
    ) -> _ResolvedNodeMention | _NodeMentionError:
        node = next((item for item in graph.nodes if item.id == reference.node_id), None)
        if node is None:
            return _NodeMentionError(
                error_code="node_reference_not_found",
                message=f"Workflow node not found: {reference.node_id}.",
                target_node_id=reference.node_id,
                metadata={"node_reference": reference.model_dump(mode="json")},
            )
        if reference.node_type and reference.node_type != node.node_type:
            return _NodeMentionError(
                error_code="node_type_mismatch",
                message=(
                    f"Workflow node {node.id} uses node_type {node.node_type}, "
                    f"not {reference.node_type}."
                ),
                target_node_id=node.id,
                metadata={
                    "node_reference": reference.model_dump(mode="json"),
                    "actual_node_type": node.node_type,
                },
            )
        if not _node_is_user_targetable(node):
            return _NodeMentionError(
                error_code="node_reference_hidden",
                message=f"Workflow node is not user-targetable: {node.id}.",
                target_node_id=node.id,
                metadata={"node_reference": reference.model_dump(mode="json")},
            )
        return _ResolvedNodeMention(
            node=node,
            source=reference.source,
            mention_text=reference.mention_text,
        )

    def _validate_mentions(self, mentions: list[str]) -> None:
        for mention in mentions:
            if mention in HIDDEN_AGENT_ALIASES:
                raise AgentConversationInputError(f"{mention} is hidden and cannot be mentioned.")
            if mention not in VISIBLE_AGENTS:
                raise AgentConversationInputError(f"unknown visible agent: {mention}")

    def _infer_agent_from_message(self, message: str) -> str | None:
        lowered = message.lower()
        if any(keyword in lowered for keyword in ("character", "hero", "role")):
            return "character_designer"
        if "角色" in message or "人物" in message:
            return "character_designer"
        if "scene" in lowered or "场景" in message:
            return "scene_designer"
        if "storyboard" in lowered or "分镜" in message:
            return "storyboard_artist"
        if "video" in lowered or "视频" in message:
            return "video_director"
        if "music" in lowered or "audio" in lowered or "音乐" in message:
            return "sound_director"
        if "final" in lowered or "composition" in lowered or "成片" in message:
            return "final_composition_assistant"
        if "script" in lowered or "copy" in lowered or "脚本" in message:
            return "script_writer"
        return None

    def _message_requests_node_action(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            keyword in lowered
            for keyword in (
                "apply",
                "change",
                "generate",
                "optimize",
                "regenerate",
                "revise",
                "run",
                "update",
            )
        ) or any(keyword in message for keyword in ("修改", "生成", "优化", "运行", "重跑"))

    def _message_requests_prompt_update(self, message: str) -> bool:
        lowered = message.lower()
        if "optimize" in lowered or "优化" in message:
            return False
        return any(keyword in lowered for keyword in PROMPT_UPDATE_KEYWORDS) or any(
            keyword in message for keyword in PROMPT_UPDATE_KEYWORDS
        )

    def _has_node_prompt_target_hint(
        self,
        conversation: AgentConversation,
        request: AgentConversationMessageRequest,
    ) -> bool:
        return bool(
            request.target_references
            or request.node_references
            or _string_list(request.context.get("mentioned_node_ids"))
            or _optional_str(request.context.get("selected_node_id"))
            or conversation.focus_node_id
            or re.search(r"(?<!\w)@[\w-]+", request.message)
        )

    def _asset_reference_payloads(self, asset_references: list[Any]) -> list[dict[str, Any]]:
        return [
            reference.model_dump(mode="json")
            if hasattr(reference, "model_dump")
            else dict(reference)
            for reference in asset_references
        ]

    def _require_action(self, conversation: AgentConversation, action_id: str) -> SuggestedAction:
        for action in conversation.suggested_actions:
            if action.action_id == action_id:
                return action
        raise AgentConversationInputError(f"unknown action_id: {action_id}")

    def _require_workflow_id(self, action: SuggestedAction) -> str:
        if not action.workflow_id:
            raise AgentConversationInputError(f"{action.action_type} action requires workflow_id.")
        return action.workflow_id

    def _require_target_node_id(self, action: SuggestedAction) -> str:
        if not action.target_node_id:
            raise AgentConversationInputError(
                f"{action.action_type} action requires target_node_id."
            )
        return action.target_node_id
