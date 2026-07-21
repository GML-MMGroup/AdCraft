from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.schemas.canvas_targets import NormalizedCanvasTarget
from app.schemas.director_context import DirectorContext
from app.schemas.specialist_agents import (
    SpecialistResult,
)
from app.schemas.workflow_graph import (
    WorkflowGraph,
    WorkflowGraphNode,
)
from app.services.chat_canvas_actions import (
    ChatCanvasActionResult,
    ResolvedChatCanvasAction,
)


class AgentConversationError(RuntimeError):
    """Base error for agent conversation operations."""


class AgentConversationInputError(AgentConversationError, ValueError):
    """Raised when a conversation request is invalid."""


@dataclass(frozen=True)
class _ResolvedNodeMention:
    node: WorkflowGraphNode
    source: str
    mention_text: str | None = None


@dataclass(frozen=True)
class _NodeMentionError:
    error_code: str
    message: str
    target_node_id: str | None = None
    metadata: dict[str, Any] | None = None


VISIBLE_AGENT_TO_NODE: dict[str, str | None] = {
    "creative_director": None,
    "script_writer": "script",
    "character_designer": "character-generation",
    "scene_designer": "scene-generation",
    "storyboard_artist": "storyboard",
    "video_director": "storyboard-video-generation",
    "sound_director": "bgm",
    "final_composition_assistant": "final-composition",
}
SPECIALIST_BY_NODE: dict[str, str] = {
    node_id: agent for agent, node_id in VISIBLE_AGENT_TO_NODE.items() if node_id is not None
}
SPECIALIST_BY_NODE_TYPE = dict(SPECIALIST_BY_NODE)
USER_TARGETABLE_NODE_TYPES = set(SPECIALIST_BY_NODE_TYPE)
PROMPT_UPDATE_KEYWORDS = (
    "adjust",
    "change",
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
)


def _dict_payload(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _resolution_needs_specialist(resolution: ResolvedChatCanvasAction) -> bool:
    return resolution.action.updates_prompt


def _specialist_action_name(resolution: ResolvedChatCanvasAction) -> str:
    action_type = resolution.action.action_type
    return {
        "update_prompt_only": "update_node_prompt",
        "update_prompt_and_run_node": "update_node_prompt_and_run",
        "update_prompt_and_run_downstream": "update_node_prompt_and_run_downstream",
        "update_item_prompt_only": "update_item_prompt",
        "update_item_prompt_and_run": "update_item_prompt_and_run",
        "run_node_only": "run_node",
        "run_item_only": "run_item",
    }.get(action_type, action_type)


def _target_current_prompt(resolution: ResolvedChatCanvasAction) -> str | None:
    target = resolution.target
    if target is not None and target.target_type == "item":
        item = _target_item_context(target)
        return _first_text(
            item.get("prompt"),
            item.get("scenePrompt"),
            item.get("storyboardPrompt"),
            item.get("characterPrompt"),
            item.get("generation_prompt"),
        )
    if target is not None and target.target_type == "asset":
        asset = _target_asset_summary(target)
        return _first_text(asset.get("prompt"), asset.get("generation_prompt"))
    node = resolution.node
    return _first_text(
        node.prompt,
        node.override_prompt,
        node.input_context.get("user_prompt"),
        node.input_context.get("system_suggested_prompt"),
    )


def _target_item_context(target: NormalizedCanvasTarget) -> dict[str, Any]:
    item = target.metadata.get("item") if isinstance(target.metadata, dict) else None
    return dict(item) if isinstance(item, dict) else {}


def _target_asset_summary(target: NormalizedCanvasTarget) -> dict[str, Any]:
    asset = target.metadata.get("asset") if isinstance(target.metadata, dict) else None
    return dict(asset) if isinstance(asset, dict) else {}


def _specialist_action_overrides(
    result: SpecialistResult,
) -> tuple[str | None, str | None]:
    if result.result_type in {"revised_node_prompt", "revised_item_prompt"}:
        return result.revised_prompt, None
    if result.result_type == "revision_instruction":
        return None, result.revision_instruction
    return None, None


def _specialist_result_was_applied(result: ChatCanvasActionResult) -> bool:
    return bool(
        result.prompt_update or result.item_prompt_update or result.execution or result.revision
    )


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
    return re.sub(r"\s+", " ", cleaned).strip() or message.strip()


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


def _director_node_briefs_from_message(message: str) -> dict[str, str]:
    suggestion = f"整体创意方向更新：{message}"
    return {
        "script": suggestion,
        "character_generation": suggestion,
        "scene_generation": suggestion,
        "storyboard": suggestion,
        "storyboard_video_generation": suggestion,
        "bgm": suggestion,
        "final_composition": suggestion,
    }


def _system_suggestion_for_node(
    node: WorkflowGraphNode,
    node_briefs: dict[str, Any],
    director_context: DirectorContext,
) -> str:
    key = node.node_type.replace("-", "_")
    suggestion = _optional_str(node_briefs.get(key))
    if suggestion:
        return suggestion
    creative_update = _optional_str(director_context.creative_direction.get("user_update"))
    return f"整体创意方向更新：{creative_update}" if creative_update else ""


def _node_prompt_is_user_owned(metadata: dict[str, Any]) -> bool:
    if metadata.get("manual_prompt_dirty") is True:
        return True
    return str(metadata.get("prompt_source") or "") in {"user", "optimized_applied"}


def _action_title(action_type: str) -> str:
    return {
        "apply_prompt_to_node": "Apply prompt to node",
        "optimize_node_prompt": "Optimize node prompt",
        "run_node": "Run node",
        "revise_node_asset": "Revise node asset",
        "update_director_context": "Update director context",
        "create_workflow": "Create workflow",
    }.get(action_type, "Apply action")


def _action_summary(action_type: str, target_node_id: str | None) -> str:
    node = f" `{target_node_id}`" if target_node_id else ""
    return {
        "apply_prompt_to_node": f"Apply the proposed prompt to{node}.",
        "optimize_node_prompt": f"Run optimize-only prompt generation for{node}.",
        "run_node": f"Run{node} after user confirmation.",
        "revise_node_asset": f"Run a local asset revision for{node}.",
        "update_director_context": "Refresh the hidden Director context.",
        "create_workflow": "Create a new planned workflow.",
    }.get(action_type, "Apply the suggested action.")
