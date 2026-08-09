"""Director-owned Agent Canvas conversation and proposal orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Literal, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.event_repository import EventRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasConnectionDecisionV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_conversation import (
    AgentActionReceiptV2,
    ChatTimelineListResponseV2,
    ChatTurnAcceptedV2,
    ChatTurnV2,
    ConceptOptionRecordV2,
    ConceptProposalCreateV2,
    ContinuationCommitV2,
    ProposalActionRequestV2,
)
from app.schemas.agent_canvas_capabilities import (
    CAPABILITY_RESULT_CONTRACTS,
    CapabilityInvocationContextV1,
    NextActionCommandV1,
    NextActionContextV1,
    TurnIntentContextV1,
    TurnIntentDecisionV1,
)
from app.schemas.agent_canvas_capability_identity import CAPABILITY_DISPLAY_NAMES
from app.schemas.agent_canvas_materialization import (
    CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS,
    CapabilityMaterializationContextV1,
)
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    CreativeGoalV2,
    DraftReferenceIntentV2,
    GuidanceCompletionProjectionV2,
    GuidanceSessionActionV2,
    SpecialistDraftV2,
    StyleGuidanceContextV2,
)
from app.schemas.agent_operation_contexts import (
    AgentCommandReplanContextV2,
)
from app.schemas.agent_runtime import (
    AgentCommandPlanDraftV2,
    AgentRunPolicy,
    AgentRunRequest,
    AgentRunCompletedPayload,
)
from app.schemas.agent_working_documents import AgentDocumentContextExcerptV2
from app.services.durable_pi_run import DurablePiRunResult, DurablePiRunService
from app.services.model_resolution import ModelResolutionService
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.pi_agent_runtime_client import PiAgentRuntimeError
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_command_compiler import (
    AgentCommandPlanCompiler,
)
from app.services.agent_canvas_commands import AgentCanvasCommandService
from app.services.agent_canvas_context import AgentLocalContextAssembler
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_capability_dispatch import CapabilityDispatchService
from app.services.agent_canvas_capability_context import (
    build_capability_context_snapshot,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_next_action import NextActionExecutionService
from app.services.agent_canvas_next_action_context import (
    assemble_capability_policy_context,
)
from app.services.agent_canvas_next_action_dispatch import NextActionDispatchService
from app.services.agent_canvas_materialization_submission import (
    ProposalMaterializationSubmissionService,
)
from app.services.agent_canvas_turn_intent import TurnIntentService
from app.services.agent_canvas_ad_media import AdMediaDraftValidationService
from app.services.agent_canvas_video_skills import VideoSkillRegistry
from app.services.agent_canvas_world_setting import (
    WorldSettingBindingPolicy,
    WorldSettingPublicationCandidateV2,
)
from app.services.agent_operation_policy import AgentOperationPolicyRegistryV2


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PiStructuredRunResult:
    """One validated terminal structured result with private audit identity."""

    value: dict[str, object]
    run_id: str
    audit: dict[str, object]
    model_ref: str


class VideoAgentGateway(Protocol):
    def classify_turn_intent(
        self, context: TurnIntentContextV1, *, turn_id: str
    ) -> TurnIntentDecisionV1: ...

    def choose_next_action(
        self, context: NextActionContextV1, *, turn_id: str
    ) -> NextActionCommandV1: ...

    def run_capability(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        candidate_count: int,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel: ...

    def run_materialization(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel: ...


class DeterministicVideoAgentGateway:
    """Test/offline gateway that never performs semantic keyword routing."""

    def classify_turn_intent(
        self,
        context: TurnIntentContextV1,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV1:
        return TurnIntentDecisionV1(
            mode="ordinary_conversation",
            objective=context.user_input,
            assistant_message=f"Your request is recorded for this canvas: {context.user_input}",
        )

    def choose_next_action(
        self,
        context: NextActionContextV1,
        *,
        turn_id: str,
    ) -> NextActionCommandV1:
        return NextActionCommandV1(
            action="reply",
            message="No deterministic creative capability was requested.",
        )

    def run_capability(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        candidate_count: int,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel:
        contract = CAPABILITY_RESULT_CONTRACTS[capability_id]
        return contract.model_validate(
            _deterministic_capability_result(capability_id, candidate_count)
        )

    def run_materialization(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel:
        contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[capability_id]
        return contract.model_validate(_deterministic_materialization_result(capability_id))


class PiVideoAgentGateway:
    """Boundary for the private single-identity Video Agent runtime."""

    def __init__(
        self,
        durable_runner: DurablePiRunService,
        *,
        timeout_seconds: float,
        model_resolution: ModelResolutionService,
        operation_policies: AgentOperationPolicyRegistryV2 | None = None,
    ) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds
        self._model_resolution = model_resolution
        self._operation_policies = operation_policies or AgentOperationPolicyRegistryV2()

    def classify_turn_intent(
        self,
        context: TurnIntentContextV1,
        *,
        turn_id: str,
    ) -> TurnIntentDecisionV1:
        value, _ = self._run(
            operation="decide_turn_intent",
            context=context,
            contract=TurnIntentDecisionV1,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "turn_id": turn_id,
                "agent_name": "video_agent",
                "operation": "decide_turn_intent",
            },
        )
        return TurnIntentDecisionV1.model_validate(value)

    def choose_next_action(
        self,
        context: NextActionContextV1,
        *,
        turn_id: str,
    ) -> NextActionCommandV1:
        value, _ = self._run(
            operation="decide_next_action",
            context=context,
            contract=NextActionCommandV1,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "turn_id": turn_id,
                "agent_name": "video_agent",
                "operation": "decide_next_action",
            },
        )
        return NextActionCommandV1.model_validate(value)

    def run_capability(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        candidate_count: int,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel:
        contract = CAPABILITY_RESULT_CONTRACTS[capability_id]
        invocation = CapabilityInvocationContextV1.model_validate(
            {
                **context,
                "context_kind": "capability_operation",
                "capability_id": capability_id,
                "repair_error": repair_error,
            }
        )
        completed = self._run_structured(
            operation=operation,
            context=invocation,
            contract=contract,
            identity_fields={
                "agent_request_identity": request_identity,
                "capability_id": capability_id,
                "result_contract_name": result_contract_name,
                "candidate_count": candidate_count,
            },
        )
        return contract.model_validate(completed.value)

    def run_materialization(
        self,
        *,
        request_identity: str,
        capability_id: str,
        operation: str,
        result_contract_name: str,
        context: Mapping[str, object],
        repair_error: str | None,
    ) -> BaseModel:
        contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[capability_id]
        invocation = CapabilityMaterializationContextV1.model_validate(context)
        completed = self._run_structured(
            operation=operation,
            context=invocation,
            contract=contract,
            identity_fields={
                "agent_request_identity": request_identity,
                "capability_id": capability_id,
                "result_contract_name": result_contract_name,
                "repair_error": repair_error or "none",
            },
        )
        return contract.model_validate(completed.value)

    def replan(
        self,
        context: AgentCommandReplanContextV2,
    ) -> AgentCommandPlanDraftV2:
        value, _ = self._run(
            operation="command_replan",
            context=context,
            contract=AgentCommandPlanDraftV2,
            identity_fields={
                "workflow_id": context.workflow_id,
                "conversation_id": context.conversation_id,
                "workflow_revision": context.workflow_revision,
                "conflict_code": context.conflict_code,
                "agent_name": "video_agent",
                "operation": "command_replan",
            },
        )
        return AgentCommandPlanDraftV2.model_validate(value)

    def _run(
        self,
        *,
        operation: str,
        context: (TurnIntentContextV1 | NextActionContextV1 | AgentCommandReplanContextV2),
        contract,
        identity_fields: dict[str, str | int],
        parent_run_id: str | None = None,
    ) -> tuple[dict[str, object], str]:
        completed = self._run_structured(
            operation=operation,
            context=context,
            contract=contract,
            identity_fields=identity_fields,
            parent_run_id=parent_run_id,
        )
        return completed.value, completed.run_id

    def _run_structured(
        self,
        *,
        operation: str,
        context: BaseModel,
        contract,
        identity_fields: dict[str, str | int],
        parent_run_id: str | None = None,
    ) -> PiStructuredRunResult:
        resolution = self._model_resolution.resolve_selection(
            node_type="script",
            model_selection_mode="default",
            model_ref=None,
        )
        operation_policy = self._operation_policies.resolve(
            agent_name="video_agent",
            operation=operation,
            contract_id=contract.__name__,
        )
        operation_timeout = float(operation_policy.hard_deadline_seconds)
        style_lineage = _style_skill_lineage(context)
        request = AgentRunRequest(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            **agent_run_envelope_fields(context),
            parent_run_id=parent_run_id,
            agent_name="video_agent",
            operation=operation,
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=operation_timeout),
            model_policy_id=f"video_agent.{operation}.v1",
            model_ref=resolution.model_ref,
            context=context,
            policy=AgentRunPolicy(
                operation_policy_id=operation_policy.policy_id,
                operation_class=operation_policy.policy_class,
                transport_retry_limit=operation_policy.transport_retry_limit,
                structured_repair_limit=operation_policy.structured_repair_limit,
                max_handoffs=0,
                timeout_seconds=operation_timeout,
            ),
            contract_name=contract.__name__,
            contract_schema=contract.model_json_schema(),
            audit_metadata={
                "tool_mode": "structured_only",
                "agent_operation_policy": operation_policy.model_dump(mode="json"),
                "model_identity": {
                    "model_ref": resolution.model_ref,
                    "provider_id": resolution.provider_id,
                    "provider_model_id": resolution.provider_model_id,
                    "capability": resolution.capability,
                    "provider_protocol": resolution.provider_protocol,
                    "catalog_revision": resolution.catalog_revision,
                    "provider_revision": resolution.credential_revision,
                },
                **({"style_skill_lineage": style_lineage} if style_lineage is not None else {}),
            },
        )
        result = self._durable_runner.run(
            request,
            identity_fields=identity_fields,
            model_ref=resolution.model_ref,
        )
        return _completed_structured_run(result, model_ref=resolution.model_ref)


def _completed_structured_run(
    result: DurablePiRunResult,
    *,
    model_ref: str,
) -> PiStructuredRunResult:
    completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
    return PiStructuredRunResult(
        value=completed.value,
        run_id=result.run_id,
        audit=completed.audit,
        model_ref=model_ref,
    )


def _deterministic_capability_result(
    capability_id: str,
    candidate_count: int,
) -> dict[str, object]:
    count = max(2, candidate_count) if capability_id == "world_setting" else candidate_count
    options: list[dict[str, object]] = []
    for index in range(1, count + 1):
        summary = f"Deterministic {capability_id} option {index}."
        options.append(
            {
                "title": f"Option {index}",
                "public_summary": summary,
                "key_decisions": [
                    f"Keep the {capability_id} direction coherent.",
                    f"Use option {index} as the selected creative premise.",
                ],
            }
        )
    return {"options": options}


def _deterministic_materialization_result(capability_id: str) -> dict[str, object]:
    summary = f"Deterministic {capability_id} materialization."
    if capability_id == "world_setting":
        return {
            "title": "World Setting",
            "summary_prompt": summary,
            "structured_content": {
                "content": summary,
                "core": {
                    "premise": "A coherent premium advertising world.",
                    "era_and_place": "A contemporary studio environment.",
                    "world_rules": ["Keep visual identity consistent."],
                    "visual_continuity": ["Use one controlled lighting language."],
                },
            },
        }
    if capability_id == "quick_media":
        return {
            "title": "Quick Media",
            "summary_prompt": summary,
            "generation_prompt": summary,
            "structured_content": {"media_type": "image", "content_summary": summary},
        }
    proposal_kind = {
        "product_design": "product",
        "prop_design": "prop",
        "character_design": "character",
        "scene_design": "scene",
        "script_authoring": "script",
        "storyboard_design": "storyboard",
        "video_direction": "video",
        "bgm_direction": "bgm",
    }[capability_id]
    return {
        "title": f"{proposal_kind.title()} Draft",
        "summary_prompt": summary,
        **({} if proposal_kind == "script" else {"generation_prompt": summary}),
        "structured_content": _structured_content_for_proposal(proposal_kind, summary),
    }


def _style_skill_lineage(context: object) -> dict[str, str | None] | None:
    style_guidance = getattr(context, "style_guidance", None)
    if not isinstance(style_guidance, StyleGuidanceContextV2):
        return None
    return {
        "skill_run_id": style_guidance.skill_run_id,
        "creative_direction_snapshot_id": style_guidance.creative_direction_snapshot_id,
        "skill_id": style_guidance.skill_id,
        "skill_version": style_guidance.skill_version,
        "package_digest": style_guidance.package_digest,
        "role": style_guidance.role or "director",
        "role_guidance_digest": style_guidance.role_guidance_digest,
    }


class GuidanceSessionActionService:
    """Project the one action available for the current Guidance session state."""

    def project(
        self,
        session,
        *,
        creating_turn_id: str,
    ) -> tuple[GuidanceSessionActionV2, ...]:
        if session is None or session.status == "completed":
            return ()
        if session.creative_authority is None:
            return tuple(
                GuidanceSessionActionV2(
                    action_id=(
                        "guided_"
                        + hashlib.sha256(
                            (
                                f"{session.session_id}:{session.revision}:"
                                f"set_creative_authority:{authority}"
                            ).encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    logical_key=(
                        f"{session.session_id}:{session.revision}:"
                        f"set_creative_authority:{authority}"
                    ),
                    action="set_creative_authority",
                    authority=authority,
                    state="pending",
                    creating_turn_id=creating_turn_id,
                    expected_session_revision=session.revision,
                    label=label,
                    workflow_id=session.workflow_id,
                    confirmation_required=False,
                    reason="Choose who supplies the next creative direction.",
                )
                for authority, label in (
                    ("user", "I have a direction"),
                    ("director", "Take the lead"),
                )
            )
        action = "stop_guidance" if session.status == "active" else "resume_guidance"
        logical_key = f"{session.session_id}:{session.revision}:{action}"
        return (
            GuidanceSessionActionV2(
                action_id=(
                    "guided_" + hashlib.sha256(logical_key.encode("utf-8")).hexdigest()[:32]
                ),
                logical_key=logical_key,
                action=action,
                state="pending",
                creating_turn_id=creating_turn_id,
                expected_session_revision=session.revision,
                label="Stop guidance" if action == "stop_guidance" else "Resume guidance",
                workflow_id=session.workflow_id,
                confirmation_required=True,
                reason=(
                    "Pause progressive guidance without changing the Canvas."
                    if action == "stop_guidance"
                    else "Resume progressive guidance from the persisted session state."
                ),
            ),
        )


class ProjectCreativeMemoryService:
    """Maintain bounded, non-authoritative creative memory references."""

    def __init__(
        self,
        repository: AgentCanvasConversationRepository,
        workflows: AgentCanvasWorkflowRepository,
    ) -> None:
        self._repository = repository
        self._workflows = workflows

    def get(self, workflow_id: str):
        self._workflows.get_workflow(workflow_id)
        return self._repository.get_creative_memory(workflow_id)

    def update(self, memory):
        self._workflows.get_workflow(memory.workflow_id)
        return self._repository.upsert_creative_memory(memory)

    def reconcile_deleted_nodes(self, workflow_id: str):
        self._workflows.get_workflow(workflow_id)
        return self._repository.reconcile_deleted_memory_nodes(workflow_id)

    def compact_non_authoritative(
        self,
        workflow_id: str,
        *,
        through_sequence_no: int,
        summarize: Callable[[], str],
    ):
        """Persist an optional conversation summary without changing approved facts.

        The caller owns Pi invocation. A summary failure must never invalidate
        authoritative memory or interrupt the conversation that triggered it.
        """

        memory = self.get(workflow_id)
        if through_sequence_no <= memory.summary_through_sequence_no:
            return memory
        try:
            summary = summarize().strip()
        except Exception:  # noqa: BLE001 - compaction is intentionally non-authoritative.
            return memory
        if not summary:
            return memory
        return self.update(
            memory.model_copy(
                update={
                    "conversation_summary": summary,
                    "summary_through_sequence_no": through_sequence_no,
                }
            )
        )


def with_agent_document_provenance(
    node: CanvasNodeV2,
    context: AgentDocumentContextExcerptV2,
) -> CanvasNodeV2:
    """Attach bounded source-document identity without creating an input."""

    return node.model_copy(
        update={
            "metadata": {
                **node.metadata,
                "source_agent_document_id": context.document_id,
                "source_agent_document_kind": context.document_kind,
                "source_agent_document_revision": context.revision,
                "source_agent_document_digest": context.content_digest,
                "source_agent_document_selector": context.selector,
            }
        }
    )


class GuidanceProposalActionService:
    """Prevalidate and atomically publish one Specialist Draft."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._asset_resolver = asset_resolver
        self._connection_policy = connection_policy or AgentCanvasConnectionPolicyService()
        self._world_setting_policy = WorldSettingBindingPolicy()

    def materialize(
        self,
        proposal_id: str,
        *,
        option_id: str,
        draft: SpecialistDraftV2,
        expected_session_revision: int,
        proposal_action: Literal["select_option", "delegate_choice", "reuse_direction"],
        selection_actor: str = "user",
        source_turn_id: str | None = None,
        continuation: ContinuationCommitV2 | None = None,
        document_context: AgentDocumentContextExcerptV2 | None = None,
        deterministic_node_id: str | None = None,
        deterministic_binding_id: Callable[[int], str] | None = None,
        materialization_id: str | None = None,
    ) -> CanvasNodeV2:
        proposal = self._conversations.get_proposal(proposal_id)
        option = next(
            (item for item in proposal.options if item.option_id == option_id),
            None,
        )
        if option is None:
            raise V2PersistenceError(
                "proposal_option_not_found",
                "Concept option was not found.",
                stage="draft_materialization",
            )
        SpecialistDraftValidationService().validate(proposal, draft)
        workflow = self._workflows.get_workflow(proposal.workflow_id)
        now = datetime.now(timezone.utc)
        provenance_keys = {
            "materialization_mode",
            "warning_code",
            "operation_policy_id",
        }
        provenance = {
            key: value for key, value in draft.parameters.items() if key in provenance_keys
        }
        node = CanvasNodeV2(
            node_id=deterministic_node_id or f"node_{uuid4().hex}",
            workflow_id=proposal.workflow_id,
            node_type=draft.node_type,
            creative_role=draft.creative_role,
            title=draft.title,
            status="ready" if draft.node_type == "script" else "draft",
            summary_prompt=draft.summary_prompt,
            generation_prompt=draft.generation_prompt,
            structured_content=draft.structured_content,
            parameters={
                **{
                    key: value
                    for key, value in draft.parameters.items()
                    if key not in provenance_keys
                },
            },
            metadata=provenance,
            position=CanvasPositionV2(x=0, y=0),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        if document_context is not None:
            node = with_agent_document_provenance(node, document_context)
        allowed_sources = {
            (reference.source_kind, reference.source_id)
            for reference in proposal.proposed_references
        }
        bindings = self._validated_bindings(
            node,
            draft.reference_intents,
            allowed_sources=allowed_sources,
            deterministic_binding_id=deterministic_binding_id,
        )
        receipt = (
            AgentActionReceiptV2(
                receipt_id=f"receipt_{source_turn_id}",
                workflow_id=node.workflow_id,
                action_id=source_turn_id,
                proposal_id=proposal.proposal_id,
                proposal_option_id=option_id,
                proposal_action=proposal_action,
                status="applied",
                summary="The selected concept is now an editable Draft.",
                created_node_ids=(node.node_id,),
                created_binding_ids=tuple(binding.binding_id for binding in bindings),
                workflow_revision=workflow.revision + 1,
            )
            if source_turn_id is not None
            else None
        )
        if continuation is not None and receipt is not None:
            if continuation.source_turn_id != source_turn_id:
                raise V2PersistenceError(
                    "continuation_context_invalid",
                    "Continuation source does not match the action turn.",
                    stage="draft_materialization",
                )
            receipt = receipt.model_copy(
                update={"continuation_turn_id": continuation.continuation_turn_id}
            )
        self._conversations.apply_and_materialize(
            proposal_id,
            option_id=option_id,
            node=node,
            bindings=bindings,
            expected_workflow_revision=workflow.revision,
            selection_actor=selection_actor,
            source_turn_id=source_turn_id,
            skill_run_id=proposal.video_skill_run_id,
            topic_id=proposal.topic_id,
            expected_session_revision=expected_session_revision,
            proposal_action=proposal_action,
            receipt=receipt,
            continuation=continuation,
            materialization_id=materialization_id,
        )
        return node

    def publish_world_setting(
        self,
        proposal_id: str,
        *,
        option_id: str,
        candidate: WorldSettingPublicationCandidateV2,
        expected_session_revision: int,
        proposal_action: Literal["select_option", "delegate_choice", "reuse_direction"],
        selection_actor: str = "user",
        source_turn_id: str | None = None,
        continuation: ContinuationCommitV2 | None = None,
        materialization_id: str | None = None,
    ) -> CanvasNodeV2:
        """Publish one canonical ready World Setting atomically."""

        proposal = self._conversations.get_proposal(proposal_id)
        if option_id not in {item.option_id for item in proposal.options}:
            raise V2PersistenceError(
                "proposal_option_not_found",
                "Concept option was not found.",
                stage="world_setting_publication",
            )
        node = candidate.node
        workflow = self._workflows.get_workflow(proposal.workflow_id)
        receipt = (
            AgentActionReceiptV2(
                receipt_id=f"receipt_{source_turn_id}",
                workflow_id=node.workflow_id,
                action_id=source_turn_id,
                proposal_id=proposal.proposal_id,
                proposal_option_id=option_id,
                proposal_action=proposal_action,
                status="applied",
                summary="The World Setting is ready.",
                created_node_ids=(node.node_id,),
                workflow_revision=workflow.revision + 1,
            )
            if source_turn_id is not None
            else None
        )
        if continuation is not None and receipt is not None:
            if continuation.source_turn_id != source_turn_id:
                raise V2PersistenceError(
                    "continuation_context_invalid",
                    "Continuation source does not match the action turn.",
                    stage="world_setting_publication",
                )
            receipt = receipt.model_copy(
                update={"continuation_turn_id": continuation.continuation_turn_id}
            )
        self._conversations.apply_and_materialize(
            proposal_id,
            option_id=option_id,
            node=node,
            expected_workflow_revision=workflow.revision,
            selection_actor=selection_actor,
            source_turn_id=source_turn_id,
            skill_run_id=proposal.video_skill_run_id,
            topic_id=proposal.topic_id,
            expected_session_revision=expected_session_revision,
            proposal_action=proposal_action,
            receipt=receipt,
            continuation=continuation,
            materialization_id=materialization_id,
        )
        return node

    def _validated_bindings(
        self,
        node: CanvasNodeV2,
        intents: tuple[DraftReferenceIntentV2, ...],
        *,
        allowed_sources: set[tuple[str, str]],
        deterministic_binding_id: Callable[[int], str] | None = None,
    ) -> tuple[CanvasBindingV2, ...]:
        bindings: list[CanvasBindingV2] = []
        seen_sources: set[tuple[str, str]] = set()
        seen_orders: set[int] = set()
        for intent in sorted(intents, key=lambda item: item.display_order):
            source_key = (intent.source_kind, intent.source_id)
            if source_key not in allowed_sources:
                raise V2PersistenceError(
                    "draft_reference_not_allowed",
                    "Draft reference was not included in the Specialist allowlist.",
                    stage="draft_materialization",
                )
            if source_key in seen_sources or intent.display_order in seen_orders:
                raise V2PersistenceError(
                    "draft_binding_invalid",
                    "Draft references must have unique sources and display order.",
                    stage="draft_materialization",
                )
            seen_sources.add(source_key)
            seen_orders.add(intent.display_order)
            if intent.source_kind == "node":
                source = self._workflows.get_node(node.workflow_id, intent.source_id)
                decision = self._require_draft_connection(
                    source_node_type=source.node_type,
                    target_node_type=node.node_type,
                    input_role=intent.input_role,
                )
                binding_source = CanvasBindingSourceNodeV2(source_node_id=source.node_id)
            else:
                if self._asset_resolver is None:
                    raise V2PersistenceError(
                        "proposal_reference_unavailable",
                        "Image asset references require the project asset resolver.",
                        stage="draft_materialization",
                    )
                try:
                    asset = self._asset_resolver(intent.source_id)
                except (KeyError, LookupError) as error:
                    raise V2PersistenceError(
                        "proposal_reference_unavailable",
                        "Draft reference asset was not found.",
                        stage="draft_materialization",
                    ) from error
                if asset.media_type != "image" or asset.status != "ready":
                    raise V2PersistenceError(
                        "proposal_reference_unavailable",
                        "Draft references must be Ready image assets.",
                        stage="draft_materialization",
                    )
                decision = self._require_draft_connection(
                    source_node_type="image",
                    target_node_type=node.node_type,
                    input_role=intent.input_role,
                    is_image_asset=True,
                )
                binding_source = CanvasBindingSourceImageAssetV2(source_asset_id=asset.asset_id)
            input_role = intent.input_role
            if decision.input_role != input_role:
                raise V2PersistenceError(
                    "draft_binding_invalid",
                    "Draft reference binding kind conflicts with the connection policy.",
                    stage="draft_materialization",
                )
            binding_metadata = (
                self._world_setting_policy.metadata_for_target(node.creative_role)
                if intent.source_kind == "node" and source.creative_role == "world_setting"
                else {}
            )
            if intent.semantic_reference_role is not None:
                binding_metadata = {
                    **binding_metadata,
                    "semantic_reference_role": intent.semantic_reference_role,
                }
            binding_index = len(bindings)
            bindings.append(
                CanvasBindingV2(
                    binding_id=(
                        deterministic_binding_id(binding_index)
                        if deterministic_binding_id is not None
                        else f"binding_{uuid4().hex}"
                    ),
                    workflow_id=node.workflow_id,
                    source=binding_source,
                    target_node_id=node.node_id,
                    input_role=decision.input_role or input_role,
                    required=intent.required,
                    enabled=True,
                    order=intent.display_order,
                    metadata=binding_metadata,
                    created_at=node.created_at,
                    updated_at=node.created_at,
                )
            )
        return tuple(bindings)

    def _require_draft_connection(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        try:
            return self._connection_policy.require(
                source_node_type=source_node_type,
                target_node_type=target_node_type,
                input_role=input_role,
                is_image_asset=is_image_asset,
            )
        except V2PersistenceError as error:
            raise V2PersistenceError(
                "draft_binding_invalid",
                "Draft reference is incompatible with the connection policy.",
                stage="draft_materialization",
            ) from error


class SpecialistDraftValidationService:
    """Reject incompatible Specialist Drafts without creatively repairing them."""

    def validate(
        self,
        proposal,
        draft: SpecialistDraftV2,
    ) -> None:
        if proposal.capability_id == "quick_media":
            expected_node_type = draft.node_type
            expected_role = {
                "image": "general_image",
                "video": "general_video",
                "audio": "general_audio",
            }.get(draft.node_type)
        else:
            expected_node_type = _node_type_for_proposal(proposal.proposal_kind)
            expected_role = _semantic_role_for_proposal(proposal.proposal_kind)
        if draft.node_type != expected_node_type or draft.creative_role != expected_role:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Specialist Draft is incompatible with the selected concept.",
                stage="draft_materialization",
            )
        try:
            AdMediaDraftValidationService().validate(
                node_type=draft.node_type,
                semantic_role=draft.creative_role,
                structured_content=draft.structured_content,
            )
        except V2PersistenceError as error:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Specialist Draft structured content is invalid.",
                stage="draft_materialization",
            ) from error
        if draft.node_type != "script" and not draft.generation_prompt:
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Media Draft requires a generation prompt.",
                stage="draft_materialization",
            )
        if (
            draft.node_type == "script"
            and not str(draft.structured_content.get("content") or "").strip()
        ):
            raise V2PersistenceError(
                "specialist_draft_invalid",
                "Script Draft requires structured content.",
                stage="draft_materialization",
            )


class AgentConversationService:
    """Persist asynchronous Director turns and apply validated proposal actions."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        nodes: AgentCanvasNodeService,
        gateway: VideoAgentGateway,
        provider_runner: Callable[..., object] | None = None,
        video_skills: VideoSkillRegistry | None = None,
        context_assembler: AgentLocalContextAssembler | None = None,
        command_compiler: AgentCommandPlanCompiler | None = None,
        command_service: AgentCanvasCommandService | None = None,
        run_nodes: Callable[
            [str, tuple[str, ...], str],
            tuple[str, ...],
        ]
        | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
        continuation_outbox: AgentCanvasContinuationOutboxRepository | None = None,
        operation_policies: AgentOperationPolicyRegistryV2 | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._nodes = nodes
        self._gateway = gateway
        self._provider_runner = provider_runner
        self._video_skills = video_skills or VideoSkillRegistry()
        self._context_assembler = context_assembler
        self._command_compiler = command_compiler or AgentCommandPlanCompiler()
        self._command_service = command_service or AgentCanvasCommandService(
            AgentCanvasCommandRepository(
                workflows.database,
                EventRepository(workflows.database),
            ),
        )
        self._run_nodes = run_nodes
        self._asset_resolver = asset_resolver
        self._session_actions = GuidanceSessionActionService()
        self._continuation_outbox = continuation_outbox or (
            AgentCanvasContinuationOutboxRepository(
                workflows.database,
                EventRepository(workflows.database),
            )
        )
        self._materialization_submission = ProposalMaterializationSubmissionService(
            conversations,
            AgentCanvasMaterializationRepository(
                workflows.database,
                EventRepository(workflows.database),
            ),
            reference_snapshot=lambda workflow_id, reference: (
                (
                    workflows.get_node(workflow_id, reference.source_id).revision
                    if reference.source_kind == "node"
                    else None
                ),
                (
                    self._asset_resolver(reference.source_id).version_id
                    if reference.source_kind == "image_asset" and self._asset_resolver is not None
                    else None
                ),
            ),
        )
        self._turn_intents = TurnIntentService(gateway)
        self._next_actions = NextActionExecutionService(gateway)
        self._capability_policy = CapabilityPolicyService()
        self._capability_dispatch = CapabilityDispatchService(
            database=workflows.database,
            events=EventRepository(workflows.database),
        )
        self._next_action_dispatch = NextActionDispatchService(
            workflows.database,
            EventRepository(workflows.database),
        )

    def submit_message(
        self,
        workflow_id: str,
        *,
        text: str,
        idempotency_key: str,
        mentioned_node_ids: tuple[str, ...] = (),
        mentioned_image_asset_ids: tuple[str, ...] = (),
        video_skill_run_id: str | None = None,
    ) -> ChatTurnAcceptedV2:
        self._workflows.get_workflow(workflow_id)
        if video_skill_run_id is None:
            video_skill_run_id = self._conversations.get_active_style_skill_run(
                workflow_id
            ).skill_run_id
        else:
            try:
                skill_run = self._conversations.get_skill_run(video_skill_run_id)
            except V2PersistenceError as error:
                raise V2PersistenceError(
                    "style_skill_activation_conflict",
                    "Style Skill Run is not active for this Workflow.",
                    stage="agent_conversation_service",
                ) from error
            if skill_run.workflow_id != workflow_id or skill_run.status != "active":
                raise V2PersistenceError(
                    "style_skill_activation_conflict",
                    "Style Skill Run is not active for this Workflow.",
                    stage="agent_conversation_service",
                )
        if self._context_assembler is not None:
            self._context_assembler.assemble_director_turn(
                workflow_id,
                conversation_id=f"pending:{idempotency_key}",
                user_input=text,
                mentioned_node_ids=mentioned_node_ids,
                mentioned_image_asset_ids=mentioned_image_asset_ids,
            )
        return self._conversations.create_user_turn(
            workflow_id,
            text=text,
            mentioned_node_ids=mentioned_node_ids,
            mentioned_image_asset_ids=mentioned_image_asset_ids,
            video_skill_run_id=video_skill_run_id,
            idempotency_key=idempotency_key,
        )

    def act_on_proposal(
        self,
        workflow_id: str,
        proposal_id: str,
        request: ProposalActionRequestV2,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        proposal = self._conversations.get_proposal(proposal_id)
        if proposal.workflow_id != workflow_id:
            raise V2PersistenceError(
                "proposal_not_found",
                "Concept proposal was not found.",
                stage="agent_conversation_service",
            )
        if request.action in {"select_option", "delegate_choice", "reuse_direction"}:
            return self._materialization_submission.submit_action(
                workflow_id,
                proposal_id,
                request,
                idempotency_key=idempotency_key,
            )
        existing_turn = self._conversations.get_turn_by_idempotency_key(idempotency_key)
        if existing_turn is not None:
            return self._conversations.create_action_turn(
                workflow_id,
                proposal_id=proposal_id,
                action=request,
                idempotency_key=idempotency_key,
            )
        historical_action = request.action in {"reuse_direction", "revise_direction"}
        if proposal.availability != "open" and not (
            historical_action and proposal.availability == "superseded"
        ):
            raise V2PersistenceError(
                "proposal_action_stale",
                "Concept proposal is not available for application.",
                stage="agent_conversation_service",
            )
        accepted = self._conversations.create_action_turn(
            workflow_id,
            proposal_id=proposal_id,
            action=request,
            idempotency_key=idempotency_key,
        )
        return accepted

    def act_on_command_plan(
        self,
        workflow_id: str,
        plan_id: str,
        *,
        action: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        plan = self._command_service.get_plan(plan_id)
        if plan.workflow_id != workflow_id:
            raise V2PersistenceError(
                "agent_command_plan_not_found",
                "Agent command plan was not found.",
                stage="agent_conversation_service",
            )
        return self._conversations.create_command_action_turn(
            workflow_id,
            plan_id=plan_id,
            action=action,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def act_on_guided_action(
        self,
        workflow_id: str,
        action_id: str,
        *,
        confirmed: bool,
        action_type: str | None = None,
        authority: str | None = None,
        expected_session_revision: int | None = None,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        action = self._conversations.get_guided_action(action_id)
        if action.workflow_id != workflow_id:
            raise V2PersistenceError(
                "guided_action_not_found",
                "Guided action was not found.",
                stage="agent_conversation_service",
            )
        if action.confirmation_required and not confirmed:
            raise V2PersistenceError(
                "confirmation_required",
                "Guided action requires explicit confirmation.",
                stage="agent_conversation_service",
            )
        if action_type is not None and action_type != action.action:
            raise V2PersistenceError(
                "guided_action_invalid",
                "Guided action type does not match the persisted action.",
                stage="agent_conversation_service",
            )
        if authority is not None and authority != action.authority:
            raise V2PersistenceError(
                "guided_action_invalid",
                "Creative authority does not match the persisted action.",
                stage="agent_conversation_service",
            )
        if (
            expected_session_revision is not None
            and expected_session_revision != action.expected_session_revision
        ):
            raise V2PersistenceError(
                "guidance_session_revision_conflict",
                "Guidance session revision is stale.",
                stage="agent_conversation_service",
            )
        return self._conversations.create_guided_action_turn(
            workflow_id,
            action_id=action_id,
            idempotency_key=idempotency_key,
        )

    def process_turn(
        self,
        turn_id: str,
        *,
        proposal: ConceptProposalCreateV2 | None = None,
    ) -> ChatTurnV2:
        turn = self._conversations.get_turn(turn_id)
        if turn.status == "completed":
            return turn
        self._conversations.mark_turn_running(turn_id)
        try:
            if turn.turn_kind == "message":
                return self._process_message_turn(turn_id, turn, proposal)
            if turn.turn_kind == "proposal_action":
                return self._process_proposal_action(turn_id, turn)
            if turn.turn_kind == "command_action":
                return self._process_command_action(turn_id, turn)
            return self._process_guided_action(turn_id, turn)
        except PiAgentRuntimeError as error:
            if error.code == "agent_run_in_progress":
                return self._conversations.get_turn(turn_id)
            return self._conversations.fail_turn(
                turn_id,
                code=error.code,
                message=error.message,
            )
        except V2PersistenceError as error:
            return self._conversations.fail_turn(
                turn_id,
                code=error.code,
                message=str(error),
            )
        except Exception:
            logger.exception(
                "Agent Canvas turn application failed.",
                extra={"turn_id": turn_id, "turn_kind": turn.turn_kind},
            )
            error_code = (
                "proposal_persistence_failed"
                if turn.turn_kind == "proposal_action"
                else "next_action_application_failed"
            )
            return self._conversations.fail_turn(
                turn_id,
                code=error_code,
                message="Agent turn application could not be completed.",
            )

    def _process_message_turn(
        self,
        turn_id: str,
        turn: ChatTurnV2,
        proposal: ConceptProposalCreateV2 | None,
    ) -> ChatTurnV2:
        return self._process_message_turn_lean(turn_id, turn)

    def _process_message_turn_lean(
        self,
        turn_id: str,
        turn: ChatTurnV2,
    ) -> ChatTurnV2:
        workflow = self._workflows.get_workflow(turn.workflow_id)
        existing_session = self._conversations.get_guidance_session_or_none(turn.workflow_id)
        mentioned_node_ids = tuple(
            str(item) for item in turn.request.get("mentioned_node_ids") or ()
        )
        mentioned_asset_ids = tuple(
            str(item) for item in turn.request.get("mentioned_image_asset_ids") or ()
        )
        intent = self._turn_intents.decide(
            TurnIntentContextV1(
                workflow_id=workflow.workflow_id,
                workflow_revision=workflow.revision,
                conversation_id=turn.conversation_id,
                user_input=str(turn.request.get("text") or ""),
                session_exists=existing_session is not None,
                mentioned_node_ids=mentioned_node_ids,
                mentioned_image_asset_ids=mentioned_asset_ids,
            ),
            turn_id=turn_id,
        )
        if intent.mode == "ordinary_conversation":
            return self._complete_turn(
                turn_id,
                turn.workflow_id,
                intent.assistant_message or "Your request is recorded for this canvas.",
            )
        session = existing_session
        if session is None:
            decisions = tuple(
                CreativeElementDecisionV2(
                    element_kind=element.element_kind,
                    presence=element.presence,
                    authority="user",
                    requirements=element.requirements,
                    source="explicit_user",
                )
                for element in intent.explicit_elements
            )
            session = self._conversations.create_guidance_session(
                turn.workflow_id,
                goal=CreativeGoalV2(
                    requested_output="video",
                    delivery_scope="draft",
                    summary=intent.objective,
                    explicit_constraints=intent.explicit_constraints,
                ),
                element_decisions=decisions,
                active_style_skill_run_id=(
                    str(turn.request.get("video_skill_run_id"))
                    if turn.request.get("video_skill_run_id")
                    else None
                ),
            )
        open_proposals = self._conversations.list_open_proposals(turn.workflow_id)
        active_capabilities = tuple(
            dict.fromkeys(
                (
                    *self._continuation_outbox.list_nonterminal_capability_ids(turn.workflow_id),
                    *self._conversations.list_active_materialization_capability_ids(
                        turn.workflow_id
                    ),
                )
            )
        )
        policy = self._capability_policy.evaluate(
            assemble_capability_policy_context(
                workflow=workflow,
                session=session,
                is_new_guided_production=(
                    existing_session is None and intent.mode == "guided_production"
                ),
                targeted_capability=(
                    intent.requested_capability
                    if intent.mode in {"targeted_authoring", "quick_media"}
                    else None
                ),
                open_proposal_capabilities=tuple(
                    proposal.capability_id for proposal in open_proposals
                ),
                active_materialization_capabilities=active_capabilities,
            )
        )
        if intent.mode in {"targeted_authoring", "quick_media"}:
            if intent.requested_capability is None:
                return self._complete_turn(
                    turn_id,
                    turn.workflow_id,
                    intent.assistant_message or "Choose a creative capability to continue.",
                )
            command = self._capability_policy.validate_next_action(
                NextActionCommandV1(
                    action="invoke_capability",
                    capability_id=intent.requested_capability,
                    objective=intent.objective,
                ),
                policy,
            )
        else:
            command = self._next_actions.execute(
                NextActionContextV1(
                    workflow_id=turn.workflow_id,
                    conversation_id=turn.conversation_id,
                    session_revision=session.revision,
                    objective=intent.objective,
                    policy=policy,
                    shared_summary=session.goal.summary,
                ),
                turn_id=turn_id,
            )
        if command.command.action in {"ask_user", "reply"}:
            return self._complete_turn(
                turn_id,
                turn.workflow_id,
                command.command.message or "Please provide more direction.",
            )
        if command.command.action == "finish":
            self._conversations.complete_guidance_session(
                session.session_id,
                expected_session_revision=session.revision,
                completion=GuidanceCompletionProjectionV2(
                    authoring="ready",
                    delivery="ready",
                ),
            )
            return self._complete_turn(
                turn_id,
                turn.workflow_id,
                command.command.message or "Guided production is complete.",
            )
        approved_reference_ids = tuple(dict.fromkeys((*mentioned_node_ids, *mentioned_asset_ids)))
        self._capability_dispatch.dispatch_next_action(
            turn,
            command,
            build_capability_context_snapshot(
                workflow=workflow,
                session=session,
                conversations=self._conversations,
                capability_id=command.command.capability_id,
                objective=command.command.objective or intent.objective,
                approved_reference_ids=approved_reference_ids,
                asset_resolver=self._asset_resolver,
            ),
            session_id=session.session_id,
            expected_session_revision=session.revision,
        )
        return self._conversations.get_turn(turn_id)

    def _process_proposal_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        committed_receipt = self._conversations.get_publication_receipt_for_action(turn_id)
        if committed_receipt is not None:
            return self._complete_turn(turn_id, turn.workflow_id, committed_receipt.summary)
        proposal_id = str(turn.request["proposal_id"])
        action = TypeAdapter(ProposalActionRequestV2).validate_python(turn.request["action"])
        proposal = self._conversations.get_proposal(proposal_id)
        if (
            action.action in {"select_option", "delegate_choice", "reuse_direction"}
            and proposal.materialization is not None
            and proposal.materialization.turn_id == turn_id
            and proposal.materialization.status in {"queued", "working"}
        ):
            return self._conversations.get_turn(turn_id)
        descriptor = next(
            (
                item
                for item in proposal.actions
                if item.action_id == action.action_id and item.action == action.action
            ),
            None,
        )
        historical_action = action.action in {"reuse_direction", "revise_direction"}
        availability_valid = proposal.availability == "open" or (
            historical_action and proposal.availability == "superseded"
        )
        if (
            not availability_valid
            or descriptor is None
            or (
                historical_action
                and descriptor.option_id != getattr(action, "option_id", descriptor.option_id)
            )
        ):
            raise V2PersistenceError(
                "proposal_action_stale",
                "Proposal action is no longer available.",
                stage="agent_conversation_service",
            )
        session = self._conversations.get_guidance_session(turn.workflow_id)
        if (
            action.expected_session_revision != descriptor.expected_session_revision
            or session.revision != action.expected_session_revision
        ):
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance session revision is stale.",
                stage="agent_conversation_service",
            )
        if action.action in {"select_option", "delegate_choice", "reuse_direction"}:
            raise V2PersistenceError(
                "capability_materialization_failed",
                "The selected direction has no active Materialization attempt.",
                stage="agent_conversation_service",
            )
        if action.action in {"defer_topic", "exclude_element"}:
            continuation = _guidance_state_action_continuation(
                turn,
                action_id=action.action_id,
            )
            receipt = self._conversations.apply_guidance_state_action(
                proposal_id,
                source_turn_id=turn_id,
                action_id=action.action_id,
                action=action.action,
                expected_session_revision=action.expected_session_revision,
                continuation=continuation,
            )
            return self._conversations.get_turn(turn_id)
        if action.action == "revise_options":
            revised = self._revise_capability_proposal(turn, proposal, action)
            revised = revised.model_copy(
                update={
                    "topic_id": proposal.topic_id,
                    "target_node_id": proposal.target_node_id,
                    "target_node_revision": proposal.target_node_revision,
                    "proposal_purpose": proposal.proposal_purpose,
                }
            )
            receipt = AgentActionReceiptV2(
                receipt_id=f"receipt_{turn_id}",
                workflow_id=turn.workflow_id,
                action_id=turn_id,
                proposal_id=proposal_id,
                proposal_action="revise_options",
                actor_kind="user",
                idempotency_key=turn_id,
                status="applied",
                summary="The concept options were revised.",
                workflow_revision=self._workflows.get_workflow(turn.workflow_id).revision,
            )
            self._conversations.create_proposal(
                turn_id,
                revised,
                source_proposal_id=proposal_id,
                expected_session_revision=action.expected_session_revision,
                receipt=receipt,
            )
            return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)
        if action.action == "revise_direction":
            revised = self._revise_capability_proposal(
                turn,
                proposal,
                action,
                selected_option_id=action.option_id,
            ).model_copy(
                update={
                    "topic_id": proposal.topic_id,
                    "target_node_id": proposal.target_node_id,
                    "target_node_revision": proposal.target_node_revision,
                    "proposal_purpose": proposal.proposal_purpose,
                }
            )
            receipt = AgentActionReceiptV2(
                receipt_id=f"receipt_{turn_id}",
                workflow_id=turn.workflow_id,
                action_id=turn_id,
                proposal_id=proposal_id,
                proposal_option_id=action.option_id,
                proposal_action="revise_direction",
                actor_kind="user",
                idempotency_key=turn_id,
                status="applied",
                summary="A new Proposal was created from the historical direction.",
                workflow_revision=self._workflows.get_workflow(turn.workflow_id).revision,
            )
            self._conversations.create_proposal(
                turn_id,
                revised,
                source_proposal_id=proposal_id,
                allow_historical_source=True,
                expected_session_revision=action.expected_session_revision,
                receipt=receipt,
            )
            return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)
        raise V2PersistenceError(
            "proposal_action_invalid",
            "This Proposal action is not implemented yet.",
            stage="agent_conversation_service",
        )

    def _dispatch_next_action_after_selection(self, turn: ChatTurnV2) -> None:
        session = self._conversations.get_guidance_session(turn.workflow_id)
        if session.status != "active":
            return
        self._next_action_dispatch.dispatch(
            turn,
            session_id=session.session_id,
            expected_session_revision=session.revision,
            objective=session.goal.summary,
        )

    def _process_command_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        receipt = self._command_service.act(
            plan_id=str(turn.request["plan_id"]),
            action=cast(
                Literal["confirm", "reject"],
                str(turn.request["action"]),
            ),
            expected_revision=int(turn.request["expected_revision"]),
            idempotency_key=turn_id,
        )
        return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)

    def _process_guided_action(self, turn_id: str, turn: ChatTurnV2) -> ChatTurnV2:
        action_id = str(turn.request.get("action_id") or "")
        action = self._conversations.get_guided_action(action_id)
        receipt = self._conversations.apply_guidance_session_action(
            action_id,
            source_turn_id=turn_id,
            continuation=None,
        )
        if action.action == "resume_guidance" or (
            action.action == "set_creative_authority" and action.authority == "director"
        ):
            self._dispatch_next_action_after_selection(turn)
        return self._complete_turn(turn_id, turn.workflow_id, receipt.summary)

    def _complete_turn(
        self,
        turn_id: str,
        workflow_id: str,
        assistant_message: str | None,
    ) -> ChatTurnV2:
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        return self._conversations.complete_turn(
            turn_id,
            assistant_message=assistant_message,
            guided_actions=self._session_actions.project(
                session,
                creating_turn_id=turn_id,
            ),
        )

    def get_turn(self, turn_id: str) -> ChatTurnV2:
        return self._conversations.get_turn(turn_id)

    def recover_pending_turns(self) -> tuple[ChatTurnV2, ...]:
        self._reconcile_terminal_expert_activities()
        return tuple(
            self.process_turn(turn_id)
            for turn_id in self._conversations.list_recoverable_turn_ids()
        )

    def _reconcile_terminal_expert_activities(self) -> None:
        for activity, turn in self._conversations.list_working_activities_with_terminal_turns():
            error_code = (
                turn.error_code
                if turn.status == "failed" and turn.error_code
                else "expert_activity_terminal_reconciled"
            )
            error_message = (
                turn.error_message
                if turn.status == "failed" and turn.error_message
                else "Expert activity was reconciled after its owning turn terminated."
            )
            try:
                self._conversations.transition_expert_activity(
                    activity.activity_id,
                    status="failed",
                    error_code=error_code,
                    error_message=error_message,
                    event_details={"reconciled_from_turn_status": turn.status},
                )
            except V2PersistenceError as error:
                if error.code != "expert_activity_terminal":
                    raise

    def get_timeline(
        self,
        workflow_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> ChatTimelineListResponseV2:
        self._workflows.get_workflow(workflow_id)
        return self._conversations.list_timeline(
            workflow_id,
            after_seq=after_seq,
            limit=limit,
        )

    def get_proposal(self, workflow_id: str, proposal_id: str):
        self._workflows.get_workflow(workflow_id)
        proposal = self._conversations.get_proposal(proposal_id)
        if proposal.workflow_id != workflow_id:
            raise V2PersistenceError(
                "proposal_not_found",
                "Concept proposal was not found.",
                stage="agent_conversation_service",
            )
        return proposal

    def _revise_capability_proposal(
        self,
        turn: ChatTurnV2,
        proposal,
        action: ProposalActionRequestV2,
        *,
        selected_option_id: str | None = None,
    ) -> ConceptProposalCreateV2:
        assert action.instruction is not None
        source_options = tuple(
            option
            for option in proposal.options
            if selected_option_id is None or option.option_id == selected_option_id
        )
        if not source_options:
            raise V2PersistenceError(
                "proposal_option_not_found",
                "Concept option was not found.",
                stage="agent_conversation_service",
            )
        definition = self._capability_policy.definition(proposal.capability_id)
        candidate_count = max(
            len(source_options),
            2 if proposal.capability_id == "world_setting" else 1,
        )
        public_direction = "\n".join(
            f"{option.title}: {option.public_summary}" for option in source_options
        )
        objective = (
            f"Revise this capability direction according to the user instruction. "
            f"Instruction: {action.instruction}\nCurrent direction:\n{public_direction}"
        )
        snapshot_payload = {
            "workflow_id": proposal.workflow_id,
            "proposal_id": proposal.proposal_id,
            "proposal_revision": proposal.proposal_revision,
            "capability_id": proposal.capability_id,
            "instruction": action.instruction,
            "source_option_ids": [option.option_id for option in source_options],
        }
        snapshot_digest = hashlib.sha256(
            json.dumps(snapshot_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        invocation = CapabilityInvocationContextV1(
            context_kind="capability_operation",
            workflow_id=proposal.workflow_id,
            conversation_id=turn.conversation_id,
            capability_id=proposal.capability_id,
            objective=objective,
            context_snapshot_id=f"snapshot_{snapshot_digest[:32]}",
            context_snapshot_digest=snapshot_digest,
            approved_reference_ids=tuple(
                reference.source_id for reference in proposal.proposed_references
            ),
        )
        request_identity = f"proposal-revision:{snapshot_digest}"
        activity = self._conversations.start_expert_activity(
            turn.turn_id,
            capability_id=proposal.capability_id,
            operation=definition.operation,
            display_name=CAPABILITY_DISPLAY_NAMES[proposal.capability_id],
        )
        contract = CAPABILITY_RESULT_CONTRACTS[proposal.capability_id]
        try:
            raw = self._gateway.run_capability(
                request_identity=request_identity,
                capability_id=proposal.capability_id,
                operation=definition.operation,
                result_contract_name=definition.result_contract_name,
                candidate_count=candidate_count,
                context=invocation.model_dump(mode="json"),
                repair_error=None,
            )
            try:
                result = contract.model_validate(raw)
            except ValidationError:
                repaired = self._gateway.run_capability(
                    request_identity=request_identity,
                    capability_id=proposal.capability_id,
                    operation=definition.operation,
                    result_contract_name=definition.result_contract_name,
                    candidate_count=candidate_count,
                    context=invocation.model_dump(mode="json"),
                    repair_error="capability_contract_invalid",
                )
                result = contract.model_validate(repaired)
        except PiAgentRuntimeError as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                error_code=error.code,
                error_message=error.message,
            )
            raise
        except (ValidationError, TypeError, ValueError) as error:
            self._conversations.transition_expert_activity(
                activity.activity_id,
                status="failed",
                error_code="capability_contract_invalid",
                error_message="Capability revision result is invalid.",
            )
            raise V2PersistenceError(
                "capability_contract_invalid",
                "Capability revision result is invalid.",
                stage="agent_conversation_service",
            ) from error
        revised = ConceptProposalCreateV2(
            proposal_kind=proposal.proposal_kind,
            capability_id=proposal.capability_id,
            options=tuple(
                ConceptOptionRecordV2(
                    option_id=(
                        "option_"
                        + hashlib.sha256(
                            f"{request_identity}:{index}:{option.title}".encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    title=option.title,
                    public_summary=option.public_summary,
                    key_decisions=option.key_decisions,
                )
                for index, option in enumerate(result.options)
            ),
            proposed_references=proposal.proposed_references,
            topic_id=proposal.topic_id,
            target_node_id=proposal.target_node_id,
            target_node_revision=proposal.target_node_revision,
            proposal_purpose=proposal.proposal_purpose,
        )
        self._conversations.transition_expert_activity(
            activity.activity_id,
            status="completed",
        )
        return revised


def _guidance_state_action_continuation(
    turn: ChatTurnV2,
    *,
    action_id: str,
) -> ContinuationCommitV2:
    digest = hashlib.sha256(
        f"guidance-state-next-action:{turn.turn_id}:{action_id}".encode("utf-8")
    ).hexdigest()
    return ContinuationCommitV2(
        continuation_id=f"continuation_{digest[:24]}",
        continuation_turn_id=f"turn_{digest[24:56]}",
        source_turn_id=turn.turn_id,
        source_action_id=action_id,
        idempotency_key=f"guidance-state-next-action:{turn.turn_id}",
    )


def _node_type_for_proposal(proposal_kind: str) -> str:
    if proposal_kind == "script":
        return "script"
    if proposal_kind == "video":
        return "video"
    if proposal_kind == "bgm":
        return "audio"
    return "image"


def _semantic_role_for_proposal(proposal_kind: str) -> str:
    return {
        "script": "script",
        "product": "product",
        "prop": "prop",
        "character": "character",
        "scene": "scene",
        "storyboard": "storyboard_sequence",
        "video": "storyboard_video",
        "bgm": "bgm",
    }[proposal_kind]


def _structured_content_for_proposal(
    proposal_kind: str,
    description: str,
) -> dict[str, object]:
    style = {
        "style_prompt": "Detailed semi-realistic advertising illustration",
        "source": "platform_default",
        "negative_style_constraints": [],
    }
    if proposal_kind == "script":
        return {"content": description}
    if proposal_kind in {"product", "prop", "character"}:
        return {
            "subject_identity": description,
            "design_summary": description,
            "style": style,
            "explicit_inclusions": [],
            "negative_constraints": [],
        }
    if proposal_kind == "scene":
        return {
            "scene_identity": description,
            "environment_summary": description,
            "layout": "One coherent advertising environment",
            "lighting": "Consistent commercial lighting",
            "materials": "Consistent materials across every panel",
            "time_of_day": "Day",
            "style": style,
            "panels": [
                {
                    "panel_index": index,
                    "view_or_zone": f"Spatial view {index}",
                    "spatial_description": description,
                    "lighting_material_detail": "Preserve the same lighting and materials.",
                }
                for index in range(1, 10)
            ],
            "explicit_entity_reference_ids": [],
            "exclude_unreferenced_entities": True,
            "no_narrative_progression": True,
        }
    if proposal_kind == "storyboard":
        return {
            "sequence_summary": description,
            "narrative_goal": description,
            "style": style,
            "panels": [
                {
                    "panel_index": index,
                    "beat": f"Beat {index}: {description}",
                    "composition": "Advertising composition",
                    "camera": "Intentional cinematic framing",
                    "subject_action": description,
                    "continuity_from_previous": (
                        "Opening frame" if index == 1 else "Continue from the previous panel"
                    ),
                }
                for index in range(1, 10)
            ],
            "no_generated_text": True,
        }
    if proposal_kind == "video":
        return {
            "segment_summary": description,
            "duration_seconds": 8,
            "storyboard_content": description,
            "dialogue": "",
            "voice_style": "",
            "environment_sound": "",
            "action_effects": "",
            "negative_constraints": "",
            "background_music": False,
        }
    if proposal_kind == "bgm":
        return {
            "music_summary": description,
            "duration_seconds": 30,
            "pace": "Medium",
            "energy_curve": "Build and resolve",
            "instrumentation": "Instrumental ensemble",
            "mood": "Confident",
            "instrumental_only": True,
            "no_vocals": True,
        }
    raise ValueError(f"Unsupported proposal kind: {proposal_kind}")
