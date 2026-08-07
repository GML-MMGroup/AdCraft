"""Deterministic validation for progressive Guidance decisions and completion."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_conversation import ConceptProposalV2
from app.schemas.agent_canvas_creative_session import (
    GuidanceCompletionClaimV2,
    GuidanceCompletionProjectionV2,
    GuidanceStagePolicyResultV2,
    GuidedSessionStateV2,
    NextGuidanceDecisionV2,
    GuidanceTopicKindV2,
)
from app.services.agent_canvas_guidance_ownership import TOPIC_SPECIALIST


class GuidanceDecisionValidator:
    """Reject invalid model authority without inventing replacement creative data."""

    def validate(
        self,
        decision: NextGuidanceDecisionV2,
        *,
        session: GuidedSessionStateV2 | None,
        workflow: AgentCanvasWorkflowV2,
        resolved_targets: tuple[str, ...],
        open_proposal: ConceptProposalV2 | None = None,
        required_topic_kind: GuidanceTopicKindV2 | None = None,
        stage_policy: GuidanceStagePolicyResultV2 | None = None,
    ) -> NextGuidanceDecisionV2:
        if (
            session is None
            and decision.action in {"propose_topic", "finish_guidance"}
            and (decision.intent_patch is None or decision.intent_patch.goal is None)
        ):
            raise _decision_error("The first guidance decision requires a creative goal.")
        workflow_ids = {node.node_id for node in workflow.nodes} | {
            asset.asset_id for asset in workflow.assets
        }
        if any(target_id not in workflow_ids for target_id in resolved_targets):
            raise _decision_error("A resolved target is outside the current Workflow.")
        if required_topic_kind is not None:
            if decision.action == "finish_guidance":
                raise _decision_error("World Setting must be established before guidance finishes.")
            if decision.action == "propose_topic" and decision.topic_kind != required_topic_kind:
                raise _decision_error(
                    "World Setting must be the first creative topic in guided production."
                )
        if decision.action == "propose_topic":
            if session is not None and session.status != "active":
                raise _decision_error("A paused or completed session cannot propose a topic.")
            if open_proposal is not None:
                raise _decision_error("The current open Proposal must be resolved first.")
            if TOPIC_SPECIALIST[decision.topic_kind] != decision.specialist_name:
                raise _decision_error("The proposed topic has the wrong Specialist owner.")
            stage_kind = {
                "creative_direction": "narrative_direction",
                "audio": "bgm",
            }.get(decision.topic_kind, decision.topic_kind)
            if stage_policy is not None and stage_kind not in stage_policy.allowed_stage_kinds:
                raise V2PersistenceError(
                    "guidance_stage_not_allowed",
                    "The proposed stage is outside the current guidance policy.",
                    stage="guidance_decision_validator",
                    details={"stage_kind": stage_kind},
                )
            if session is not None and any(
                item.element_kind == decision.topic_kind and item.presence == "exclude"
                for item in session.element_decisions
            ):
                raise _decision_error("An explicitly excluded element cannot be proposed.")
        if session is not None and decision.intent_patch is not None:
            excluded = {
                item.element_kind
                for item in session.element_decisions
                if item.presence == "exclude"
            }
            if any(
                item.element_kind in excluded and item.presence == "include"
                for item in decision.intent_patch.element_decisions
            ):
                raise _decision_error("An explicit exclusion cannot be silently reversed.")
        return decision


class GuidanceCompletionService:
    """Validate model completion claims against canonical Nodes and Assets."""

    def validate(
        self,
        goal,
        claim: GuidanceCompletionClaimV2,
        workflow: AgentCanvasWorkflowV2,
        assets: tuple[ProjectAssetSummaryV2, ...],
    ) -> GuidanceCompletionProjectionV2:
        expected_node_type = {
            "text": "text",
            "script": "script",
            "image": "image",
            "video": "video",
            "audio": "audio",
        }[goal.requested_output]
        matching_nodes = tuple(
            node
            for node in workflow.nodes
            if node.node_type == expected_node_type
            and node.node_id in claim.node_ids
            and node.status in {"draft", "working", "ready"}
        )
        if not matching_nodes:
            raise _completion_error("The completion claim has no matching canonical Node.")
        if goal.delivery_scope == "draft":
            if claim.state != "authoring_ready":
                raise _completion_error("A Draft goal requires authoring-ready evidence.")
            return GuidanceCompletionProjectionV2(
                authoring="ready",
                delivery="not_ready",
                matching_node_ids=tuple(node.node_id for node in matching_nodes),
            )
        asset_by_id = {asset.asset_id: asset for asset in assets}
        matching_assets = tuple(
            asset_by_id[asset_id]
            for asset_id in claim.asset_ids
            if asset_id in asset_by_id
            and asset_by_id[asset_id].media_type == goal.requested_output
            and asset_by_id[asset_id].status == "ready"
        )
        ready_node_ids = {
            node.node_id
            for node in matching_nodes
            if node.status == "ready"
            and node.output_asset_id in {asset.asset_id for asset in matching_assets}
        }
        if claim.state != "delivery_ready" or not ready_node_ids or not matching_assets:
            raise _completion_error("Generated-media completion requires a Ready Node and Asset.")
        return GuidanceCompletionProjectionV2(
            authoring="ready",
            delivery="ready",
            matching_node_ids=tuple(sorted(ready_node_ids)),
            matching_asset_ids=tuple(asset.asset_id for asset in matching_assets),
        )


def _decision_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_decision_invalid",
        message,
        stage="guidance_decision_validator",
    )


def _completion_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guidance_completion_invalid",
        message,
        stage="guidance_completion_service",
    )
