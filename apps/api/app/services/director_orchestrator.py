from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal

from app.core.config import Settings
from app.schemas.agent_conversations import NodeReference
from app.schemas.canvas_targets import CanvasTargetReference, NormalizedCanvasTarget
from app.schemas.director_orchestrator import DirectorDecision
from app.schemas.workflow_graph import WorkflowGraph, WorkflowGraphNode
from app.services.canvas_targets import (
    CanvasTargetResolutionError,
    CanvasTargetResolverService,
)
from app.services.chat_canvas_actions import ChatCanvasActionProtocolService
from app.services.workflow_graph import WorkflowGraphError, WorkflowGraphService
from app.services.workflow_item_prompt_utils import item_id_from_payload


DirectorRoute = Literal["chat_canvas", "clarification", "director_context"]


@dataclass(frozen=True)
class DirectorOrchestrationPlan:
    route: DirectorRoute
    decision: DirectorDecision
    target_references: list[CanvasTargetReference] = field(default_factory=list)
    node_references: list[NodeReference] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    clarification_text: str | None = None


class DirectorOrchestratorService:
    def __init__(
        self,
        settings: Settings,
        *,
        workflow_graph_service: WorkflowGraphService | None = None,
        chat_canvas_action_service: ChatCanvasActionProtocolService | None = None,
        target_resolver: CanvasTargetResolverService | None = None,
    ) -> None:
        self._settings = settings
        self._graph_service = workflow_graph_service or WorkflowGraphService(
            data_dir=settings.media_data_dir
        )
        self._chat_canvas_actions = chat_canvas_action_service or ChatCanvasActionProtocolService(
            settings=settings,
            workflow_graph_service=self._graph_service,
        )
        self._target_resolver = target_resolver or CanvasTargetResolverService(
            settings,
            workflow_graph_service=self._graph_service,
        )

    def plan(
        self,
        *,
        workflow_id: str | None,
        message: str,
        target_references: list[CanvasTargetReference | dict[str, Any]],
        node_references: list[NodeReference | dict[str, Any]],
        context: dict[str, Any],
        focus_node_id: str | None,
    ) -> DirectorOrchestrationPlan | None:
        if not workflow_id:
            return None

        action_type = self._action_type_for_message(message)
        explicit_plan = self._explicit_target_plan(
            workflow_id=workflow_id,
            message=message,
            action_type=action_type,
            target_references=target_references,
            node_references=node_references,
        )
        if target_references or node_references:
            return explicit_plan
        if explicit_plan is not None:
            return explicit_plan

        global_plan = self._global_director_update_plan(message, context)
        if global_plan is not None:
            return global_plan

        if action_type is None:
            return self._no_action_type_plan(message, context)

        selected_plan = self._selected_context_plan(
            workflow_id=workflow_id,
            message=message,
            action_type=action_type,
            context=context,
        )
        if selected_plan is not None:
            return selected_plan

        inferred_plan = self._semantic_inference_plan(
            workflow_id=workflow_id,
            message=message,
            action_type=action_type,
        )
        if inferred_plan is not None:
            return inferred_plan

        if self._looks_batch_scene_update(message):
            return self._clarification_plan(
                reason="batch_requires_confirmation",
                message="你想一次修改所有场景，还是只修改其中一个场景？",
                decision_reason="Batch scene updates require confirmation.",
                confidence=0.58,
            )

        if focus_node_id:
            return None

        return self._fallback_ambiguous_target_plan(message, context)

    def _action_type_for_message(self, message: str) -> str | None:
        action = self._chat_canvas_actions.classify_message(message)
        if action is not None:
            return action.action_type
        if self._looks_director_prompt_update(message):
            return "update_prompt_only"
        return None

    def _global_director_update_plan(
        self, message: str, context: dict[str, Any]
    ) -> DirectorOrchestrationPlan | None:
        if not self._is_global_director_update(message, context):
            return None
        return DirectorOrchestrationPlan(
            route="director_context",
            decision=DirectorDecision(
                intent="update_director_context",
                action="update_director_context",
                target=None,
                confidence=0.84,
                requires_confirmation=False,
                reason="User requested a global creative direction update.",
            ),
        )

    def _no_action_type_plan(
        self, message: str, context: dict[str, Any]
    ) -> DirectorOrchestrationPlan | None:
        if self._looks_ambiguous_without_target(message, context):
            return self._clarification_plan(
                reason="target_ambiguous",
                message="你想修改哪个场景或分镜？",
                decision_reason="The user asked for a change but no target was available.",
                confidence=0.42,
            )
        return None

    def _fallback_ambiguous_target_plan(
        self, message: str, context: dict[str, Any]
    ) -> DirectorOrchestrationPlan | None:
        if not self._looks_ambiguous_without_target(message, context):
            return None
        return self._clarification_plan(
            reason="target_ambiguous",
            message="你想修改哪个场景或分镜？",
            decision_reason="The request contains an edit intent but no resolvable target.",
            confidence=0.45,
        )

    def _explicit_target_plan(
        self,
        *,
        workflow_id: str,
        message: str,
        action_type: str | None,
        target_references: list[CanvasTargetReference | dict[str, Any]],
        node_references: list[NodeReference | dict[str, Any]],
    ) -> DirectorOrchestrationPlan | None:
        if action_type is None or (not target_references and not node_references):
            return None
        target = self._target_resolver.resolve_explicit_target(
            workflow_id=workflow_id,
            target_references=target_references,
            node_references=node_references,
        )
        if isinstance(target, CanvasTargetResolutionError) or target is None:
            return None
        return DirectorOrchestrationPlan(
            route="chat_canvas",
            decision=self._decision_for_target(
                target=target,
                action_type=action_type,
                confidence=0.9,
                reason="User provided an explicit canvas target.",
            ),
            target_references=[_target_reference(ref) for ref in target_references],
            node_references=[_node_reference(ref) for ref in node_references],
            context={},
        )

    def _selected_context_plan(
        self,
        *,
        workflow_id: str,
        message: str,
        action_type: str,
        context: dict[str, Any],
    ) -> DirectorOrchestrationPlan | None:
        mentioned_node_ids = _string_list(context.get("mentioned_node_ids"))
        if mentioned_node_ids:
            if len(mentioned_node_ids) != 1:
                return self._clarification_plan(
                    reason="target_ambiguous",
                    message="请只指定一个要修改或运行的节点。",
                    decision_reason="Context mentioned more than one node.",
                    confidence=0.48,
                    candidate_targets=[
                        {"target_type": "node", "node_id": node_id}
                        for node_id in mentioned_node_ids
                    ],
                )
            reference = CanvasTargetReference(
                target_type="node",
                node_id=mentioned_node_ids[0],
                semantic_type="workflow_node",
                intent_scope="single",
                source="mention",
            )
            target = self._target_resolver.resolve_target(
                workflow_id=workflow_id,
                reference=reference,
            )
            if isinstance(target, CanvasTargetResolutionError):
                return None
            return DirectorOrchestrationPlan(
                route="chat_canvas",
                decision=self._decision_for_target(
                    target=target,
                    action_type=action_type,
                    confidence=0.84,
                    reason="User message included a structured mentioned node id.",
                ),
                target_references=[reference],
                context={},
            )
        selected_node_id = _optional_str(context.get("selected_node_id"))
        selected_item_id = _optional_str(context.get("selected_item_id"))
        selected_asset_id = _optional_str(context.get("selected_asset_id"))
        if selected_item_id and selected_node_id:
            reference = CanvasTargetReference(
                target_type="item",
                node_id=selected_node_id,
                item_id=selected_item_id,
                semantic_type=_optional_str(context.get("selected_item_semantic_type")),
                intent_scope="single",
                source="selected_item",
            )
            target = self._target_resolver.resolve_target(
                workflow_id=workflow_id,
                reference=reference,
            )
            if isinstance(target, CanvasTargetResolutionError):
                return self._clarification_plan(
                    reason="target_ambiguous",
                    message="选中的 item 已不可用，请重新选择要修改的内容。",
                    decision_reason=target.message,
                    confidence=0.5,
                    warnings=[target.error_code],
                )
            return DirectorOrchestrationPlan(
                route="chat_canvas",
                decision=self._decision_for_target(
                    target=target,
                    action_type=action_type,
                    confidence=0.82,
                    reason="User message used the selected item context.",
                ),
                target_references=[reference],
                context={},
            )
        if selected_asset_id:
            return self._clarification_plan(
                reason="director_action_unsupported",
                message="当前还不能直接编辑单个资产，请选择节点或 item。",
                decision_reason="Asset-level repaint/editing is outside Director Orchestrator v1.",
                confidence=0.62,
            )
        if selected_node_id:
            reference = CanvasTargetReference(
                target_type="node",
                node_id=selected_node_id,
                semantic_type="workflow_node",
                intent_scope="single",
                source="selected_node",
            )
            target = self._target_resolver.resolve_target(
                workflow_id=workflow_id,
                reference=reference,
            )
            if isinstance(target, CanvasTargetResolutionError):
                return None
            return DirectorOrchestrationPlan(
                route="chat_canvas",
                decision=self._decision_for_target(
                    target=target,
                    action_type=action_type,
                    confidence=0.78,
                    reason="User message used the selected node context.",
                ),
                target_references=[reference],
                context={},
            )
        return None

    def _semantic_inference_plan(
        self,
        *,
        workflow_id: str,
        message: str,
        action_type: str,
    ) -> DirectorOrchestrationPlan | None:
        ordinal = _scene_ordinal(message)
        if ordinal is None:
            return None
        try:
            graph = self._graph_service.get_graph(workflow_id)
        except WorkflowGraphError:
            return self._clarification_plan(
                reason="director_target_not_found",
                message="没有找到当前 workflow 的画布状态。",
                decision_reason=f"Workflow graph not found: {workflow_id}.",
                confidence=0.4,
            )
        candidates = self._scene_item_candidates(graph, ordinal)
        if len(candidates) != 1:
            return self._clarification_plan(
                reason="target_ambiguous",
                message="我没法唯一确定你说的是哪个场景，请点选或 @ 一个具体场景。",
                decision_reason="Semantic scene ordinal did not resolve to exactly one target.",
                confidence=0.5,
                candidate_targets=[target.model_dump(mode="json") for target in candidates],
            )
        target = candidates[0]
        reference = CanvasTargetReference(
            target_type="item",
            node_id=target.node_id,
            item_id=target.item_id,
            semantic_type=target.semantic_type,
            intent_scope="single",
            source="inferred",
        )
        return DirectorOrchestrationPlan(
            route="chat_canvas",
            decision=self._decision_for_target(
                target=target,
                action_type=action_type,
                confidence=0.76,
                reason="Semantic ordinal phrase resolved to one scene item.",
            ),
            target_references=[reference],
            context={},
        )

    def _scene_item_candidates(
        self,
        graph: WorkflowGraph,
        ordinal: int,
    ) -> list[NormalizedCanvasTarget]:
        candidates: list[NormalizedCanvasTarget] = []
        for node in graph.nodes:
            if node.node_type != "scene-generation":
                continue
            seen_item_ids: set[str] = set()
            for item in _iter_dynamic_items(node):
                item_id = item_id_from_payload(item)
                if not item_id or item_id in seen_item_ids:
                    continue
                if _item_order(item, item_id) != ordinal:
                    continue
                seen_item_ids.add(item_id)
                target = self._target_resolver.resolve_target(
                    workflow_id=node.workflow_id,
                    reference=CanvasTargetReference(
                        target_type="item",
                        node_id=node.id,
                        item_id=item_id,
                        semantic_type="scene",
                        intent_scope="single",
                        source="inferred",
                    ),
                )
                if isinstance(target, NormalizedCanvasTarget):
                    candidates.append(target)
        return candidates

    def _decision_for_target(
        self,
        *,
        target: NormalizedCanvasTarget,
        action_type: str,
        confidence: float,
        reason: str,
    ) -> DirectorDecision:
        intent, action = _intent_and_action(target.target_type, action_type)
        return DirectorDecision(
            intent=intent,
            action=action,
            target=target.model_dump(mode="json"),
            confidence=confidence,
            requires_confirmation=False,
            reason=reason,
        )

    def _clarification_plan(
        self,
        *,
        reason: str,
        message: str,
        decision_reason: str,
        confidence: float,
        warnings: list[str] | None = None,
        candidate_targets: list[dict[str, Any]] | None = None,
    ) -> DirectorOrchestrationPlan:
        metadata = {"reason": reason, "candidate_targets": candidate_targets or []}
        return DirectorOrchestrationPlan(
            route="clarification",
            decision=DirectorDecision(
                intent="clarify",
                action="clarification_requested",
                target=metadata,
                confidence=confidence,
                requires_confirmation=True,
                reason=decision_reason,
                warnings=warnings or [],
            ),
            clarification_text=message,
        )

    def _is_global_director_update(self, message: str, context: dict[str, Any]) -> bool:
        if context.get("force_director_context_update") is True:
            return True
        lowered = message.lower()
        global_terms = (
            "global",
            "overall",
            "brand direction",
            "creative direction",
            "整体",
            "全局",
            "整体创意",
            "整体方向",
            "品牌调性",
        )
        style_terms = (
            "apple",
            "premium",
            "minimal",
            "restrained",
            "高级",
            "克制",
            "留白",
            "苹果广告",
            "风格",
            "调性",
        )
        return (
            any(term in lowered for term in global_terms)
            or any(term in message for term in global_terms)
        ) and (
            any(term in lowered for term in style_terms)
            or any(term in message for term in style_terms)
        )

    def _looks_ambiguous_without_target(self, message: str, context: dict[str, Any]) -> bool:
        if context.get("selected_node_id") or context.get("selected_item_id"):
            return False
        return bool(
            re.search(r"\b(this|here|it)\b", message.lower())
            or any(term in message for term in ("这里", "这个", "它", "不太对", "帮我改"))
        )

    def _looks_batch_scene_update(self, message: str) -> bool:
        lowered = message.lower()
        return ("all scenes" in lowered) or (
            ("所有" in message or "全部" in message) and "场景" in message
        )

    def _looks_director_prompt_update(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            term in lowered
            for term in (
                "cleaner",
                "simpler",
                "too busy",
                "less clutter",
                "low angle",
            )
        ) or any(term in message for term in ("太乱", "简洁", "低角度", "夜晚", "改成"))


def _target_reference(value: CanvasTargetReference | dict[str, Any]) -> CanvasTargetReference:
    if isinstance(value, CanvasTargetReference):
        return value
    return CanvasTargetReference.model_validate(value)


def _node_reference(value: NodeReference | dict[str, Any]) -> NodeReference:
    if isinstance(value, NodeReference):
        return value
    return NodeReference.model_validate(value)


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


def _intent_and_action(target_type: str, action_type: str) -> tuple[str, str]:
    if target_type == "item":
        if action_type == "update_prompt_and_run_node":
            return "update_item_prompt_and_run", "update_item_prompt_and_run"
        if action_type == "run_node_only":
            return "run_item", "run_item"
        return "update_item_prompt", "update_item_prompt"
    if action_type == "update_prompt_and_run_node":
        return "update_node_prompt_and_run", "update_prompt_and_run_node"
    if action_type == "run_node_only":
        return "run_node", "run_node_only"
    if action_type == "update_prompt_and_run_downstream":
        return "update_node_prompt_and_run", "update_prompt_and_run_downstream"
    return "update_node_prompt", "update_prompt_only"


def _scene_ordinal(message: str) -> int | None:
    patterns = (
        r"第\s*([一二三四五六七八九十\d]+)\s*个?\s*场景",
        r"([一二三四五六七八九十\d]+)\s*个?\s*场景",
        r"(?:scene|场景)\s*([0-9]+)",
        r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+scene",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        return _ordinal_to_int(match.group(1))
    return None


def _ordinal_to_int(value: str) -> int | None:
    text = value.strip().lower()
    english = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
    }
    if text in english:
        return english[text]
    if text.isdigit():
        return int(text)
    chinese = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese.get(text)


def _iter_dynamic_items(node: WorkflowGraphNode) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for payload in (node.output, node.input_context):
        _collect_dynamic_items(payload, items)
    return items


def _collect_dynamic_items(value: Any, items: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if item_id_from_payload(value):
            items.append(value)
            return
        for item in value.values():
            _collect_dynamic_items(item, items)
    elif isinstance(value, list):
        for item in value:
            _collect_dynamic_items(item, items)


def _item_order(item: dict[str, Any], item_id: str) -> int | None:
    order = item.get("order")
    if isinstance(order, int):
        return order
    if isinstance(order, str) and order.isdigit():
        return int(order)
    match = re.search(r"(\d+)$", item_id)
    return int(match.group(1)) if match else None
