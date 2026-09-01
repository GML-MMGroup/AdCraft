"""Classify the authoritative execution lane for one Canvas Node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.agent_canvas import CanvasNodeV2


CanvasExecutionModeV2 = Literal["manual_prompt_direct", "agent_assisted"]
CanvasSemanticExtractionModeV2 = Literal["not_required", "agent"]
CanvasParameterSourceV2 = Literal["manual", "typed_binding", "model_default", "mixed"]


@dataclass(frozen=True, slots=True)
class CanvasExecutionModeDecisionV2:
    """Bounded mode evidence frozen before dispatch."""

    execution_mode: CanvasExecutionModeV2
    semantic_extraction: CanvasSemanticExtractionModeV2


def classify_canvas_execution_mode(node: CanvasNodeV2) -> CanvasExecutionModeDecisionV2:
    """Select direct execution only from persisted manual authoring evidence."""

    direct = (
        node.node_type in {"image", "video"}
        and node.execution_mode == "generative"
        and bool((node.generation_prompt or "").strip())
        and node.prompt_preparation.status == "ready"
        and not has_managed_prompt_preparation(node)
    )
    if direct:
        return CanvasExecutionModeDecisionV2(
            execution_mode="manual_prompt_direct",
            semantic_extraction="not_required",
        )
    return CanvasExecutionModeDecisionV2(
        execution_mode="agent_assisted",
        semantic_extraction="agent",
    )


def has_managed_prompt_preparation(node: CanvasNodeV2) -> bool:
    """Return whether prompt evidence is owned by a preparation authority."""

    preparation = node.prompt_preparation
    return bool(
        preparation.operation_id
        or preparation.presentation_stream_id
        or preparation.context_snapshot_id
        or preparation.occurrence_id
        or preparation.character_phase
        or preparation.role_variant
        or preparation.recipe_id
        or preparation.recipe_version
        or preparation.recipe_digest
        or preparation.requirement_revision_id
        or preparation.requirement_revision_no
        or preparation.document_revisions
        or preparation.binding_digest
        or preparation.style_projection_digest
        or preparation.brief_digest
        or preparation.parameter_origins
        or preparation.compaction_policy_version
        or preparation.compaction_policy_digest
        or preparation.compaction_decisions
        or preparation.assertion_evidence
        or preparation.attempt_stage
        or node.metadata.get("prompt_recipe_id")
    )
