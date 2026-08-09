"""Build replay-safe, capability-local Video Agent context snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_capabilities import CapabilityContextSnapshotV1
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


def build_capability_context_snapshot(
    *,
    workflow: AgentCanvasWorkflowV2,
    session: GuidedSessionStateV2,
    conversations: AgentCanvasConversationRepository,
    capability_id: CapabilityIdV1,
    objective: str,
    approved_reference_ids: tuple[str, ...],
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
) -> CapabilityContextSnapshotV1:
    """Freeze only the current capability's approved authoring context."""

    capability_context: dict[str, object] = {"objective": objective}
    reference_summaries = _reference_summaries(
        workflow,
        approved_reference_ids,
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
    payload = {
        "workflow_id": workflow.workflow_id,
        "workflow_revision": workflow.revision,
        "session_revision": session.revision,
        "capability_id": capability_id,
        "shared_summary": session.goal.summary,
        "approved_reference_ids": approved_reference_ids,
        "capability_context": capability_context,
        "style_projection": style_projection,
    }
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CapabilityContextSnapshotV1(
        snapshot_id=f"snapshot_{digest[:32]}",
        digest=digest,
        shared_summary=session.goal.summary,
        approved_reference_ids=approved_reference_ids,
        capability_context=capability_context,
        style_projection=style_projection,
    )


def _reference_summaries(
    workflow: AgentCanvasWorkflowV2,
    reference_ids: tuple[str, ...],
    *,
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None,
) -> list[dict[str, object]]:
    nodes = {node.node_id: node for node in workflow.nodes}
    summaries: list[dict[str, object]] = []
    for source_id in reference_ids:
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
                }
            )
            continue
        if asset_resolver is None:
            summaries.append({"source_id": source_id, "source_kind": "asset"})
            continue
        asset = asset_resolver(source_id)
        summaries.append(
            {
                "source_id": asset.asset_id,
                "source_kind": "asset",
                "display_name": asset.display_name,
                "media_type": asset.media_type,
                "checksum": asset.checksum,
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
