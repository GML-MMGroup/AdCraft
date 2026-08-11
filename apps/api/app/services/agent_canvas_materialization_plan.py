"""Pure compilation of validated capability output into one commit plan."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from app.schemas.agent_canvas import (
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_conversation import AgentActionReceiptV2, ContinuationCommitV2
from app.schemas.agent_canvas_creative_session import DraftReferenceIntentV2, SpecialistDraftV2
from app.schemas.agent_canvas_draft_seeds import AcceptedProposalCommitmentV1
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    MaterializationNormalizationV1,
    ProposalApplicationEnvelopeV1,
    QuickMediaMaterializationResultV1,
    WorldSettingMaterializationResultV1,
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
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingDocumentV2,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_character_reference_pairs import CharacterReferencePairFactory
from app.services.agent_canvas_stage_authoring import FoundationDraftPublicationService
from app.services.agent_canvas_world_setting import WorldSettingBindingPolicy


_PROVENANCE_KEYS = {
    "materialization_mode",
    "warning_code",
    "operation_policy_id",
    "normalization_mode",
    "normalization_warnings",
    "character_pair_id",
    "character_asset_kind",
    "source_agent_document_id",
    "source_sequence_id",
}


class CapabilityMaterializationPlanCompiler:
    """Compile one immutable plan without I/O, clocks, or external execution."""

    def compile(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
        *,
        snapshot: MaterializationAuthoringSnapshotV1,
        storyboard_documents: tuple[MaterializationDocumentWriteV1, ...] = (),
    ) -> MaterializationPlanV1:
        if isinstance(normalization, CapabilityMaterializationContextV1):
            nodes, bindings, preparations = self._progressive_nodes(
                envelope,
                normalization,
            )
        else:
            nodes, bindings, preparations = self._normalized_nodes(
                envelope,
                normalization,
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
            "action_turn_id": envelope.action_turn_id,
            "proposal_action": envelope.action,
            "selection_actor": envelope.selection_actor,
            "expected_workflow_revision": snapshot.workflow_revision,
            "expected_session_revision": snapshot.session_revision,
            "expected_proposal_revision": snapshot.proposal_revision,
            "expected_target_node_revision": snapshot.target_node_revision,
            "nodes": nodes,
            "bindings": bindings,
            "document_writes": storyboard_documents,
            "requirement_commitments": _commitments(envelope),
            "receipt": receipt,
            "continuation": continuation,
            "prompt_preparations": preparations,
            "journey_event": _journey_event(envelope, snapshot),
            "payload_digest": "0" * 64,
        }
        provisional = MaterializationPlanV1.model_construct(**payload)
        payload["payload_digest"] = materialization_plan_digest(provisional)
        return MaterializationPlanV1.model_validate(payload)

    @staticmethod
    def _progressive_nodes(
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
    ) -> tuple[
        tuple[CanvasNodeV2, ...],
        tuple[CanvasBindingV2, ...],
        tuple[NodePromptPreparationIntentV1, ...],
    ]:
        foundation = FoundationDraftPublicationService().build(
            envelope,
            context,
            now=envelope.created_at,
        )
        nodes, external_bindings, preparations = _draft_nodes(
            envelope,
            foundation.drafts,
            foundation.node_ids,
        )
        return (
            nodes,
            (*external_bindings, *foundation.internal_bindings),
            preparations,
        )

    @staticmethod
    def _normalized_nodes(
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1,
    ) -> tuple[
        tuple[CanvasNodeV2, ...],
        tuple[CanvasBindingV2, ...],
        tuple[NodePromptPreparationIntentV1, ...],
    ]:
        result = normalization.result
        if envelope.capability_id == "world_setting":
            return (_world_setting_node(envelope, result),), (), ()

        if envelope.capability_id == "character_design":
            pair = CharacterReferencePairFactory().build(
                envelope=envelope,
                normalization=normalization,
            )
            nodes, bindings, preparations = _draft_nodes(
                envelope,
                (pair.main_draft, pair.turnaround_draft),
                (pair.main_node_id, pair.turnaround_node_id),
            )
            return nodes, (*bindings, pair.internal_binding), preparations

        if envelope.capability_id == "quick_media":
            quick = QuickMediaMaterializationResultV1.model_validate(result)
            node_type = quick.structured_content.media_type
            creative_role = {
                "image": "general_image",
                "video": "general_video",
                "audio": "general_audio",
            }[node_type]
        else:
            definition = CapabilityPolicyService().definition(envelope.capability_id)
            if definition.node_type is None or definition.creative_role is None:
                raise ValueError("capability_policy_invalid")
            node_type = definition.node_type
            creative_role = definition.creative_role

        structured_content = getattr(result, "structured_content")
        draft = SpecialistDraftV2(
            title=str(getattr(result, "title")),
            node_type=node_type,
            creative_role=creative_role,
            summary_prompt=str(getattr(result, "summary_prompt")),
            generation_prompt=getattr(result, "generation_prompt", None),
            structured_content=_model_payload(structured_content),
            parameters={
                **normalization.parameters,
                "normalization_mode": normalization.mode,
                "normalization_warnings": list(normalization.warnings),
            },
            parameter_provenance=normalization.parameter_provenance,
            prompt_context_snapshot_id=envelope.context_snapshot_id,
            reference_intents=_reference_intents(envelope),
        )
        node_id = f"node_{_digest(envelope.materialization_id)[:32]}"
        return _draft_nodes(envelope, (draft,), (node_id,))


def _draft_nodes(
    envelope: ProposalApplicationEnvelopeV1,
    drafts: tuple[Any, ...],
    node_ids: tuple[str, ...],
) -> tuple[
    tuple[CanvasNodeV2, ...],
    tuple[CanvasBindingV2, ...],
    tuple[NodePromptPreparationIntentV1, ...],
]:
    nodes: list[CanvasNodeV2] = []
    preparations: list[NodePromptPreparationIntentV1] = []
    for node_id, draft in zip(node_ids, drafts, strict=True):
        operation_id = f"prompt_{_digest(f'{envelope.materialization_id}:{node_id}')[:32]}"
        provenance = {
            key: value for key, value in draft.parameters.items() if key in _PROVENANCE_KEYS
        }
        if draft.prompt_context_snapshot_id is not None:
            provenance["materialization_context_snapshot_id"] = draft.prompt_context_snapshot_id
        nodes.append(
            CanvasNodeV2(
                node_id=node_id,
                workflow_id=envelope.workflow_id,
                node_type=draft.node_type,
                creative_role=draft.creative_role,
                title=draft.title,
                status="draft",
                summary_prompt=draft.summary_prompt,
                generation_prompt=None,
                structured_content=_model_payload(draft.structured_content),
                parameters={
                    key: value
                    for key, value in draft.parameters.items()
                    if key not in _PROVENANCE_KEYS
                },
                metadata=provenance,
                parameter_provenance=draft.parameter_provenance,
                prompt_context_snapshot_id=(
                    "snapshot_"
                    + _digest(f"{envelope.materialization_id}:{node_id}:prompt-context")[:32]
                ),
                position=CanvasPositionV2(x=0, y=0),
                revision=1,
                prompt_preparation=NodePromptPreparationV1(
                    status="queued",
                    operation_id=operation_id,
                    attempt_no=0,
                    context_snapshot_id=envelope.context_snapshot_id,
                    updated_at=envelope.created_at,
                ),
                created_at=envelope.created_at,
                updated_at=envelope.created_at,
            )
        )
        preparations.append(
            NodePromptPreparationIntentV1(
                operation_id=operation_id,
                node_id=node_id,
                context_snapshot_id=envelope.context_snapshot_id,
            )
        )

    bindings: list[CanvasBindingV2] = []
    for node, draft in zip(nodes, drafts, strict=True):
        for intent in sorted(draft.reference_intents, key=lambda item: item.display_order):
            source = (
                CanvasBindingSourceNodeV2(source_node_id=intent.source_id)
                if intent.source_kind == "node"
                else CanvasBindingSourceImageAssetV2(source_asset_id=intent.source_id)
            )
            metadata = (
                WorldSettingBindingPolicy().metadata_for_target(node.creative_role)
                if intent.semantic_reference_role == "world_setting_reference"
                else (
                    {"semantic_reference_role": intent.semantic_reference_role}
                    if intent.semantic_reference_role is not None
                    else {}
                )
            )
            binding_index = len(bindings)
            bindings.append(
                CanvasBindingV2(
                    binding_id=(
                        "binding_"
                        + _digest(f"{envelope.materialization_id}:reference:{binding_index}")[:32]
                    ),
                    workflow_id=envelope.workflow_id,
                    source=source,
                    target_node_id=node.node_id,
                    input_role=intent.input_role,
                    required=intent.required,
                    enabled=True,
                    order=intent.display_order,
                    metadata=metadata,
                    created_at=envelope.created_at,
                    updated_at=envelope.created_at,
                )
            )
    return tuple(nodes), tuple(bindings), tuple(preparations)


def _world_setting_node(
    envelope: ProposalApplicationEnvelopeV1,
    value: Any,
) -> CanvasNodeV2:
    result = WorldSettingMaterializationResultV1.model_validate(value)
    document = WorldSettingDocumentV2(
        content=result.structured_content.content,
        core=result.structured_content.core,
        authoring_provenance=WorldSettingAuthoringProvenanceV2(
            source_proposal_id=envelope.proposal_id,
            source_option_id=envelope.selected_option.option_id,
            materialization_run_id=envelope.materialization_id,
            style_skill_run_id=envelope.style_skill_run_id,
            creative_direction_snapshot_id=None,
        ),
    )
    digest = _digest(result.summary_prompt)
    return CanvasNodeV2(
        node_id=f"node_{_digest(envelope.materialization_id)[:32]}",
        workflow_id=envelope.workflow_id,
        node_type="text",
        creative_role="world_setting",
        title=result.title,
        status="ready",
        summary_prompt=result.summary_prompt,
        structured_content=document.model_dump(mode="json"),
        position=CanvasPositionV2(x=0, y=0),
        revision=1,
        prompt_preparation=NodePromptPreparationV1(
            status="ready",
            operation_id=None,
            attempt_no=0,
            context_snapshot_id=envelope.context_snapshot_id,
            prompt_digest=digest,
            updated_at=envelope.created_at,
        ),
        created_at=envelope.created_at,
        updated_at=envelope.created_at,
    )


def _reference_intents(
    envelope: ProposalApplicationEnvelopeV1,
) -> tuple[DraftReferenceIntentV2, ...]:
    return tuple(
        DraftReferenceIntentV2.model_validate(
            reference.model_dump(
                include={
                    "source_kind",
                    "source_id",
                    "binding_kind",
                    "input_role",
                    "required",
                    "display_order",
                    "semantic_reference_role",
                }
            )
        )
        for reference in envelope.reference_plan.references
    )


def _continuation(
    envelope: ProposalApplicationEnvelopeV1,
    snapshot: MaterializationAuthoringSnapshotV1,
) -> ContinuationCommitV2 | None:
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
) -> StageMaterializedJourneyEventV1 | TargetedActionCompletedJourneyEventV1 | None:
    journey = snapshot.current_journey
    if journey.suspended_action is not None:
        return TargetedActionCompletedJourneyEventV1(
            evidence_id=f"targeted-finish:{envelope.materialization_id}",
            source_id=envelope.materialization_id,
            action_id=journey.suspended_action.action_id,
            recorded_at=envelope.created_at,
        )
    if envelope.capability_id == "quick_media" or journey.active_action is None:
        return None
    evidence_kind_by_stage = {
        "world_setting": "world_setting_selected",
        "narrative_direction": "narrative_direction_selected",
        "storyboard_plan": "storyboard_plan_accepted",
        "storyboard_grids": "storyboard_grids_prepared",
        "video_segments": "video_segments_prepared",
        "bgm": "bgm_prepared",
    }
    foundation_item_id = None
    if journey.stage == "foundation_design":
        evidence_kind = "foundation_item_selected"
        foundation_item_id = journey.active_action.foundation_item_id
    else:
        evidence_kind = evidence_kind_by_stage.get(journey.stage)
    if evidence_kind is None:
        return None
    return StageMaterializedJourneyEventV1.model_validate(
        {
            "evidence_id": f"materialization:{envelope.materialization_id}",
            "evidence_kind": evidence_kind,
            "source_id": envelope.materialization_id,
            "foundation_item_id": foundation_item_id,
            "recorded_at": envelope.created_at,
        }
    )


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
