"""Build replay-safe, capability-local Video Agent context snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_capabilities import (
    CapabilityContextSnapshotV2,
    CapabilityReferencePlanV1,
    CharacterProposalTargetV1,
    PlannedCapabilityReferenceV1,
)
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_requirements import RequirementLedgerRevisionV1
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_requirement_projection import (
    AgentCanvasRequirementProjectionService,
    requirement_projection_digest,
)
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


def build_capability_context_snapshot(
    *,
    workflow: AgentCanvasWorkflowV2,
    session: GuidedSessionStateV2,
    conversations: AgentCanvasConversationRepository,
    capability_id: CapabilityIdV1,
    objective: str,
    reference_plan: CapabilityReferencePlanV1,
    requirement_revision: RequirementLedgerRevisionV1,
    target_node_id: str | None = None,
    character_target: CharacterProposalTargetV1 | None = None,
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
) -> CapabilityContextSnapshotV2:
    """Freeze only the current capability's approved authoring context."""

    projection = AgentCanvasRequirementProjectionService().project(
        requirement_revision,
        workflow=workflow,
        capability_id=capability_id,
        goal_summary=objective,
        reference_plan=reference_plan,
        target_node_id=target_node_id,
    )
    capability_context: dict[str, object] = {"objective": objective}
    if character_target is not None:
        _validate_character_target(
            character_target,
            capability_id=capability_id,
            requirement_revision=requirement_revision,
        )
        occurrence = next(
            item
            for item in requirement_revision.ledger.character_occurrences
            if item.occurrence_id == character_target.occurrence_id
        )
        capability_context["character_target"] = character_target.model_dump(mode="json")
        capability_context["character_occurrence"] = {
            "occurrence_id": occurrence.occurrence_id,
            "occurrence_index": occurrence.occurrence_index,
            "occurrence_count": character_target.occurrence_count,
            "character_phase": character_target.character_phase,
            "role": occurrence.role,
            "identity_summary": occurrence.identity_summary,
        }
    reference_summaries = _reference_summaries(
        workflow,
        reference_plan.references,
        asset_resolver=asset_resolver,
    )
    if reference_summaries:
        capability_context["reference_summaries"] = reference_summaries
    style_projection = _style_projection(
        workflow.workflow_id,
        session,
        conversations,
        capability_id,
    )
    projection_digest = requirement_projection_digest(projection)
    capability_context_digest = _digest(capability_context)
    style_projection_digest = _digest(style_projection)
    capability_context["audit"] = {
        "requirement_revision_id": projection.ledger_revision_id,
        "requirement_revision_no": projection.ledger_revision_no,
        "requirement_digest": projection.ledger_digest,
        "included_directive_ids": list(projection.included_directive_ids),
        "omitted_directives": [
            item.model_dump(mode="json") for item in projection.omitted_directives
        ],
        "reference_plan_digest": reference_plan.digest,
        "style_projection_digest": style_projection_digest,
        "capability_context_digest": capability_context_digest,
        "projection_digest": projection_digest,
    }
    payload = {
        "workflow_id": workflow.workflow_id,
        "workflow_revision": workflow.revision,
        "session_revision": session.revision,
        "capability_id": capability_id,
        "requirement_projection": projection.model_dump(mode="json"),
        "approved_reference_ids": reference_plan.approved_reference_ids,
        "reference_plan_digest": reference_plan.digest,
        "capability_context": capability_context,
        "style_projection": style_projection,
        "response_locale": session.response_locale,
    }
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CapabilityContextSnapshotV2(
        snapshot_id=f"snapshot_{digest[:32]}",
        digest=digest,
        requirement_projection=projection,
        shared_summary=session.goal.summary,
        approved_reference_ids=reference_plan.approved_reference_ids,
        capability_context=capability_context,
        style_projection=style_projection,
        reference_plan=reference_plan,
        response_locale=session.response_locale,
        character_target=character_target,
    )


def _validate_character_target(
    target: CharacterProposalTargetV1,
    *,
    capability_id: CapabilityIdV1,
    requirement_revision: RequirementLedgerRevisionV1,
) -> None:
    """Ensure a frozen target still belongs to the supplied Ledger revision."""

    if capability_id != "character_design":
        raise V2PersistenceError(
            "character_proposal_scope_invalid",
            "Character proposal scope is not valid for this capability.",
            stage="agent_canvas_capability_context",
        )
    if (
        target.requirement_revision_id != requirement_revision.revision_id
        or target.requirement_revision_no != requirement_revision.revision_no
    ):
        raise V2PersistenceError(
            "character_proposal_scope_invalid",
            "Character proposal target does not match the Requirement Ledger revision.",
            stage="agent_canvas_capability_context",
        )
    occurrence = next(
        (
            item
            for item in requirement_revision.ledger.character_occurrences
            if item.occurrence_id == target.occurrence_id
        ),
        None,
    )
    if occurrence is None or occurrence.occurrence_index != target.occurrence_index:
        raise V2PersistenceError(
            "character_proposal_scope_invalid",
            "Character proposal target does not match the current occurrence.",
            stage="agent_canvas_capability_context",
        )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _reference_summaries(
    workflow: AgentCanvasWorkflowV2,
    references: tuple[PlannedCapabilityReferenceV1, ...],
    *,
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None,
) -> list[dict[str, object]]:
    nodes = {node.node_id: node for node in workflow.nodes}
    summaries: list[dict[str, object]] = []
    for reference in references:
        source_id = reference.source_id
        plan_facts = {
            "input_role": reference.input_role,
            "required": reference.required,
            "semantic_reference_role": reference.semantic_reference_role,
            "display_order": reference.priority,
        }
        node = nodes.get(source_id)
        if node is not None:
            summaries.append(
                {
                    "source_id": node.node_id,
                    "source_kind": "node",
                    "node_type": node.node_type,
                    "creative_role": node.creative_role,
                    "title": node.title,
                    "status": node.status,
                    **plan_facts,
                }
            )
            continue
        if asset_resolver is None:
            summaries.append(
                {
                    "source_id": source_id,
                    "source_kind": "asset",
                    **plan_facts,
                }
            )
            continue
        asset = asset_resolver(source_id)
        summaries.append(
            {
                "source_id": asset.asset_id,
                "source_kind": "asset",
                "display_name": asset.display_name,
                "media_type": asset.media_type,
                "checksum": asset.checksum,
                **plan_facts,
            }
        )
    return summaries


def _style_projection(
    workflow_id: str,
    session: GuidedSessionStateV2,
    conversations: AgentCanvasConversationRepository,
    capability_id: CapabilityIdV1,
) -> dict[str, object]:
    if session.active_style_skill_run_id is None:
        return {}
    snapshot = conversations.get_active_creative_direction_snapshot(workflow_id)
    if snapshot.skill_run_id != session.active_style_skill_run_id:
        raise ValueError("Active Style snapshot does not match the Guidance session.")
    role = VideoAgentOperationRegistry().for_capability(capability_id).style_projection_role
    if role is None:
        return {}
    context = CreativeDirectionService().resolve_style_context(snapshot, role)
    return context.model_dump(mode="json", exclude_none=True)
