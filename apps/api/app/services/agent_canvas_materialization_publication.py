"""Deterministic publication of one validated capability Materialization."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, CanvasPositionV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_creative_session import (
    DraftReferenceIntentV2,
    SpecialistDraftV2,
)
from app.schemas.agent_canvas_conversation import ContinuationCommitV2
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationEnvelopeV1,
    QuickMediaMaterializationResultV1,
    WorldSettingMaterializationResultV1,
)
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingDocumentV2,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_conversation import GuidanceProposalActionService
from app.services.agent_canvas_materialization_runtime import (
    validate_materialization_reference_snapshots,
)
from app.services.agent_canvas_world_setting import WorldSettingPublicationCandidateV2


class CapabilityMaterializationPublicationService:
    """Compile platform-owned fields and publish one Materialization exactly once."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        materializer: GuidanceProposalActionService,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._materializer = materializer
        self._asset_resolver = asset_resolver
        self._policy = CapabilityPolicyService()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(
        self,
        envelope: CapabilityMaterializationEnvelopeV1,
        result: BaseModel,
        lease_guard: Callable[[], None],
    ) -> str:
        existing = self._conversations.get_publication_receipt_for_action(envelope.action_turn_id)
        if existing is not None and existing.created_node_ids:
            return existing.created_node_ids[0]
        lease_guard()
        if envelope.target_node_id is not None:
            try:
                target = self._workflows.get_node(
                    envelope.workflow_id,
                    envelope.target_node_id,
                )
            except V2PersistenceError as error:
                raise V2PersistenceError(
                    "proposal_target_revision_stale",
                    "The targeted Node is no longer available.",
                    stage="capability_materialization_publication",
                ) from error
            if target.revision != envelope.target_node_revision:
                raise V2PersistenceError(
                    "proposal_target_revision_stale",
                    "The targeted Node changed before Materialization publication.",
                    stage="capability_materialization_publication",
                )
        validate_materialization_reference_snapshots(
            envelope,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
        )
        definition = self._policy.definition(envelope.capability_id)
        node_id = "node_" + _digest(envelope.materialization_id)[:32]
        continuation = _next_action_continuation(envelope)
        if envelope.capability_id == "world_setting":
            typed = WorldSettingMaterializationResultV1.model_validate(result)
            now = self._clock()
            document = WorldSettingDocumentV2(
                content=typed.structured_content.content,
                core=typed.structured_content.core,
                authoring_provenance=WorldSettingAuthoringProvenanceV2(
                    source_proposal_id=envelope.proposal_id,
                    source_option_id=envelope.selected_option.option_id,
                    materialization_run_id=envelope.materialization_id,
                    style_skill_run_id=envelope.style_skill_run_id,
                    creative_direction_snapshot_id=(
                        self._conversations.get_proposal(
                            envelope.proposal_id
                        ).creative_direction_snapshot_id
                    ),
                ),
            )
            node = CanvasNodeV2(
                node_id=node_id,
                workflow_id=envelope.workflow_id,
                node_type="text",
                creative_role="world_setting",
                title=typed.title,
                status="ready",
                summary_prompt=typed.summary_prompt,
                structured_content=document.model_dump(mode="json"),
                position=CanvasPositionV2(x=0, y=0),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            published = self._materializer.publish_world_setting(
                envelope.proposal_id,
                option_id=envelope.selected_option.option_id,
                candidate=WorldSettingPublicationCandidateV2(
                    node=node,
                    materialization_run_id=envelope.materialization_id,
                ),
                expected_session_revision=envelope.expected_session_revision,
                proposal_action=envelope.action,
                selection_actor=envelope.selection_actor,
                source_turn_id=envelope.action_turn_id,
                continuation=continuation,
                materialization_id=envelope.materialization_id,
            )
            return published.node_id
        if envelope.capability_id == "quick_media":
            quick_media = QuickMediaMaterializationResultV1.model_validate(result)
            node_type = quick_media.structured_content.media_type
            creative_role = {
                "image": "general_image",
                "video": "general_video",
                "audio": "general_audio",
            }[node_type]
        else:
            if definition.node_type is None or definition.creative_role is None:
                raise V2PersistenceError(
                    "capability_policy_invalid",
                    "Capability does not define a publishable Node role.",
                    stage="capability_materialization_publication",
                )
            node_type = definition.node_type
            creative_role = definition.creative_role
        structured = getattr(result, "structured_content")
        parameters = _compile_parameters(
            capability_id=envelope.capability_id,
            structured=structured,
            explicit_constraints=self._conversations.get_guidance_session(
                envelope.workflow_id
            ).goal.explicit_constraints,
        )
        references = tuple(
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
        draft = SpecialistDraftV2(
            title=str(getattr(result, "title")),
            node_type=node_type,
            creative_role=creative_role,
            summary_prompt=str(getattr(result, "summary_prompt")),
            generation_prompt=getattr(result, "generation_prompt", None),
            structured_content=structured.model_dump(mode="json"),
            parameters=parameters,
            reference_intents=references,
        )
        lease_guard()
        node = self._materializer.materialize(
            envelope.proposal_id,
            option_id=envelope.selected_option.option_id,
            draft=draft,
            expected_session_revision=envelope.expected_session_revision,
            proposal_action=envelope.action,
            selection_actor=envelope.selection_actor,
            source_turn_id=envelope.action_turn_id,
            continuation=continuation,
            deterministic_node_id=node_id,
            deterministic_binding_id=lambda index: (
                "binding_" + _digest(f"{envelope.materialization_id}:{index}")[:32]
            ),
            materialization_id=envelope.materialization_id,
        )
        return node.node_id


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _compile_parameters(
    *,
    capability_id: str,
    structured: BaseModel,
    explicit_constraints: dict[str, object],
) -> dict[str, object]:
    parameters: dict[str, object] = {}
    duration = getattr(structured, "duration_seconds", None)
    if duration is not None:
        parameters["duration_seconds"] = duration
    if capability_id != "video_direction":
        return parameters

    required_video_parameters = explicit_constraints.get("required_video_parameters")
    if not isinstance(required_video_parameters, dict):
        required_video_parameters = {}

    def requested_parameter(name: str) -> object:
        return explicit_constraints.get(name, required_video_parameters.get(name))

    duration = requested_parameter("duration_seconds")
    if (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and 0 < duration <= 3_600
    ):
        parameters["duration_seconds"] = duration
    aspect_ratio = requested_parameter("aspect_ratio")
    if isinstance(aspect_ratio, str) and aspect_ratio.strip():
        parameters["aspect_ratio"] = aspect_ratio.strip()
    resolution = requested_parameter("resolution")
    if isinstance(resolution, str) and resolution.strip():
        parameters["resolution"] = resolution.strip()
    generate_audio = requested_parameter("generate_audio")
    if isinstance(generate_audio, bool):
        parameters["generate_audio"] = generate_audio
    return parameters


def _next_action_continuation(
    envelope: CapabilityMaterializationEnvelopeV1,
) -> ContinuationCommitV2:
    digest = _digest(f"materialization-next-action:{envelope.materialization_id}")
    return ContinuationCommitV2(
        continuation_id=f"continuation_{digest[:24]}",
        continuation_turn_id=f"turn_{digest[24:56]}",
        source_turn_id=envelope.action_turn_id,
        source_action_id=envelope.action_turn_id,
        idempotency_key=f"materialization-next-action:{envelope.materialization_id}",
        video_skill_run_id=envelope.style_skill_run_id,
    )
