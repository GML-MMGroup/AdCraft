from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.core.config import Settings, get_settings
from app.schemas.canvas_targets import CanvasTargetReference, NormalizedCanvasTarget
from app.schemas.agent_conversations import NodeReference
from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
    WorkflowGraphNodePatchRequest,
)
from app.schemas.workflow_nodes import WorkflowRunRequest
from app.schemas.workflow_item_prompts import WorkflowItemPromptUpdateRequest
from app.schemas.workflow_revisions import WorkflowRevisionRequest, WorkflowRevisionState
from app.services.canvas_targets import (
    CanvasTargetResolutionError,
    CanvasTargetResolverService,
)
from app.services.workflow_executions import (
    ACTIVE_BLOCKING_EXECUTION_STATUSES,
    WorkflowExecutionAlreadyRunningError,
    WorkflowExecutionService,
)
from app.services.workflow_graph import WorkflowGraphError, WorkflowGraphService
from app.services.workflow_item_prompt_utils import (
    item_prompt_from_payload,
    item_semantic_type_for_revision,
)
from app.services.workflow_item_prompts import (
    WorkflowItemPromptError,
    WorkflowItemPromptService,
)
from app.services.workflow_local_revisions import (
    WorkflowLocalRevisionError,
    WorkflowLocalRevisionService,
)
from app.services.workflow_run import WorkflowCanvasExecutionService


ChatCanvasActionType = Literal[
    "update_prompt_only",
    "update_prompt_and_run_node",
    "run_node_only",
    "update_prompt_and_run_downstream",
    "update_item_prompt_only",
    "update_item_prompt_and_run",
    "run_item_only",
]

ScheduleExecution = Callable[[str, str], None]

USER_TARGETABLE_NODE_TYPES = {
    "script",
    "character-generation",
    "scene-generation",
    "storyboard",
    "storyboard-video-generation",
    "bgm",
    "final-composition",
}
PROMPT_UPDATE_KEYWORDS = (
    "adjust",
    "change",
    "cleaner",
    "direction",
    "prompt",
    "revise",
    "style",
    "update",
    "修改",
    "改",
    "调整",
    "提示词",
    "风格",
    "更",
    "少",
    "多",
    "突出",
    "保留",
    "简洁",
    "太乱",
    "低角度",
    "夜晚",
)
RUN_KEYWORDS = (
    "generate",
    "regenerate",
    "rerun",
    "remake",
    "run",
    "produce",
    "another version",
    "new version",
    "生成",
    "重新生成",
    "重跑",
    "再跑",
    "运行",
    "跑一下",
    "再来一版",
    "再来一张",
    "再出一版",
    "换一版",
    "另一版",
)
RUN_NEGATION_KEYWORDS = (
    "do not generate",
    "don't generate",
    "do not run",
    "don't run",
    "without generating",
    "no generation",
    "不要生成",
    "先不要生成",
    "不生成",
    "不要运行",
    "不要跑",
    "先不要跑",
)
DOWNSTREAM_KEYWORDS = (
    "from here",
    "from this node",
    "from this node onward",
    "from here onward",
    "downstream",
    "后续",
    "从这里",
    "从此节点",
    "从这个节点",
    "往后",
)
OPTIMIZE_ONLY_KEYWORDS = (
    "optimize",
    "优化",
)


@dataclass(frozen=True)
class ChatCanvasAction:
    action_type: ChatCanvasActionType

    @property
    def updates_prompt(self) -> bool:
        return self.action_type in {
            "update_prompt_only",
            "update_prompt_and_run_node",
            "update_prompt_and_run_downstream",
            "update_item_prompt_only",
            "update_item_prompt_and_run",
        }

    @property
    def starts_execution(self) -> bool:
        return self.action_type in {
            "update_prompt_and_run_node",
            "run_node_only",
            "update_prompt_and_run_downstream",
        }

    @property
    def updates_item_prompt(self) -> bool:
        return self.action_type in {
            "update_item_prompt_only",
            "update_item_prompt_and_run",
        }

    @property
    def starts_revision(self) -> bool:
        return self.action_type in {"update_item_prompt_and_run", "run_item_only"}

    @property
    def run_mode(self) -> str | None:
        if self.action_type in {"update_prompt_and_run_node", "run_node_only"}:
            return "single_node"
        if self.action_type == "update_prompt_and_run_downstream":
            return "run_from_frontier"
        return None


@dataclass(frozen=True)
class ResolvedChatCanvasAction:
    workflow_id: str
    node: WorkflowGraphNode
    action: ChatCanvasAction
    source: str
    mention_text: str | None = None
    target: NormalizedCanvasTarget | None = None


@dataclass(frozen=True)
class PromptUpdateResult:
    workflow_version: int
    stale_node_ids: list[str]
    revised_prompt: str


@dataclass(frozen=True)
class ExecutionStartResult:
    execution_id: str
    run_mode: str
    frontier_node_id: str | None


@dataclass(frozen=True)
class ItemPromptUpdateResult:
    prompt: str
    status: str
    stale_item_ids: list[str]
    target: dict[str, Any]


@dataclass(frozen=True)
class RevisionStartResult:
    revision_id: str
    status: str
    generation_status: str | None
    acceptance_status: str
    target: dict[str, Any]


@dataclass(frozen=True)
class ChatCanvasActionError:
    error_code: str
    message: str
    target_node_id: str | None = None
    target: NormalizedCanvasTarget | None = None
    metadata: dict[str, Any] | None = None

    def metadata_payload(self) -> dict[str, Any]:
        payload = dict(self.metadata or {})
        if self.target is not None:
            payload["target"] = self.target.model_dump(mode="json")
        return payload


@dataclass(frozen=True)
class ChatCanvasActionResult:
    resolved: ResolvedChatCanvasAction | None = None
    prompt_update: PromptUpdateResult | None = None
    item_prompt_update: ItemPromptUpdateResult | None = None
    execution: ExecutionStartResult | None = None
    revision: RevisionStartResult | None = None
    error: ChatCanvasActionError | None = None


class ChatCanvasActionProtocolService:
    def __init__(
        self,
        settings: Settings,
        *,
        workflow_graph_service: WorkflowGraphService | None = None,
        workflow_execution_service: WorkflowCanvasExecutionService | None = None,
        execution_state_service: WorkflowExecutionService | None = None,
        target_resolver: CanvasTargetResolverService | None = None,
        item_prompt_service: WorkflowItemPromptService | None = None,
        local_revision_service: WorkflowLocalRevisionService | None = None,
    ) -> None:
        self._settings = settings
        self._graph_service = workflow_graph_service or WorkflowGraphService(
            data_dir=settings.media_data_dir
        )
        self._workflow_execution = workflow_execution_service or WorkflowCanvasExecutionService(
            settings
        )
        self._execution_state = execution_state_service or WorkflowExecutionService(
            settings.media_data_dir
        )
        self._target_resolver = target_resolver or CanvasTargetResolverService(
            settings,
            workflow_graph_service=self._graph_service,
        )
        self._item_prompts = item_prompt_service or WorkflowItemPromptService(settings)
        self._local_revisions = local_revision_service or WorkflowLocalRevisionService(settings)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ChatCanvasActionProtocolService":
        return cls(settings or get_settings())

    def resolve_and_classify(
        self,
        *,
        workflow_id: str,
        message: str,
        target_references: list[CanvasTargetReference | dict[str, Any]] | None = None,
        node_references: list[NodeReference | dict[str, Any]],
        context: dict[str, Any],
        focus_node_id: str | None,
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError | None:
        action = self.classify_message(message)
        if action is None:
            return None
        graph = self._load_graph_or_error(workflow_id)
        if isinstance(graph, ChatCanvasActionError):
            return graph

        explicit = self._resolve_explicit_chat_canvas_target(
            workflow_id=workflow_id,
            graph=graph,
            action=action,
            target_references=target_references,
            node_references=node_references,
        )
        if explicit is not None or target_references:
            return explicit

        referenced = self._resolve_referenced_chat_canvas_node(
            workflow_id=workflow_id,
            graph=graph,
            action=action,
            node_references=node_references,
        )
        if referenced is not None:
            return referenced

        contextual = self._resolve_context_chat_canvas_node(
            workflow_id=workflow_id,
            graph=graph,
            action=action,
            context=context,
            focus_node_id=focus_node_id,
        )
        if contextual is not None:
            return contextual

        return self._resolve_inferred_chat_canvas_node(
            workflow_id=workflow_id,
            graph=graph,
            action=action,
            message=message,
        )

    def _resolve_explicit_chat_canvas_target(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        action: ChatCanvasAction,
        target_references: list[CanvasTargetReference | dict[str, Any]] | None,
        node_references: list[NodeReference | dict[str, Any]],
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError | None:
        if not target_references:
            return None
        target = self._target_resolver.resolve_explicit_target(
            workflow_id=workflow_id,
            target_references=target_references,
            node_references=node_references,
        )
        if isinstance(target, CanvasTargetResolutionError):
            return _target_error(target)
        if target is None:
            return None
        return self._resolve_normalized_target(
            workflow_id=workflow_id,
            graph=graph,
            target=target,
            action=action,
        )

    def _resolve_referenced_chat_canvas_node(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        action: ChatCanvasAction,
        node_references: list[NodeReference | dict[str, Any]],
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError | None:
        references = [_node_reference(reference) for reference in node_references]
        if references:
            if len(references) != 1:
                return ChatCanvasActionError(
                    error_code="node_reference_ambiguous",
                    message="Mention exactly one workflow node before updating or running it.",
                    metadata={"matching_node_ids": [reference.node_id for reference in references]},
                )
            return self._validate_node_reference(
                workflow_id=workflow_id,
                graph=graph,
                reference=references[0],
                action=action,
            )
        return None

    def _resolve_context_chat_canvas_node(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        action: ChatCanvasAction,
        context: dict[str, Any],
        focus_node_id: str | None,
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError | None:
        mentioned_node_ids = _string_list(context.get("mentioned_node_ids"))
        if mentioned_node_ids:
            if len(mentioned_node_ids) != 1:
                return ChatCanvasActionError(
                    error_code="node_reference_ambiguous",
                    message="Mention exactly one workflow node before updating or running it.",
                    metadata={"matching_node_ids": mentioned_node_ids},
                )
            return self._validate_node_reference(
                workflow_id=workflow_id,
                graph=graph,
                reference=NodeReference(node_id=mentioned_node_ids[0], source="mention"),
                action=action,
            )

        selected_node_id = _optional_str(context.get("selected_node_id"))
        if selected_node_id:
            return self._validate_node_reference(
                workflow_id=workflow_id,
                graph=graph,
                reference=NodeReference(node_id=selected_node_id, source="selected_node"),
                action=action,
            )

        if focus_node_id:
            return self._validate_node_reference(
                workflow_id=workflow_id,
                graph=graph,
                reference=NodeReference(node_id=focus_node_id, source="selected_node"),
                action=action,
            )
        return None

    def _resolve_inferred_chat_canvas_node(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        action: ChatCanvasAction,
        message: str,
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError | None:
        inferred = [
            node
            for node in graph.nodes
            if _node_is_user_targetable(node) and _message_mentions_node_id(message, node.id)
        ]
        if not inferred:
            return None
        if len(inferred) != 1:
            return ChatCanvasActionError(
                error_code="node_reference_ambiguous",
                message="The message mentions multiple workflow nodes.",
                metadata={"matching_node_ids": [node.id for node in inferred]},
            )
        node = inferred[0]
        return ResolvedChatCanvasAction(
            workflow_id=workflow_id,
            node=node,
            action=action,
            source="inferred",
            mention_text=f"@{node.id}",
            target=self._target_resolver.normalized_node_target(
                workflow_id=workflow_id,
                node=node,
                source="inferred",
                mention_text=f"@{node.id}",
            ),
        )

    def classify_message(self, message: str) -> ChatCanvasAction | None:
        lowered = message.lower()
        if any(keyword in lowered for keyword in OPTIMIZE_ONLY_KEYWORDS) or any(
            keyword in message for keyword in OPTIMIZE_ONLY_KEYWORDS
        ):
            return None
        prompt_intent = any(keyword in lowered for keyword in PROMPT_UPDATE_KEYWORDS) or any(
            keyword in message for keyword in PROMPT_UPDATE_KEYWORDS
        )
        run_intent = not _has_run_negation(message) and (
            any(keyword in lowered for keyword in RUN_KEYWORDS)
            or any(keyword in message for keyword in RUN_KEYWORDS)
        )
        downstream_intent = any(keyword in lowered for keyword in DOWNSTREAM_KEYWORDS) or any(
            keyword in message for keyword in DOWNSTREAM_KEYWORDS
        )
        if prompt_intent and run_intent and downstream_intent:
            return ChatCanvasAction("update_prompt_and_run_downstream")
        if prompt_intent and run_intent:
            return ChatCanvasAction("update_prompt_and_run_node")
        if run_intent:
            return ChatCanvasAction("run_node_only")
        if prompt_intent:
            return ChatCanvasAction("update_prompt_only")
        return None

    def execute(
        self,
        resolved: ResolvedChatCanvasAction,
        *,
        message: str,
        schedule_execution: ScheduleExecution | None = None,
        prompt_override: str | None = None,
        revision_instruction_override: str | None = None,
    ) -> ChatCanvasActionResult:
        if resolved.action.updates_item_prompt or resolved.action.starts_revision:
            return self._execute_item_action(
                resolved,
                message=message,
                prompt_override=prompt_override,
                revision_instruction_override=revision_instruction_override,
            )

        active_error = self._active_execution_error(resolved)
        if active_error is not None:
            return ChatCanvasActionResult(resolved=resolved, error=active_error)

        prompt_update: PromptUpdateResult | None = None
        if resolved.action.updates_prompt:
            try:
                revised_prompt = prompt_override or self.revise_node_prompt(
                    node=resolved.node,
                    message=message,
                    mention_text=resolved.mention_text,
                )
            except Exception as exc:  # noqa: BLE001 - returned as structured chat event.
                return ChatCanvasActionResult(
                    resolved=resolved,
                    error=ChatCanvasActionError(
                        error_code="prompt_revision_failed",
                        message=str(exc),
                        target_node_id=resolved.node.id,
                        target=resolved.target,
                    ),
                )
            saved_graph = self.write_prompt_update(
                workflow_id=resolved.workflow_id,
                node=resolved.node,
                revised_prompt=revised_prompt,
            )
            prompt_update = PromptUpdateResult(
                workflow_version=saved_graph.version,
                stale_node_ids=_affected_node_ids(saved_graph, resolved.node.id),
                revised_prompt=revised_prompt,
            )

        if not resolved.action.starts_execution:
            return ChatCanvasActionResult(resolved=resolved, prompt_update=prompt_update)

        try:
            execution = self.start_execution(resolved, schedule_execution=schedule_execution)
        except WorkflowExecutionAlreadyRunningError:
            active = self._execution_state.load_active_execution(resolved.workflow_id)
            metadata = {"execution_id": active.execution_id} if active is not None else {}
            return ChatCanvasActionResult(
                resolved=resolved,
                prompt_update=prompt_update,
                error=ChatCanvasActionError(
                    error_code="execution_already_running",
                    message="Workflow execution is already running.",
                    target_node_id=resolved.node.id,
                    target=resolved.target,
                    metadata=metadata,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - returned as structured chat event.
            return ChatCanvasActionResult(
                resolved=resolved,
                prompt_update=prompt_update,
                error=ChatCanvasActionError(
                    error_code="execution_start_failed",
                    message=str(exc),
                    target_node_id=resolved.node.id,
                    target=resolved.target,
                ),
            )
        return ChatCanvasActionResult(
            resolved=resolved,
            prompt_update=prompt_update,
            execution=execution,
        )

    def _execute_item_action(
        self,
        resolved: ResolvedChatCanvasAction,
        *,
        message: str,
        prompt_override: str | None = None,
        revision_instruction_override: str | None = None,
    ) -> ChatCanvasActionResult:
        target = resolved.target
        if target is None or target.target_type != "item" or not target.item_id:
            return ChatCanvasActionResult(
                resolved=resolved,
                error=ChatCanvasActionError(
                    error_code="unsupported_target_action",
                    message="This item-level action requires a resolved item target.",
                    target_node_id=resolved.node.id,
                    target=target,
                ),
            )
        item_prompt_update: ItemPromptUpdateResult | None = None
        revision_instruction: str | None = None
        if resolved.action.updates_item_prompt:
            revised_prompt = prompt_override or self.revise_item_prompt(
                target=target,
                message=message,
            )
            try:
                update_response = self._item_prompts.update_item_prompt(
                    workflow_id=resolved.workflow_id,
                    node_id=resolved.node.id,
                    item_id=target.item_id,
                    request=WorkflowItemPromptUpdateRequest(
                        prompt=revised_prompt,
                        semantic_type=target.semantic_type,
                        mark_stale=True,
                    ),
                )
            except WorkflowItemPromptError as exc:
                message_text = str(exc.detail.get("message") or exc.detail.get("code") or exc)
                return ChatCanvasActionResult(
                    resolved=resolved,
                    error=ChatCanvasActionError(
                        error_code=str(exc.detail.get("code") or "item_prompt_update_failed"),
                        message=message_text,
                        target_node_id=resolved.node.id,
                        target=target,
                        metadata=exc.detail,
                    ),
                )
            item_prompt_update = ItemPromptUpdateResult(
                prompt=update_response.prompt,
                status=update_response.status,
                stale_item_ids=update_response.stale_item_ids,
                target=update_response.target,
            )
            revision_instruction = update_response.prompt

        if not resolved.action.starts_revision:
            return ChatCanvasActionResult(
                resolved=resolved,
                item_prompt_update=item_prompt_update,
            )

        if not revision_instruction:
            revision_instruction = revision_instruction_override
        if not revision_instruction:
            item = target.metadata.get("item") if isinstance(target.metadata, dict) else None
            revision_instruction = item_prompt_from_payload(item) if isinstance(item, dict) else ""
        if not revision_instruction:
            return ChatCanvasActionResult(
                resolved=resolved,
                item_prompt_update=item_prompt_update,
                error=ChatCanvasActionError(
                    error_code="item_prompt_missing",
                    message="Target item has no prompt to use for regeneration.",
                    target_node_id=resolved.node.id,
                    target=target,
                ),
            )
        semantic_type = item_semantic_type_for_revision(
            resolved.node.node_type,
            target.semantic_type,
        )
        try:
            state = self._local_revisions.create_revision(
                resolved.workflow_id,
                resolved.node.id,
                WorkflowRevisionRequest(
                    mode="regenerate_entity",
                    target_entity_id=target.item_id,
                    semantic_type=semantic_type,
                    instruction=revision_instruction,
                    preserve_other_outputs=True,
                    metadata={
                        "source_item_id": target.item_id,
                        "source_item_prompt": revision_instruction,
                    },
                ),
                source_metadata={
                    "source_type": "agent_conversation_item_action",
                    "source_item_id": target.item_id,
                    "source_item_prompt": revision_instruction,
                },
            )
        except WorkflowLocalRevisionError as exc:
            message_text = str(exc.detail.get("message") or exc.detail.get("code") or exc)
            return ChatCanvasActionResult(
                resolved=resolved,
                item_prompt_update=item_prompt_update,
                error=ChatCanvasActionError(
                    error_code="item_revision_start_failed",
                    message=message_text,
                    target_node_id=resolved.node.id,
                    target=target,
                    metadata=exc.detail,
                ),
            )
        return ChatCanvasActionResult(
            resolved=resolved,
            item_prompt_update=item_prompt_update,
            revision=_revision_start_result(state, target),
        )

    def revise_node_prompt(
        self,
        *,
        node: WorkflowGraphNode,
        message: str,
        mention_text: str | None,
    ) -> str:
        current_prompt = _first_text(
            node.prompt,
            node.override_prompt,
            node.input_context.get("user_prompt"),
            node.input_context.get("system_suggested_prompt"),
        )
        user_update = _clean_node_update_message(
            message,
            node_id=node.id,
            mention_text=mention_text,
        )
        if not user_update:
            raise ValueError("node prompt update message is empty.")
        if not current_prompt:
            return user_update
        if user_update in current_prompt:
            return current_prompt
        return f"{current_prompt}\n\n用户最新要求：{user_update}"

    def revise_item_prompt(
        self,
        *,
        target: NormalizedCanvasTarget,
        message: str,
    ) -> str:
        user_update = _clean_item_update_message(
            message,
            node_id=target.node_id or "",
            item_id=target.item_id or "",
        )
        if not user_update:
            raise ValueError("item prompt update message is empty.")
        return user_update

    def write_prompt_update(
        self,
        *,
        workflow_id: str,
        node: WorkflowGraphNode,
        revised_prompt: str,
    ) -> WorkflowGraph:
        input_context = {
            **node.input_context,
            "user_prompt": revised_prompt,
        }
        metadata = {
            **node.metadata,
            "prompt_source": "user",
            "manual_prompt_dirty": True,
            "has_new_system_suggestion": False,
        }
        return self._graph_service.patch_node(
            workflow_id,
            node.id,
            WorkflowGraphNodePatchRequest(
                prompt=revised_prompt,
                override_prompt=revised_prompt,
                input_context=input_context,
                metadata=metadata,
                status="stale",
                stale=True,
                stale_reason="prompt updated from chat canvas action",
            ),
        )

    def start_execution(
        self,
        resolved: ResolvedChatCanvasAction,
        *,
        schedule_execution: ScheduleExecution | None = None,
    ) -> ExecutionStartResult:
        run_mode = resolved.action.run_mode
        if run_mode == "single_node":
            request = WorkflowRunRequest(
                mode="single_node",
                target_node_id=resolved.node.id,
                start_node_id=resolved.node.id,
                run_downstream=False,
                force_rerun=True,
            )
        elif run_mode == "run_from_frontier":
            request = WorkflowRunRequest(
                mode="run_from_frontier",
                target_node_id=resolved.node.id,
                start_node_id=resolved.node.id,
                run_downstream=True,
                force_rerun=True,
            )
        else:
            raise ValueError(f"unsupported execution action: {resolved.action.action_type}")
        execution = self._workflow_execution.start_execution(resolved.workflow_id, request)
        if schedule_execution is not None:
            schedule_execution(resolved.workflow_id, execution.execution_id)
        return ExecutionStartResult(
            execution_id=execution.execution_id,
            run_mode=execution.mode,
            frontier_node_id=None
            if execution.mode == "single_node"
            else execution.frontier_node_id,
        )

    def run_execution(self, workflow_id: str, execution_id: str) -> None:
        self._workflow_execution.run_execution(workflow_id, execution_id)

    def _load_graph_or_error(self, workflow_id: str) -> WorkflowGraph | ChatCanvasActionError:
        try:
            return self._graph_service.get_graph(workflow_id)
        except WorkflowGraphError:
            return ChatCanvasActionError(
                error_code="workflow_graph_not_found",
                message=f"Workflow graph not found: {workflow_id}.",
            )

    def _validate_node_reference(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        reference: NodeReference,
        action: ChatCanvasAction,
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError:
        node = next((item for item in graph.nodes if item.id == reference.node_id), None)
        if node is None:
            return ChatCanvasActionError(
                error_code="node_reference_not_found",
                message=f"Workflow node not found: {reference.node_id}.",
                target_node_id=reference.node_id,
                metadata={"node_reference": reference.model_dump(mode="json")},
            )
        if reference.node_type and reference.node_type != node.node_type:
            return ChatCanvasActionError(
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
            return ChatCanvasActionError(
                error_code="node_reference_hidden",
                message=f"Workflow node is not user-targetable: {node.id}.",
                target_node_id=node.id,
                metadata={"node_reference": reference.model_dump(mode="json")},
            )
        if node.locked:
            return ChatCanvasActionError(
                error_code="node_locked",
                message=f"Workflow node is locked: {node.id}.",
                target_node_id=node.id,
                metadata={"node_reference": reference.model_dump(mode="json")},
            )
        return ResolvedChatCanvasAction(
            workflow_id=workflow_id,
            node=node,
            action=action,
            source=reference.source,
            mention_text=reference.mention_text,
            target=self._target_resolver.normalized_node_target(
                workflow_id=workflow_id,
                node=node,
                source=reference.source,
                mention_text=reference.mention_text,
                semantic_type=reference.node_type or "workflow_node",
            ),
        )

    def _resolve_normalized_target(
        self,
        *,
        workflow_id: str,
        graph: WorkflowGraph,
        target: NormalizedCanvasTarget,
        action: ChatCanvasAction,
    ) -> ResolvedChatCanvasAction | ChatCanvasActionError:
        if target.target_type == "item":
            if target.intent_scope == "downstream":
                return ChatCanvasActionError(
                    error_code="unsupported_target_scope",
                    message="Downstream item target actions are not available yet.",
                    target_node_id=target.node_id,
                    target=target,
                )
            if target.intent_scope != "single":
                return ChatCanvasActionError(
                    error_code="unsupported_target_scope",
                    message="Only single item target actions are available.",
                    target_node_id=target.node_id,
                    target=target,
                )
            item_action = _item_action_from_node_action(action)
            node = next((item for item in graph.nodes if item.id == target.node_id), None)
            if node is None:
                return ChatCanvasActionError(
                    error_code="target_node_not_found",
                    message=f"Workflow node not found: {target.node_id}.",
                    target_node_id=target.node_id,
                    target=target,
                )
            if node.locked:
                return ChatCanvasActionError(
                    error_code="node_locked",
                    message=f"Workflow node is locked: {node.id}.",
                    target_node_id=node.id,
                    target=target,
                )
            return ResolvedChatCanvasAction(
                workflow_id=workflow_id,
                node=node,
                action=item_action,
                source=target.source,
                mention_text=None,
                target=target,
            )
        if target.target_type != "node":
            return ChatCanvasActionError(
                error_code="unsupported_target_action",
                message="This asset-level action is not available yet.",
                target_node_id=target.node_id,
                target=target,
            )
        node = next((item for item in graph.nodes if item.id == target.node_id), None)
        if node is None:
            return ChatCanvasActionError(
                error_code="target_node_not_found",
                message=f"Workflow node not found: {target.node_id}.",
                target_node_id=target.node_id,
                target=target,
            )
        if node.locked:
            return ChatCanvasActionError(
                error_code="node_locked",
                message=f"Workflow node is locked: {node.id}.",
                target_node_id=node.id,
                target=target,
            )
        return ResolvedChatCanvasAction(
            workflow_id=workflow_id,
            node=node,
            action=action,
            source=target.source,
            mention_text=None,
            target=target,
        )

    def _active_execution_error(
        self,
        resolved: ResolvedChatCanvasAction,
    ) -> ChatCanvasActionError | None:
        if not resolved.action.starts_execution:
            return None
        active = self._execution_state.load_active_execution(resolved.workflow_id)
        if active is None or active.status not in ACTIVE_BLOCKING_EXECUTION_STATUSES:
            return None
        return ChatCanvasActionError(
            error_code="execution_already_running",
            message="Workflow execution is already running.",
            target_node_id=resolved.node.id,
            target=resolved.target,
            metadata={"execution_id": active.execution_id},
        )


def _node_reference(value: NodeReference | dict[str, Any]) -> NodeReference:
    if isinstance(value, NodeReference):
        return value
    return NodeReference.model_validate(value)


def _item_action_from_node_action(action: ChatCanvasAction) -> ChatCanvasAction:
    if action.action_type == "update_prompt_only":
        return ChatCanvasAction("update_item_prompt_only")
    if action.action_type == "update_prompt_and_run_node":
        return ChatCanvasAction("update_item_prompt_and_run")
    if action.action_type == "run_node_only":
        return ChatCanvasAction("run_item_only")
    return action


def _revision_start_result(
    state: WorkflowRevisionState,
    target: NormalizedCanvasTarget,
) -> RevisionStartResult:
    return RevisionStartResult(
        revision_id=state.revision_id,
        status=state.status,
        generation_status=state.generation_status,
        acceptance_status=state.acceptance_status,
        target={
            **target.model_dump(mode="json"),
            "semantic_type": target.semantic_type,
        },
    )


def _target_error(error: CanvasTargetResolutionError) -> ChatCanvasActionError:
    return ChatCanvasActionError(
        error_code=error.error_code,
        message=error.message,
        target_node_id=error.target_node_id,
        target=error.target,
        metadata=error.metadata,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            result.append(text)
    return result


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_str(value)
        if text:
            return text
    return None


def _node_is_user_targetable(node: WorkflowGraphNode) -> bool:
    return bool(node.can_run_standalone) and node.node_type in USER_TARGETABLE_NODE_TYPES


def _message_mentions_node_id(message: str, node_id: str) -> bool:
    return re.search(rf"(?<![\w-])@{re.escape(node_id)}(?![\w-])", message) is not None


def _clean_node_update_message(
    message: str,
    *,
    node_id: str,
    mention_text: str | None,
) -> str:
    cleaned = message.strip()
    for token in (mention_text, f"@{node_id}"):
        if token:
            cleaned = cleaned.replace(token, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_item_update_message(
    message: str,
    *,
    node_id: str,
    item_id: str,
) -> str:
    cleaned = message.strip()
    for token in (f"@{node_id}/{item_id}", f"@{node_id}", item_id):
        if token:
            cleaned = cleaned.replace(token, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _affected_node_ids(graph: WorkflowGraph, node_id: str) -> list[str]:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    ordered = [node_id]
    seen = {node_id}
    queue = list(outgoing.get(node_id, []))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        queue.extend(outgoing.get(current, []))
    return ordered


def _has_run_negation(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in RUN_NEGATION_KEYWORDS) or any(
        keyword in message for keyword in RUN_NEGATION_KEYWORDS
    )
