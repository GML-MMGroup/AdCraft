"""Pure compilation of validated capability output into one commit plan."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from app.schemas.agent_canvas import CanvasBindingV2, CanvasNodeV2
from app.schemas.agent_canvas_conversation import AgentActionReceiptV2, ContinuationCommitV2
from app.schemas.agent_canvas_capability_drafts import CapabilityDraftBundleV1
from app.schemas.agent_canvas_draft_seeds import AcceptedProposalCommitmentV1
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    MaterializationNormalizationV1,
    ProposalApplicationEnvelopeV1,
)
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationAuthoringSnapshotV1,
    MaterializationDocumentWriteV1,
    MaterializationPlanV1,
    NodePromptPreparationIntentV1,
    StageMaterializedJourneyEventV1,
    TargetedActionCompletedJourneyEventV1,
    materialization_plan_digest,
)
from app.services.agent_canvas_capability_draft_bundle import CapabilityDraftBundleBuilder


class CapabilityMaterializationPlanCompiler:
    """Compile one immutable plan without I/O, clocks, or external execution."""

    def compile_draft_bundle(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
    ) -> CapabilityDraftBundleV1:
        """Compile the canonical draft bundle used to prepare authority documents."""

        return CapabilityDraftBundleBuilder().build(envelope, normalization)

    def compile(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
        *,
        snapshot: MaterializationAuthoringSnapshotV1,
        storyboard_documents: tuple[MaterializationDocumentWriteV1, ...] = (),
    ) -> MaterializationPlanV1:
        bundle = self.compile_draft_bundle(envelope, normalization)
        nodes = bundle.nodes
        bindings = bundle.bindings
        preparations = bundle.prompt_preparations
        storyboard_draft_preparation_queued = _has_storyboard_draft_preparation_evidence(
            envelope,
            nodes=nodes,
            preparations=preparations,
            documents=storyboard_documents,
        )
        if (
            envelope.capability_id == "storyboard_design"
            and snapshot.current_journey.stage == "storyboard_grids"
            and not storyboard_draft_preparation_queued
        ):
            raise ValueError(
                "Storyboard plan materialization requires Storyboard Grid Draft preparation evidence."
            )

        continuation = _continuation(envelope, snapshot)
        receipt = _receipt(
            envelope,
            snapshot,
            nodes=nodes,
            bindings=bindings,
            continuation=continuation,
        )
        payload: dict[str, Any] = {
            "schema_version": "1",
            "materialization_id": envelope.materialization_id,
            "workflow_id": envelope.workflow_id,
            "proposal_id": envelope.proposal_id,
            "option_id": envelope.selected_option.option_id,
            "custom_text": envelope.selected_option.custom_text,
            "action_turn_id": envelope.action_turn_id,
            "proposal_action": envelope.action,
            "selection_actor": envelope.selection_actor,
            "expected_workflow_revision": snapshot.workflow_revision,
            "expected_session_revision": snapshot.session_revision,
            "stage_revision": envelope.stage_revision,
            "expected_proposal_revision": snapshot.proposal_revision,
            "expected_target_node_revision": snapshot.target_node_revision,
            "nodes": nodes,
            "bindings": bindings,
            "document_writes": storyboard_documents,
            "requirement_commitments": _commitments(envelope),
            "receipt": receipt,
            "continuation": continuation,
            "prompt_preparations": preparations,
            "operation_kind": envelope.operation_kind,
            "parent_snapshot": envelope.parent_snapshot,
            "derivative_intent": bundle.derivative_intent,
            "journey_event": _journey_event(
                envelope,
                snapshot,
                storyboard_draft_preparation_queued=storyboard_draft_preparation_queued,
            ),
            "payload_digest": "0" * 64,
        }
        provisional = MaterializationPlanV1.model_construct(**payload)
        payload["payload_digest"] = materialization_plan_digest(provisional)
        return MaterializationPlanV1.model_validate(payload)


def _continuation(
    envelope: ProposalApplicationEnvelopeV1,
    snapshot: MaterializationAuthoringSnapshotV1,
) -> ContinuationCommitV2 | None:
    if envelope.operation_kind == "parent":
        # Parent-derived work is queued by ParentDerivedMaterializationCoordinator
        # after the parent authority transaction commits.
        return None
    if not (
        envelope.target_node_id is not None
        or envelope.capability_id == "quick_media"
        or snapshot.current_journey.suspended_action is not None
    ):
        return None
    digest = _digest(f"materialization-next-action:{envelope.materialization_id}")
    return ContinuationCommitV2(
        continuation_id=f"continuation_{digest[:24]}",
        continuation_turn_id=f"turn_{digest[24:56]}",
        source_turn_id=envelope.action_turn_id,
        source_action_id=envelope.action_turn_id,
        idempotency_key=f"materialization-next-action:{envelope.materialization_id}",
        video_skill_run_id=envelope.style_skill_run_id,
    )


def _receipt(
    envelope: ProposalApplicationEnvelopeV1,
    snapshot: MaterializationAuthoringSnapshotV1,
    *,
    nodes: tuple[CanvasNodeV2, ...],
    bindings: tuple[CanvasBindingV2, ...],
    continuation: ContinuationCommitV2 | None,
) -> AgentActionReceiptV2:
    return AgentActionReceiptV2(
        receipt_id=f"receipt_{envelope.action_turn_id}",
        workflow_id=envelope.workflow_id,
        action_id=envelope.action_turn_id,
        proposal_id=envelope.proposal_id,
        proposal_option_id=envelope.selected_option.option_id,
        proposal_action=envelope.action,
        actor_kind=envelope.selection_actor,
        status="applied",
        summary="The selected concept is now an editable Draft.",
        created_node_ids=tuple(node.node_id for node in nodes),
        created_binding_ids=tuple(binding.binding_id for binding in bindings),
        workflow_revision=snapshot.workflow_revision + 1,
        before_workflow_revision=snapshot.workflow_revision,
        continuation_turn_id=(
            continuation.continuation_turn_id if continuation is not None else None
        ),
        created_at=envelope.created_at,
    )


def _commitments(
    envelope: ProposalApplicationEnvelopeV1,
) -> tuple[AcceptedProposalCommitmentV1, ...]:
    return tuple(
        AcceptedProposalCommitmentV1(
            normalized_meaning=decision[:512],
            source_fragment=decision[:512],
        )
        for decision in envelope.selected_option.key_decisions
    )


def _journey_event(
    envelope: ProposalApplicationEnvelopeV1,
    snapshot: MaterializationAuthoringSnapshotV1,
    *,
    storyboard_draft_preparation_queued: bool,
) -> StageMaterializedJourneyEventV1 | TargetedActionCompletedJourneyEventV1 | None:
    journey = snapshot.current_journey
    if journey.suspended_action is not None:
        if journey.active_action is None:
            return None
        return TargetedActionCompletedJourneyEventV1(
            evidence_id=f"targeted-finish:{envelope.materialization_id}",
            source_id=envelope.materialization_id,
            action_id=journey.active_action.action_id,
            recorded_at=envelope.created_at,
        )
    if envelope.capability_id == "quick_media" or journey.active_action is None:
        return None
    if envelope.operation_kind == "parent" and envelope.capability_id in {
        "product_design",
        "character_design",
    }:
        # Pair completion belongs to the derivative commit, not parent presence.
        return None
    evidence_kind_by_stage = {
        "world_view": "world_view_selected",
        "product": "product_materialized",
        "props": "props_materialized",
        "character": "character_materialized",
        "scene": "scene_materialized",
        "narrative_direction": "narrative_direction_accepted",
        "style_lock": "style_lock_accepted",
        "storyboard_plan": "storyboard_plan_accepted",
        "storyboard_grids": "storyboard_grids_prepared",
        "videos": "videos_prepared",
        "bgm": "bgm_prepared",
    }
    occurrence_id = journey.active_action.occurrence_id
    evidence_kind = evidence_kind_by_stage.get(journey.stage)
    if evidence_kind is None:
        return None
    return StageMaterializedJourneyEventV1.model_validate(
        {
            "evidence_id": f"materialization:{envelope.materialization_id}",
            "evidence_kind": evidence_kind,
            "source_id": envelope.materialization_id,
            "occurrence_id": occurrence_id,
            "storyboard_draft_preparation_queued": storyboard_draft_preparation_queued,
            "recorded_at": envelope.created_at,
        }
    )


def _has_storyboard_draft_preparation_evidence(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    nodes: tuple[CanvasNodeV2, ...],
    preparations: tuple[NodePromptPreparationIntentV1, ...],
    documents: tuple[MaterializationDocumentWriteV1, ...],
) -> bool:
    if envelope.capability_id != "storyboard_design":
        return False
    grid_node_ids = {
        node.node_id
        for node in nodes
        if node.node_type == "image"
        and node.creative_role == "storyboard_sequence"
        and node.status == "draft"
    }
    prepared_node_ids = {item.node_id for item in preparations}
    has_plan = any(
        item.document_type == "agent_working_document"
        and item.payload is not None
        and item.payload.get("kind") == "storyboard_production_plan"
        for item in documents
    )
    return bool(grid_node_ids and grid_node_ids <= prepared_node_ids and has_plan)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
