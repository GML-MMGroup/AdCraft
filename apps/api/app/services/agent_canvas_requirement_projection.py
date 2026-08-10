"""Deterministic, capability-scoped Requirement Ledger projections."""

from __future__ import annotations

import json

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceNodeV2,
    CanvasNodeV2,
)
from app.schemas.agent_canvas_capabilities import CapabilityReferencePlanV1
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_requirements import (
    CapabilityRequirementProjectionV1,
    OmittedRequirementDirectiveV1,
    RequirementDirectiveV1,
    RequirementLedgerRevisionV1,
)


_DIRECTIVE_BUDGET = 24 * 1024
_DIRECT_TEXT_BUDGET = 32 * 1024

_CONTROL_VISIBILITY: dict[CapabilityIdV1, frozenset[str]] = {
    "world_setting": frozenset(),
    "product_design": frozenset({"product_count"}),
    "prop_design": frozenset({"prop_count"}),
    "character_design": frozenset({"character_count"}),
    "scene_design": frozenset({"scene_count"}),
    "script_authoring": frozenset(
        {"duration_seconds", "spoken_language", "audio_mode", "product_count"}
    ),
    "storyboard_design": frozenset(
        {
            "duration_seconds",
            "aspect_ratio",
            "output_resolution",
            "frame_rate",
            "storyboard_sequence_count",
        }
    ),
    "video_direction": frozenset(
        {
            "duration_seconds",
            "aspect_ratio",
            "output_resolution",
            "frame_rate",
            "spoken_language",
            "audio_mode",
            "video_segment_count",
        }
    ),
    "bgm_direction": frozenset({"duration_seconds", "audio_mode"}),
    "quick_media": frozenset(
        {
            "duration_seconds",
            "aspect_ratio",
            "output_resolution",
            "frame_rate",
            "spoken_language",
            "audio_mode",
            "product_count",
            "prop_count",
            "character_count",
            "scene_count",
            "storyboard_sequence_count",
            "video_segment_count",
        }
    ),
}

_SOURCE_PRIORITY = {"user_message": 0, "manual_edit": 0, "accepted_proposal": 1}
_SCOPE_PRIORITY = {"node": 0, "capability": 1, "global": 2}


class AgentCanvasRequirementProjectionService:
    """Project immutable Requirement state without hidden topology expansion."""

    def project(
        self,
        revision: RequirementLedgerRevisionV1,
        *,
        workflow: AgentCanvasWorkflowV2,
        capability_id: CapabilityIdV1,
        goal_summary: str,
        reference_plan: CapabilityReferencePlanV1,
        target_node_id: str | None = None,
    ) -> CapabilityRequirementProjectionV1:
        if revision.workflow_id != workflow.workflow_id:
            raise ValueError("Requirement revision and Workflow must share an identity.")
        if reference_plan.capability_id != capability_id:
            raise ValueError("Reference plan and projection capability must match.")

        direct_node_ids = _direct_node_ids(
            workflow,
            reference_plan=reference_plan,
            target_node_id=target_node_id,
        )
        applicable = [
            item
            for item in revision.ledger.active_directives
            if _directive_is_visible(
                item,
                capability_id=capability_id,
                target_node_id=target_node_id,
                direct_node_ids=direct_node_ids,
            )
        ]
        applicable.sort(key=_directive_sort_key)
        included, omitted = _bounded_directives(applicable)
        controls = tuple(
            item
            for item in revision.ledger.hard_controls
            if item.control in _CONTROL_VISIBILITY[capability_id]
        )
        controls = tuple(sorted(controls, key=lambda item: item.control))
        direct_text_inputs, text_warnings = _direct_text_inputs(
            workflow,
            direct_node_ids,
        )
        element_summaries = tuple(
            f"{item.element_kind}: {item.presence}"
            for item in sorted(
                revision.ledger.element_presence,
                key=lambda item: item.element_kind,
            )
        )
        return CapabilityRequirementProjectionV1(
            ledger_revision_id=revision.revision_id,
            ledger_revision_no=revision.revision_no,
            ledger_digest=revision.digest,
            capability_id=capability_id,
            goal_summary=_bounded_text(goal_summary, 4 * 1024),
            hard_controls=controls,
            relevant_directives=included,
            accepted_element_summaries=element_summaries,
            direct_text_inputs=direct_text_inputs,
            warnings=text_warnings,
            included_directive_ids=tuple(item.directive_id for item in included),
            omitted_directives=omitted,
        )


def requirement_projection_digest(projection: CapabilityRequirementProjectionV1) -> str:
    import hashlib

    return hashlib.sha256(_canonical_bytes(projection.model_dump(mode="json"))).hexdigest()


def _directive_is_visible(
    directive: RequirementDirectiveV1,
    *,
    capability_id: CapabilityIdV1,
    target_node_id: str | None,
    direct_node_ids: frozenset[str],
) -> bool:
    if directive.scope_kind == "global":
        return True
    if directive.scope_kind == "capability":
        return capability_id in directive.capability_ids
    visible_nodes = set(direct_node_ids)
    if target_node_id is not None:
        visible_nodes.add(target_node_id)
    return bool(visible_nodes.intersection(directive.target_node_ids))


def _directive_sort_key(
    directive: RequirementDirectiveV1,
) -> tuple[int, int, int, int, str]:
    return (
        0 if directive.strength == "hard" else 1,
        _SCOPE_PRIORITY[directive.scope_kind],
        _SOURCE_PRIORITY[directive.source_kind],
        -directive.created_revision_no,
        directive.directive_id,
    )


def _bounded_directives(
    directives: list[RequirementDirectiveV1],
) -> tuple[
    tuple[RequirementDirectiveV1, ...],
    tuple[OmittedRequirementDirectiveV1, ...],
]:
    hard = [item for item in directives if item.strength == "hard"]
    if len(_canonical_bytes([item.model_dump(mode="json") for item in hard])) > _DIRECTIVE_BUDGET:
        raise V2PersistenceError(
            "requirement_projection_budget_exceeded",
            "Hard Requirement directives exceed the capability projection budget.",
            stage="agent_canvas_requirement_projection",
        )
    included = list(hard)
    omitted: list[OmittedRequirementDirectiveV1] = []
    for directive in (item for item in directives if item.strength == "preference"):
        candidate = [*included, directive]
        if (
            len(_canonical_bytes([item.model_dump(mode="json") for item in candidate]))
            <= _DIRECTIVE_BUDGET
        ):
            included.append(directive)
        else:
            omitted.append(
                OmittedRequirementDirectiveV1(
                    directive_id=directive.directive_id,
                    reason="section_byte_budget",
                )
            )
    return tuple(included), tuple(omitted)


def _direct_node_ids(
    workflow: AgentCanvasWorkflowV2,
    *,
    reference_plan: CapabilityReferencePlanV1,
    target_node_id: str | None,
) -> frozenset[str]:
    direct = {item.source_id for item in reference_plan.references if item.source_kind == "node"}
    if target_node_id is not None:
        direct.update(
            binding.source.source_node_id
            for binding in workflow.bindings
            if binding.enabled
            and binding.target_node_id == target_node_id
            and isinstance(binding.source, CanvasBindingSourceNodeV2)
        )
    return frozenset(direct)


def _direct_text_inputs(
    workflow: AgentCanvasWorkflowV2,
    direct_node_ids: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    nodes = {node.node_id: node for node in workflow.nodes}
    included: list[str] = []
    warnings: list[str] = []
    for node_id in sorted(direct_node_ids):
        node = nodes.get(node_id)
        if node is None or node.node_type not in {"text", "script"}:
            continue
        content = _saved_text_content(node)
        if not content:
            continue
        candidate = [*included, content]
        if len(_canonical_bytes(candidate)) <= _DIRECT_TEXT_BUDGET:
            included.append(content)
        else:
            warnings.append(f"direct_text_input_omitted:{node_id}:section_byte_budget")
    return tuple(included), tuple(warnings)


def _saved_text_content(node: CanvasNodeV2) -> str:
    content = node.structured_content.get("content")
    if isinstance(content, str):
        return content
    if node.structured_content:
        return json.dumps(
            node.structured_content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return ""


def _bounded_text(value: str, byte_limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value
    return encoded[:byte_limit].decode("utf-8", errors="ignore")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
