from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.schemas.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationMessageRequest,
    ConversationMemory,
)
from app.schemas.canvas_targets import CanvasTargetReference, NormalizedCanvasTarget
from app.services.agent_trace import utc_now
from app.services.canvas_targets import (
    CanvasTargetResolutionError,
    CanvasTargetResolverService,
)
from app.services.workflow_graph import WorkflowGraphService

RECENT_TARGET_LIMIT = 10
RECENT_ACTION_LIMIT = 20
OPEN_REVISION_LIMIT = 20
ACTIVE_EXECUTION_LIMIT = 10

TERMINAL_REVISION_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_EXECUTION_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}

MEMORY_REFERENCE_TERMS = (
    " it ",
    " this ",
    " that ",
    "that one",
    "again",
    "another version",
    "new version",
    "刚才那个",
    "刚才的",
    "这个",
    "这一个",
    "它",
    "再来一版",
    "再来一张",
    "再出一版",
    "换一版",
    "另一版",
)
MEMORY_FOCUS_ONLY_TERMS = (
    "记住这个目标",
    "记住它",
    "remember this target",
    "remember it",
)


@dataclass(frozen=True)
class ConversationMemoryRepair:
    warning_code: str
    message: str
    target: dict[str, Any] | None


@dataclass
class _MemoryEventState:
    recent_targets: list[dict[str, Any]]
    recent_actions: list[dict[str, Any]]
    open_revisions: list[dict[str, Any]]
    active_executions: list[dict[str, Any]]
    focus_target: dict[str, Any] | None
    last_director_decision: dict[str, Any] | None
    last_specialist_result_summary: dict[str, Any] | None


def new_conversation_memory(
    *,
    workflow_id: str | None,
    conversation_id: str,
) -> ConversationMemory:
    return ConversationMemory(
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        updated_at=utc_now().isoformat(),
    )


def trim_conversation_memory(memory: ConversationMemory) -> ConversationMemory:
    return memory.model_copy(
        update={
            "recent_targets": _tail(memory.recent_targets, RECENT_TARGET_LIMIT),
            "recent_actions": _tail(memory.recent_actions, RECENT_ACTION_LIMIT),
            "open_revisions": _tail(memory.open_revisions, OPEN_REVISION_LIMIT),
            "active_executions": _tail(
                memory.active_executions,
                ACTIVE_EXECUTION_LIMIT,
            ),
        }
    )


def reconcile_memory_active_work(
    memory: ConversationMemory,
    *,
    revision_statuses: dict[str, str],
    execution_statuses: dict[str, str],
) -> ConversationMemory:
    open_revisions = [
        item
        for item in memory.open_revisions
        if str(
            revision_statuses.get(str(item.get("revision_id") or "")) or item.get("status") or ""
        )
        not in TERMINAL_REVISION_STATUSES
    ]
    active_executions = [
        item
        for item in memory.active_executions
        if str(
            execution_statuses.get(str(item.get("execution_id") or "")) or item.get("status") or ""
        )
        not in TERMINAL_EXECUTION_STATUSES
    ]
    return trim_conversation_memory(
        memory.model_copy(
            update={
                "open_revisions": open_revisions,
                "active_executions": active_executions,
                "updated_at": utc_now().isoformat(),
            }
        )
    )


class ConversationMemoryService:
    def __init__(
        self,
        settings: Settings,
        *,
        workflow_graph_service: WorkflowGraphService | None = None,
        target_resolver: CanvasTargetResolverService | None = None,
    ) -> None:
        self._settings = settings
        self._graph_service = workflow_graph_service or WorkflowGraphService(
            data_dir=settings.media_data_dir
        )
        self._target_resolver = target_resolver or CanvasTargetResolverService(
            settings,
            workflow_graph_service=self._graph_service,
        )

    def ensure_memory(self, conversation: AgentConversation) -> ConversationMemory:
        if conversation.memory is None:
            conversation.memory = new_conversation_memory(
                workflow_id=conversation.workflow_id,
                conversation_id=conversation.conversation_id,
            )
        elif (
            conversation.memory.workflow_id != conversation.workflow_id
            or conversation.memory.conversation_id != conversation.conversation_id
        ):
            conversation.memory = conversation.memory.model_copy(
                update={
                    "workflow_id": conversation.workflow_id,
                    "conversation_id": conversation.conversation_id,
                    "updated_at": utc_now().isoformat(),
                }
            )
        return conversation.memory

    def repair_focus_target(
        self,
        conversation: AgentConversation,
    ) -> ConversationMemoryRepair | None:
        memory = self.ensure_memory(conversation)
        focus = memory.focus_target
        if not focus or not conversation.workflow_id:
            return None
        reference = target_reference_from_payload(focus, source="memory_focus")
        if reference is None:
            conversation.memory = memory.model_copy(
                update={"focus_target": None, "updated_at": utc_now().isoformat()}
            )
            return ConversationMemoryRepair(
                warning_code="memory_focus_target_not_found",
                message="Stored memory focus target is malformed.",
                target=focus,
            )
        resolved = self._target_resolver.resolve_target(
            workflow_id=conversation.workflow_id,
            reference=reference,
        )
        if isinstance(resolved, CanvasTargetResolutionError):
            conversation.memory = memory.model_copy(
                update={"focus_target": None, "updated_at": utc_now().isoformat()}
            )
            return ConversationMemoryRepair(
                warning_code="memory_focus_target_not_found",
                message=resolved.message,
                target=focus,
            )
        conversation.memory = memory.model_copy(
            update={
                "focus_target": compact_target(resolved),
                "updated_at": utc_now().isoformat(),
            }
        )
        return None

    def reconcile_active_work(self, conversation: AgentConversation) -> None:
        memory = self.ensure_memory(conversation)
        workflow_id = conversation.workflow_id
        if not workflow_id:
            return
        revision_statuses = self._open_revision_statuses(workflow_id, memory.open_revisions)
        execution_statuses = self._active_execution_statuses(workflow_id, memory.active_executions)
        if revision_statuses or execution_statuses:
            conversation.memory = reconcile_memory_active_work(
                memory,
                revision_statuses=revision_statuses,
                execution_statuses=execution_statuses,
            )

    def _open_revision_statuses(
        self, workflow_id: str, open_revisions: list[dict[str, Any]]
    ) -> dict[str, str]:
        if not open_revisions:
            return {}
        from app.services.workflow_local_revisions import (  # noqa: PLC0415
            WorkflowLocalRevisionError,
            WorkflowLocalRevisionService,
        )

        revisions = WorkflowLocalRevisionService(self._settings)
        revision_statuses: dict[str, str] = {}
        for item in open_revisions:
            revision_id = _optional_str(item.get("revision_id"))
            node_id = _memory_work_node_id(item)
            if not revision_id or not node_id:
                continue
            try:
                state = revisions.get_revision(workflow_id, node_id, revision_id)
            except WorkflowLocalRevisionError:
                continue
            revision_statuses[revision_id] = state.status
        return revision_statuses

    def _active_execution_statuses(
        self, workflow_id: str, active_executions: list[dict[str, Any]]
    ) -> dict[str, str]:
        if not active_executions:
            return {}
        from app.services.workflow_executions import (  # noqa: PLC0415
            WorkflowExecutionNotFoundError,
            WorkflowExecutionService,
        )

        executions = WorkflowExecutionService(self._settings.media_data_dir)
        execution_statuses: dict[str, str] = {}
        for item in active_executions:
            execution_id = _optional_str(item.get("execution_id"))
            if not execution_id:
                continue
            try:
                state = executions.load_execution(workflow_id, execution_id)
            except WorkflowExecutionNotFoundError:
                continue
            execution_statuses[execution_id] = state.status
        return execution_statuses

    def memory_summary(self, conversation: AgentConversation) -> dict[str, Any]:
        memory = trim_conversation_memory(self.ensure_memory(conversation))
        return {
            "workflow_id": memory.workflow_id,
            "conversation_id": memory.conversation_id,
            "focus_target": memory.focus_target,
            "recent_targets": _tail(memory.recent_targets, 5),
            "recent_actions": _tail(memory.recent_actions, 8),
            "recent_user_preferences": memory.recent_user_preferences,
            "last_director_decision": memory.last_director_decision,
            "last_specialist_result_summary": memory.last_specialist_result_summary,
            "open_revisions": _tail(memory.open_revisions, 5),
            "active_executions": _tail(memory.active_executions, 5),
            "updated_at": memory.updated_at,
        }

    def memory_summary_for_request(
        self,
        conversation: AgentConversation,
        *,
        user_message: str,
        target: NormalizedCanvasTarget | None = None,
    ) -> dict[str, Any]:
        summary = self.memory_summary(conversation)
        if target is not None:
            summary["focus_target"] = compact_target(target)
        summary["recent_user_preferences"] = _merge_preferences(
            summary.get("recent_user_preferences") or {},
            user_message,
        )
        return summary

    def focus_reference(
        self,
        conversation: AgentConversation,
    ) -> CanvasTargetReference | None:
        memory = self.ensure_memory(conversation)
        if not memory.focus_target:
            return None
        return target_reference_from_payload(memory.focus_target, source="memory_focus")

    def selected_reference(
        self,
        context: dict[str, Any],
    ) -> CanvasTargetReference | None:
        selected_node_id = _optional_str(context.get("selected_node_id"))
        selected_item_id = _optional_str(context.get("selected_item_id"))
        selected_asset_id = _optional_str(context.get("selected_asset_id"))
        if selected_item_id and selected_node_id:
            return CanvasTargetReference(
                target_type="item",
                node_id=selected_node_id,
                item_id=selected_item_id,
                semantic_type=_optional_str(context.get("selected_item_semantic_type")),
                intent_scope="single",
                source="selected_item",
            )
        if selected_asset_id:
            return CanvasTargetReference(
                target_type="asset",
                asset_id=selected_asset_id,
                node_id=selected_node_id,
                semantic_type=_optional_str(context.get("selected_asset_semantic_type")),
                intent_scope="single",
                source="selected_asset",
            )
        if selected_node_id:
            return CanvasTargetReference(
                target_type="node",
                node_id=selected_node_id,
                semantic_type="workflow_node",
                intent_scope="single",
                source="selected_node",
            )
        return None

    def with_memory_target(
        self,
        request: AgentConversationMessageRequest,
        reference: CanvasTargetReference,
    ) -> AgentConversationMessageRequest:
        context = {
            **request.context,
            "memory_focus_target": reference.model_dump(mode="json"),
        }
        return request.model_copy(update={"target_references": [reference], "context": context})

    def update_from_events(
        self,
        conversation: AgentConversation,
        events: list[AgentConversationEvent],
        *,
        user_message: str | None = None,
    ) -> None:
        if not events and not user_message:
            return
        memory = self.ensure_memory(conversation)
        state = _memory_event_state(memory)
        for event in events:
            _apply_memory_event(state, event)

        preferences = _merge_preferences(
            memory.recent_user_preferences,
            user_message or "",
        )
        conversation.memory = trim_conversation_memory(
            memory.model_copy(
                update={
                    "focus_target": state.focus_target,
                    "recent_targets": state.recent_targets,
                    "recent_actions": state.recent_actions,
                    "recent_user_preferences": preferences,
                    "last_director_decision": state.last_director_decision,
                    "last_specialist_result_summary": state.last_specialist_result_summary,
                    "open_revisions": state.open_revisions,
                    "active_executions": state.active_executions,
                    "updated_at": utc_now().isoformat(),
                }
            )
        )


def _memory_event_state(memory: ConversationMemory) -> _MemoryEventState:
    return _MemoryEventState(
        recent_targets=list(memory.recent_targets),
        recent_actions=list(memory.recent_actions),
        open_revisions=list(memory.open_revisions),
        active_executions=list(memory.active_executions),
        focus_target=memory.focus_target,
        last_director_decision=memory.last_director_decision,
        last_specialist_result_summary=memory.last_specialist_result_summary,
    )


def _apply_memory_event(state: _MemoryEventState, event: AgentConversationEvent) -> None:
    metadata = event.metadata
    target = _event_target(event)
    _apply_director_decision(state, metadata)
    _apply_event_focus_target(state, target)
    _apply_specialist_result(state, event, target)
    _apply_revision_memory_event(state, event, target)
    _apply_execution_memory_event(state, event, target)
    _apply_recent_memory_action(state, event, target)


def _apply_director_decision(state: _MemoryEventState, metadata: dict[str, Any]) -> None:
    decision = _dict_or_none(metadata.get("director_decision"))
    if decision is not None:
        state.last_director_decision = _compact_director_decision(decision)


def _apply_event_focus_target(state: _MemoryEventState, target: dict[str, Any] | None) -> None:
    if target is None:
        return
    state.focus_target = target
    state.recent_targets.append(target)


def _apply_specialist_result(
    state: _MemoryEventState,
    event: AgentConversationEvent,
    target: dict[str, Any] | None,
) -> None:
    if event.event_type != "specialist_result":
        return
    metadata = event.metadata
    state.last_specialist_result_summary = {
        "specialist": metadata.get("specialist"),
        "result_type": metadata.get("result_type"),
        "applied": metadata.get("applied"),
        "target": target,
        "warnings": metadata.get("warnings") or [],
    }


def _apply_revision_memory_event(
    state: _MemoryEventState,
    event: AgentConversationEvent,
    target: dict[str, Any] | None,
) -> None:
    metadata = event.metadata
    revision_id = _optional_str(metadata.get("revision_id"))
    if not revision_id:
        return
    if event.event_type == "revision_started":
        state.open_revisions.append(
            {
                "revision_id": revision_id,
                "status": metadata.get("revision_status"),
                "generation_status": metadata.get("generation_status"),
                "acceptance_status": metadata.get("acceptance_status"),
                "target": target,
                "created_at": event.created_at,
            }
        )
    if event.event_type in {"revision_completed", "revision_failed"}:
        state.open_revisions = [
            item for item in state.open_revisions if item.get("revision_id") != revision_id
        ]


def _apply_execution_memory_event(
    state: _MemoryEventState,
    event: AgentConversationEvent,
    target: dict[str, Any] | None,
) -> None:
    if event.event_type != "execution_started":
        return
    execution_id = _optional_str(event.metadata.get("execution_id"))
    if not execution_id:
        return
    state.active_executions.append(
        {
            "execution_id": execution_id,
            "run_mode": event.metadata.get("run_mode"),
            "frontier_node_id": event.metadata.get("frontier_node_id"),
            "target": target,
            "status": "running",
            "created_at": event.created_at,
        }
    )


def _apply_recent_memory_action(
    state: _MemoryEventState,
    event: AgentConversationEvent,
    target: dict[str, Any] | None,
) -> None:
    if not _event_updates_memory_action(event):
        return
    metadata = event.metadata
    state.recent_actions.append(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "target_node_id": event.target_node_id,
            "target": target,
            "revision_id": metadata.get("revision_id"),
            "execution_id": metadata.get("execution_id"),
            "created_at": event.created_at,
        }
    )


def message_has_memory_reference(message: str) -> bool:
    lowered = f" {message.lower()} "
    return any(term in lowered or term in message for term in MEMORY_REFERENCE_TERMS)


def message_is_memory_focus_only(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered or term in message for term in MEMORY_FOCUS_ONLY_TERMS)


def target_reference_from_payload(
    value: dict[str, Any],
    *,
    source: str,
) -> CanvasTargetReference | None:
    target_type = _optional_str(value.get("target_type"))
    if target_type not in {"node", "item", "asset"}:
        return None
    try:
        return CanvasTargetReference(
            target_type=target_type,  # type: ignore[arg-type]
            node_id=_optional_str(value.get("node_id")),
            node_type=_optional_str(value.get("node_type")),
            item_id=_optional_str(value.get("item_id")),
            asset_id=_optional_str(value.get("asset_id")),
            semantic_type=_optional_str(value.get("semantic_type")),
            intent_scope=value.get("intent_scope") or "single",
            mention_text=_optional_str(value.get("mention_text")),
            source=source,  # type: ignore[arg-type]
            metadata=_dict_payload(value.get("metadata")),
        )
    except ValueError:
        return None


def compact_target(target: NormalizedCanvasTarget | dict[str, Any]) -> dict[str, Any]:
    payload = target.model_dump(mode="json") if hasattr(target, "model_dump") else target
    return {
        key: payload.get(key)
        for key in (
            "workflow_id",
            "target_type",
            "node_id",
            "node_type",
            "item_id",
            "asset_id",
            "semantic_type",
            "intent_scope",
            "display_name",
            "source",
        )
        if payload.get(key) is not None
    }


def compact_target_reference(reference: CanvasTargetReference) -> dict[str, Any]:
    payload = reference.model_dump(mode="json")
    return {
        key: payload.get(key)
        for key in (
            "target_type",
            "node_id",
            "node_type",
            "item_id",
            "asset_id",
            "semantic_type",
            "intent_scope",
            "mention_text",
            "source",
        )
        if payload.get(key) is not None
    }


def targets_conflict(
    first: CanvasTargetReference,
    second: CanvasTargetReference,
) -> bool:
    return _target_identity(first) != _target_identity(second)


def has_explicit_target(request: AgentConversationMessageRequest) -> bool:
    return bool(
        request.target_references
        or request.node_references
        or _string_list(request.context.get("mentioned_node_ids"))
    )


def _event_target(event: AgentConversationEvent) -> dict[str, Any] | None:
    target = _dict_or_none(event.metadata.get("target"))
    if target is not None:
        return compact_target(target)
    decision = _dict_or_none(event.metadata.get("director_decision"))
    decision_target = _dict_or_none(decision.get("target")) if decision else None
    if decision_target and decision_target.get("target_type") in {"node", "item", "asset"}:
        return compact_target(decision_target)
    if event.target_node_id:
        return {
            "target_type": "node",
            "node_id": event.target_node_id,
            "semantic_type": "workflow_node",
            "intent_scope": "single",
            "source": "inferred",
        }
    return None


def _compact_director_decision(decision: dict[str, Any]) -> dict[str, Any]:
    target = _dict_or_none(decision.get("target"))
    return {
        "intent": decision.get("intent"),
        "action": decision.get("action"),
        "confidence": decision.get("confidence"),
        "requires_confirmation": decision.get("requires_confirmation"),
        "reason": decision.get("reason"),
        "target": compact_target(target) if target else target,
        "warnings": decision.get("warnings") or [],
    }


def _event_updates_memory_action(event: AgentConversationEvent) -> bool:
    return event.event_type in {
        "node_prompt_updated",
        "item_prompt_updated",
        "execution_started",
        "revision_started",
        "revision_waiting",
        "revision_completed",
        "revision_failed",
        "director_context_updated",
        "conversation_memory_updated",
    }


def _merge_preferences(
    existing: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        key: list(value) if isinstance(value, list) else value for key, value in existing.items()
    }
    _append_preference(result, "style", message, ("高级", "premium", "minimal", "简洁"))
    _append_preference(result, "lighting", message, ("夜晚", "霓虹", "清晨", "night"))
    _append_preference(result, "composition", message, ("少杂物", "少", "留白"))
    return result


def _append_preference(
    preferences: dict[str, Any],
    key: str,
    message: str,
    terms: tuple[str, ...],
) -> None:
    values = preferences.get(key)
    if not isinstance(values, list):
        values = []
    lowered = message.lower()
    for term in terms:
        if term in message or term in lowered:
            if term not in values:
                values.append(term)
    if values:
        preferences[key] = _tail(values, 10)


def _target_identity(reference: CanvasTargetReference) -> tuple[str, str, str, str]:
    return (
        reference.target_type,
        reference.node_id or "",
        reference.item_id or "",
        reference.asset_id or "",
    )


def _memory_work_node_id(item: dict[str, Any]) -> str | None:
    node_id = _optional_str(item.get("node_id"))
    if node_id:
        return node_id
    target = _dict_payload(item.get("target"))
    return _optional_str(target.get("node_id"))


def _tail(values: list[Any], limit: int) -> list[Any]:
    if len(values) <= limit:
        return list(values)
    return list(values[-limit:])


def _dict_payload(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _optional_str(item))]
