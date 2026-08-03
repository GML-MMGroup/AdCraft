"""Deterministic validation and readiness projection for Agent Canvas plans."""

from __future__ import annotations

from collections.abc import Iterable

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, ProjectAssetV2
from app.schemas.agent_canvas_creative_session import (
    AdaptiveProductionRecipeDraftV2,
    AdaptiveProductionRecipeV2,
    ProductionCompletionProjectionV2,
    ProductionReadinessProjectionV2,
)
from app.schemas.agent_canvas_runtime import CanvasRuntimeSnapshotV2
from app.schemas.agent_operation_contexts import DirectorTurnContextV2


class AgentCanvasProductionPlanService:
    """Validate plan-only data and derive fact-based readiness without mutation."""

    def validate_draft(
        self,
        draft: AdaptiveProductionRecipeDraftV2,
        *,
        context: DirectorTurnContextV2,
        workflow: AgentCanvasWorkflowV2,
    ) -> AdaptiveProductionRecipeDraftV2:
        if context.workflow_id != workflow.workflow_id:
            raise _error(
                "production_plan_invalid",
                "The production plan context does not belong to this workflow.",
            )
        if context.approved_anchor_digest and context.approved_anchor_digest != draft.anchor_digest:
            raise _error(
                "production_plan_invalid",
                "The production plan does not preserve approved anchors.",
            )

        topic_ids = tuple(stage.topic_id for stage in draft.stages)
        deliverable_ids = tuple(item.deliverable_id for item in draft.deliverables)
        if len(topic_ids) != len(set(topic_ids)) or len(deliverable_ids) != len(
            set(deliverable_ids)
        ):
            raise _error("production_plan_invalid", "Production plan identities must be unique.")
        if any(topic_id not in set(topic_ids) for topic_id in draft.recommended_next_topic_ids):
            raise _error(
                "production_plan_invalid",
                "Production plan recommendations must reference known topics.",
            )
        self._validate_dependencies(topic_ids, draft)
        self._validate_completion_criteria(deliverable_ids, draft)
        if not any(item.required for item in draft.deliverables):
            raise _error(
                "production_plan_invalid",
                "Guided production requires a reachable required deliverable.",
            )
        if not any(stage.applicability != "not_required" for stage in draft.stages):
            raise _error(
                "production_plan_invalid",
                "Guided production requires an applicable planning topic.",
            )
        return draft

    def readiness(
        self,
        recipe: AdaptiveProductionRecipeV2,
        *,
        workflow: AgentCanvasWorkflowV2,
        runtime: CanvasRuntimeSnapshotV2,
        assets: tuple[ProjectAssetV2, ...],
    ) -> ProductionReadinessProjectionV2:
        required_stages = tuple(
            stage for stage in recipe.stages if stage.applicability == "required"
        )
        planning = (
            "complete"
            if required_stages
            and all(stage.status in {"completed", "skipped"} for stage in required_stages)
            else "in_progress"
        )
        media_nodes = tuple(
            node for node in workflow.nodes if node.node_type in {"image", "video", "audio"}
        )
        runtime_states = {
            node_id: item.visible_status for node_id, item in runtime.node_runtime.items()
        }
        node_states = tuple(runtime_states.get(node.node_id, node.status) for node in media_nodes)
        generation = _generation_state(node_states)
        delivery = _delivery_state(recipe, workflow, assets)
        return ProductionReadinessProjectionV2(
            discussable_topic_ids=tuple(
                stage.topic_id
                for stage in recipe.stages
                if stage.applicability != "not_required"
                and stage.status in {"pending", "working", "reopened"}
            ),
            materializable_topic_ids=tuple(
                stage.topic_id
                for stage in recipe.stages
                if stage.applicability != "not_required"
                and stage.status in {"pending", "working", "reopened"}
            ),
            runnable_node_ids=tuple(node.node_id for node in media_nodes if node.status == "draft"),
            completion=ProductionCompletionProjectionV2(
                planning=planning,
                generation=generation,
                delivery=delivery,
            ),
        )

    @staticmethod
    def _validate_dependencies(
        topic_ids: tuple[str, ...],
        draft: AdaptiveProductionRecipeDraftV2,
    ) -> None:
        known_topics = set(topic_ids)
        adjacency: dict[str, set[str]] = {topic_id: set() for topic_id in topic_ids}
        for dependency in draft.dependencies:
            if (
                dependency.source_topic_id not in known_topics
                or dependency.target_topic_id not in known_topics
            ):
                raise _error(
                    "production_plan_invalid",
                    "Production plan dependencies must reference known topics.",
                )
            adjacency[dependency.source_topic_id].add(dependency.target_topic_id)
        if _has_cycle(adjacency):
            raise _error(
                "production_plan_dependency_cycle",
                "Production plan dependencies must be acyclic.",
            )

    @staticmethod
    def _validate_completion_criteria(
        deliverable_ids: tuple[str, ...],
        draft: AdaptiveProductionRecipeDraftV2,
    ) -> None:
        known_deliverables = set(deliverable_ids)
        criteria_ids = set(draft.completion_criteria.required_deliverable_ids)
        criteria_ids.update(draft.completion_criteria.accepted_omission_deliverable_ids)
        if not criteria_ids.issubset(known_deliverables):
            raise _error(
                "production_plan_invalid",
                "Completion criteria must reference known deliverables.",
            )


def _has_cycle(adjacency: dict[str, set[str]]) -> bool:
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(topic_id: str) -> bool:
        if topic_id in visiting:
            return True
        if topic_id in visited:
            return False
        visiting.add(topic_id)
        try:
            return any(visit(child) for child in adjacency[topic_id])
        finally:
            visiting.discard(topic_id)
            visited.add(topic_id)

    return any(visit(topic_id) for topic_id in adjacency)


def _generation_state(node_states: Iterable[str]) -> str:
    states = tuple(node_states)
    if not states or all(state == "draft" for state in states):
        return "not_started"
    if any(state == "working" for state in states):
        return "in_progress"
    if all(state == "ready" for state in states):
        return "complete"
    if any(state == "ready" for state in states) and any(state == "failed" for state in states):
        return "partial_failed"
    if all(state == "failed" for state in states):
        return "failed"
    return "in_progress"


def _delivery_state(
    recipe: AdaptiveProductionRecipeV2,
    workflow: AgentCanvasWorkflowV2,
    assets: tuple[ProjectAssetV2, ...],
) -> str:
    required_ids = set(recipe.completion_criteria.required_deliverable_ids)
    deliverables = tuple(
        item
        for item in recipe.deliverables
        if item.required and (not required_ids or item.deliverable_id in required_ids)
    )
    if not deliverables:
        return "not_ready"
    ready_asset_ids = {asset.asset_id for asset in assets if asset.status == "ready"}
    ready_source_nodes = {
        asset.source_node_id for asset in assets if asset.status == "ready" and asset.source_node_id
    }
    complete = tuple(
        item
        for item in deliverables
        if set(item.related_asset_ids).issubset(ready_asset_ids)
        and set(item.related_node_ids).issubset(ready_source_nodes)
        and (item.related_asset_ids or item.related_node_ids)
    )
    if len(complete) == len(deliverables):
        return "ready"
    failed_nodes = {node.node_id for node in workflow.nodes if node.status == "failed"}
    if any(set(item.related_node_ids) & failed_nodes for item in deliverables):
        return "failed" if not complete else "partial"
    return "partial" if complete else "not_ready"


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_production_plan")
