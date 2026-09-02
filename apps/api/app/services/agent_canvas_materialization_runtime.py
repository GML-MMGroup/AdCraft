"""Bounded Pi execution for one selected capability Materialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from pydantic import BaseModel, ValidationError

from app.persistence.errors import V2PersistenceError
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_materialization import (
    CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS,
    CapabilityMaterializationContextV1,
    CapabilityMaterializationEnvelopeV1,
    CapabilityMaterializationExecutionResultV1,
    ProposalApplicationEnvelopeV1,
)
from app.services.agent_canvas_materialization_normalizer import (
    CapabilityMaterializationNormalizer,
)
from app.services.agent_canvas_references import canonical_node_reference_facts
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


_MAX_CONTEXT_BYTES = 64 * 1024
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "base64",
    "credential",
    "filesystem",
    "local_path",
    "media_bytes",
    "provider_payload",
    "secret",
    "token",
)


class QuickMediaMaterializationGateway(Protocol):
    def run_materialization(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel: ...


class CapabilityMaterializationContextAssembler:
    """Build one capability-local context and reject unsafe payload material."""

    def __init__(
        self,
        *,
        proposal_context: Callable[[str], Mapping[str, object]],
    ) -> None:
        self._proposal_context = proposal_context

    def assemble(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
    ) -> CapabilityMaterializationContextV1:
        raw = dict(self._proposal_context(envelope.proposal_id))
        payload = {
            "workflow_id": envelope.workflow_id,
            "conversation_id": envelope.conversation_id,
            "capability_id": envelope.capability_id,
            "occurrence_id": envelope.occurrence_id,
            "character_phase": envelope.character_phase,
            "requirement_revision_id": envelope.requirement_revision_id,
            "requirement_revision_no": envelope.requirement_revision_no,
            "selected_option": envelope.selected_option,
            "creative_goal": raw.get("creative_goal") or envelope.selected_option.public_summary,
            "explicit_constraints": raw.get("explicit_constraints") or {},
            "shared_summary": raw.get("shared_summary") or "",
            "capability_facts": raw.get("capability_facts") or {},
            "world_setting_excerpt": raw.get("world_setting_excerpt"),
            "reference_summaries": raw.get("reference_summaries") or (),
            "style_projection": raw.get("style_projection") or {},
            "target_node_summary": raw.get("target_node_summary"),
        }
        _reject_unsafe(payload)
        try:
            context = CapabilityMaterializationContextV1.model_validate(payload)
        except ValidationError as error:
            raise _context_error() from error
        if len(context.model_dump_json().encode("utf-8")) > _MAX_CONTEXT_BYTES:
            raise _context_error()
        return context


class QuickMediaMaterializationRunner:
    """Invoke and publish the sole remaining model-assisted Proposal path."""

    def __init__(
        self,
        *,
        gateway: QuickMediaMaterializationGateway,
        context_loader: Callable[
            [CapabilityMaterializationEnvelopeV1], CapabilityMaterializationContextV1
        ],
        publisher: Callable[
            [CapabilityMaterializationEnvelopeV1, BaseModel, Callable[[], None]], str | None
        ],
        normalizer: CapabilityMaterializationNormalizer | None = None,
    ) -> None:
        self._gateway = gateway
        self._context_loader = context_loader
        self._publisher = publisher
        self._normalizer = normalizer or CapabilityMaterializationNormalizer()

    def execute(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
        *,
        lease_guard: Callable[[], None],
    ) -> CapabilityMaterializationExecutionResultV1:
        if envelope.capability_id != "quick_media":
            raise V2PersistenceError(
                "quick_media_materialization_invalid",
                "Only Quick Media uses model-assisted Proposal materialization.",
                stage="quick_media_materialization",
            )
        contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[envelope.capability_id]
        if contract.__name__ != envelope.result_contract_name:
            raise V2PersistenceError(
                "capability_contract_invalid",
                "Materialization result contract conflicts with its immutable envelope.",
                stage="capability_materialization",
            )
        context = self._context_loader(envelope)
        operation = "materialize_quick_media"
        repaired = False
        raw = self._invoke(
            envelope,
            operation,
            context,
            child="initial",
            repair_error=None,
        )
        try:
            result = contract.model_validate(raw)
        except ValidationError:
            repaired = True
            try:
                repaired_raw = self._invoke(
                    envelope,
                    operation,
                    context,
                    child="repair",
                    repair_error="capability_materialization_contract_invalid",
                )
                result = contract.model_validate(repaired_raw)
            except (ValidationError, TypeError, ValueError) as error:
                raise V2PersistenceError(
                    "capability_materialization_contract_invalid",
                    "Materialization output remained invalid after one repair.",
                    stage="capability_materialization",
                ) from error
        normalization = self._normalizer.normalize(
            capability_id=envelope.capability_id,
            result=result,
            context=context,
            repair=(
                None
                if repaired
                else lambda violations: self._invoke(
                    envelope,
                    operation,
                    context,
                    child="semantic-repair",
                    repair_error=",".join(violations),
                )
            ),
        )
        lease_guard()
        node_id = self._publisher(envelope, normalization, lease_guard)
        return CapabilityMaterializationExecutionResultV1(
            materialization_id=envelope.materialization_id,
            node_id=node_id,
            repaired=repaired or normalization.mode == "repaired",
        )

    def _invoke(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
        operation: str,
        context: CapabilityMaterializationContextV1,
        *,
        child: str,
        repair_error: str | None,
    ) -> Mapping[str, object] | BaseModel:
        context_payload = context.model_dump(mode="json", exclude_none=True)
        if repair_error is not None:
            context_payload["repair_error"] = repair_error
        return self._gateway.run_materialization(
            request_identity=f"{envelope.agent_request_identity}:{child}",
            capability_id=envelope.capability_id,
            operation=operation,
            result_contract_name=envelope.result_contract_name,
            context=context_payload,
            repair_error=repair_error,
        )


def _reject_unsafe(value: object, key: str = "") -> None:
    normalized = key.casefold()
    if normalized and any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
        raise _context_error()
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _reject_unsafe(child, str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_unsafe(child)
    elif isinstance(value, str):
        if value.startswith(("/", "\\\\", "data:")):
            raise _context_error()
        try:
            value.encode("utf-8")
        except UnicodeError as error:
            raise _context_error() from error


def _context_error() -> V2PersistenceError:
    return V2PersistenceError(
        "capability_materialization_context_invalid",
        "Materialization context is invalid or exceeds its safe size limit.",
        stage="capability_materialization_context",
    )


def materialization_context_from_state(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    conversations: AgentCanvasConversationRepository,
    workflows: AgentCanvasWorkflowRepository,
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
    validate_references: bool = True,
) -> CapabilityMaterializationContextV1:
    """Project safe current facts for the selected capability only."""

    if validate_references:
        validate_materialization_reference_snapshots(
            envelope,
            workflows=workflows,
            asset_resolver=asset_resolver,
        )

    proposal = conversations.get_private_proposal(envelope.proposal_id)
    session = conversations.get_guidance_session(envelope.workflow_id)
    memory = conversations.get_creative_memory(envelope.workflow_id)
    workflow = workflows.get_workflow(envelope.workflow_id)
    requirement_head = AgentCanvasRequirementRepository(workflows.database).get_current(
        envelope.workflow_id
    )
    requirement_controls = {
        control.control: control.value for control in requirement_head.ledger.hard_controls
    }
    if requirement_head.ledger.identity_safety_decision is not None:
        requirement_controls["identity_safety_decision"] = (
            requirement_head.ledger.identity_safety_decision.model_dump(mode="json")
        )
    bound_reference_ids: dict[str, tuple[str, ...]] = {}
    if envelope.target_node_id is not None:
        for binding in workflow.bindings:
            source_node_id = getattr(binding.source, "source_node_id", None)
            if (
                binding.enabled
                and binding.target_node_id == envelope.target_node_id
                and isinstance(source_node_id, str)
            ):
                bound_reference_ids[source_node_id] = tuple(
                    (*bound_reference_ids.get(source_node_id, ()), binding.binding_id)
                )
    reference_summaries: list[dict[str, object]] = []
    world_excerpt = None
    for reference in envelope.reference_plan.references:
        summary: dict[str, object] = {
            "source_kind": reference.source_kind,
            "source_id": reference.source_id,
            "semantic_reference_role": reference.semantic_reference_role,
            "display_name": reference.display_name,
            "media_type": reference.media_type,
            "required": reference.required,
            "display_order": reference.display_order,
        }
        if reference.source_kind == "node" and validate_references:
            node = workflows.get_node(envelope.workflow_id, reference.source_id)
            summary.update(
                {
                    "node_type": node.node_type,
                    "creative_role": node.creative_role,
                    "title": node.title,
                    "summary_prompt": node.summary_prompt,
                    "revision": node.revision,
                }
            )
            binding_ids = bound_reference_ids.get(reference.source_id, ())
            if binding_ids:
                summary["binding_ids"] = list(binding_ids)
            if node.creative_role == "world_setting":
                content = node.structured_content.get("content")
                if isinstance(content, str):
                    world_excerpt = content[:8_192]
            source_identity_facts = canonical_node_reference_facts(node)
            if source_identity_facts:
                summary["source_identity_facts"] = source_identity_facts
        elif reference.source_kind != "node" and asset_resolver is not None and validate_references:
            asset = asset_resolver(reference.source_id)
            summary.update(
                {
                    "asset_id": getattr(asset, "asset_id", reference.source_id),
                    "display_name": getattr(asset, "display_name", reference.display_name),
                    "media_type": getattr(asset, "media_type", reference.media_type),
                    "status": getattr(asset, "status", None),
                }
            )
        reference_summaries.append(summary)
    style_projection: dict[str, object] = {}
    if proposal.creative_direction_snapshot_id is not None:
        snapshot = conversations.get_creative_direction_snapshot(
            proposal.creative_direction_snapshot_id
        )
        role = (
            VideoAgentOperationRegistry()
            .for_capability(envelope.capability_id)
            .style_projection_role
        )
        candidate = snapshot.role_projections.get(role) if role is not None else None
        if isinstance(candidate, dict):
            style_projection = dict(candidate)
    target_summary = None
    if envelope.target_node_id is not None:
        target = workflows.get_node(envelope.workflow_id, envelope.target_node_id)
        target_summary = {
            "node_id": target.node_id,
            "node_type": target.node_type,
            "creative_role": target.creative_role,
            "title": target.title,
            "summary_prompt": target.summary_prompt,
            "revision": target.revision,
        }
    return CapabilityMaterializationContextAssembler(
        proposal_context=lambda _: {
            "creative_goal": proposal.proposal_purpose or session.goal.summary,
            "explicit_constraints": requirement_controls,
            "shared_summary": "",
            "capability_facts": {
                "approved_node_ids": list(
                    memory.approved_node_ids.get(_creative_role(envelope.capability_id), ())
                ),
            },
            "world_setting_excerpt": world_excerpt,
            "reference_summaries": reference_summaries,
            "style_projection": style_projection,
            "target_node_summary": target_summary,
            "response_locale": session.response_locale,
        }
    ).assemble(envelope)


def validate_materialization_reference_snapshots(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    workflows: AgentCanvasWorkflowRepository,
    asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
) -> None:
    """Reject accepted references that no longer match the frozen source version."""

    for snapshot in envelope.reference_plan.source_snapshots:
        try:
            if snapshot.source_kind == "node":
                current_revision = workflows.get_node(
                    envelope.workflow_id,
                    snapshot.source_id,
                ).revision
                if current_revision != snapshot.source_revision:
                    raise _stale_reference_error()
            else:
                if asset_resolver is None:
                    raise _stale_reference_error()
                current_version_id = asset_resolver(snapshot.source_id).version_id
                if current_version_id != snapshot.asset_version_id:
                    raise _stale_reference_error()
        except V2PersistenceError as error:
            if error.code == "proposal_reference_revision_stale":
                raise
            raise _stale_reference_error() from error


def _creative_role(capability_id: str) -> str:
    return {
        "world_setting": "world_setting",
        "product_design": "product",
        "prop_design": "prop",
        "character_design": "character",
        "scene_design": "scene",
        "script_authoring": "script",
        "storyboard_design": "storyboard_sequence",
        "video_direction": "storyboard_video",
        "bgm_direction": "bgm",
        "quick_media": "general_image",
    }[capability_id]


def _stale_reference_error() -> V2PersistenceError:
    return V2PersistenceError(
        "proposal_reference_revision_stale",
        "An accepted reference changed before Materialization execution.",
        stage="capability_materialization_context",
    )
