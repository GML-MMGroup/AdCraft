"""Idempotent retry orchestration for failed Agent Canvas chat turns."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
    matches_operation_envelope_digest,
    operation_envelope_digest,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import (
    ChatTurnAcceptedV2,
    ChatTurnRetryRequestV1,
    ChatTurnV2,
)
from app.schemas.agent_canvas_capabilities import CapabilityCommandEnvelopeV2
from app.schemas.agent_canvas_guidance import ContinuationTurnRetrySnapshotV1
from app.services.agent_canvas_explicit_retry import explicit_turn_retryable
from app.services.agent_canvas_retry_fingerprint import journey_fingerprint
from app.schemas.agent_canvas_retry_repair import (
    RetryEnvelopeDigestRepairReceiptV1,
    RetryEnvelopeDigestRepairV1,
)


class ChatTurnRetryService:
    """Validate a frozen failed-turn snapshot and enqueue one child attempt."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        *,
        asset_resolver: Callable[[str], object] | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._asset_resolver = asset_resolver
        self._continuations = AgentCanvasContinuationOutboxRepository(
            conversations.database,
            conversations.events,
        )
        self._envelopes = AgentCanvasOperationEnvelopeRepository(conversations.database)
        self._requirements = AgentCanvasRequirementRepository(conversations.database)

    def retry(
        self,
        workflow_id: str,
        turn_id: str,
        request: ChatTurnRetryRequestV1,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        source = self._conversations.get_turn(turn_id)
        if source.workflow_id != workflow_id:
            raise _error("chat_turn_not_found", "Chat turn was not found.")
        continuation = self._continuations.get_for_turn(turn_id)
        if (
            source.turn_kind == "proposal_action"
            and continuation is not None
            and continuation.operation == "capability_materialization"
        ):
            from app.persistence.agent_canvas_materialization_repository import (
                AgentCanvasMaterializationRepository,
            )

            return AgentCanvasMaterializationRepository(
                self._conversations.database,
                self._conversations.events,
            ).retry_storyboard_turn(workflow_id, turn_id, request, idempotency_key=idempotency_key)
        replay = self._conversations.get_turn_by_idempotency_key(idempotency_key)
        if replay is not None:
            source = self._conversations.get_turn(turn_id)
            if replay.retry_of_turn_id != source.turn_id:
                raise _error("idempotency_conflict", "Idempotency key was reused.")
            typed = self._typed_authority(source)
            if typed is not None:
                continuation, envelope, snapshot = typed
                return self._conversations.create_typed_retry_turn(
                    source,
                    source_envelope=envelope,
                    operation=continuation.operation,
                    idempotency_key=idempotency_key,
                    retry_snapshot=snapshot,
                )
            return self._conversations.create_retry_turn(
                source,
                idempotency_key=idempotency_key,
                retry_snapshot=self._conversations.get_retry_snapshot(source.turn_id),
            )

        source, snapshot_payload = self.validate(workflow_id, turn_id, request)
        typed = self._typed_authority(source)
        if typed is not None:
            continuation, envelope, snapshot = typed
            return self._conversations.create_typed_retry_turn(
                source,
                source_envelope=envelope,
                operation=continuation.operation,
                idempotency_key=idempotency_key,
                retry_snapshot=snapshot,
            )
        return self._conversations.create_retry_turn(
            source,
            idempotency_key=idempotency_key,
            retry_snapshot=snapshot_payload,
        )

    def _typed_authority(self, source: ChatTurnV2):
        continuation = self._continuations.get_for_turn(source.turn_id)
        if continuation is None or continuation.operation not in {
            "next_action",
            "capability_command",
        }:
            return None
        envelope = self._envelopes.get(continuation.envelope_id)
        try:
            snapshot = ContinuationTurnRetrySnapshotV1.model_validate(
                self._conversations.get_retry_snapshot(source.turn_id)
            )
        except ValueError as error:
            raise _stale_error() from error
        return continuation, envelope, snapshot

    def validate(
        self,
        workflow_id: str,
        turn_id: str,
        request: ChatTurnRetryRequestV1,
    ) -> tuple[ChatTurnV2, dict[str, object]]:
        """Validate frozen retry authority without creating a retry Turn."""

        return self._validate(workflow_id, turn_id, request)

    def repair_legacy_envelope_digest(
        self,
        workflow_id: str,
        turn_id: str,
        *,
        expected_snapshot_digest: str,
        expected_envelope_digest: str,
    ) -> RetryEnvelopeDigestRepairReceiptV1:
        """Operator-only repair; never enqueue work or relax other frozen authority."""

        from app.persistence.agent_canvas_retry_repair_repository import (
            RetryEnvelopeDigestRepairRepository,
        )

        command = RetryEnvelopeDigestRepairV1(
            workflow_id=workflow_id,
            turn_id=turn_id,
            expected_snapshot_digest=expected_snapshot_digest,
            expected_envelope_digest=expected_envelope_digest,
        )
        return RetryEnvelopeDigestRepairRepository(
            self._conversations.database, self._conversations.events
        ).repair(command, validate=self._validate_digest_repair)

    def _validate_digest_repair(
        self, workflow_id: str, turn_id: str, request: ChatTurnRetryRequestV1, digest: str
    ) -> ChatTurnV2:
        return self._validate(workflow_id, turn_id, request, repair_envelope_digest=digest)[0]

    def _validate(
        self,
        workflow_id: str,
        turn_id: str,
        request: ChatTurnRetryRequestV1,
        *,
        repair_envelope_digest: str | None = None,
    ) -> tuple[ChatTurnV2, dict[str, object]]:

        source = self._conversations.get_turn(turn_id)
        if source.workflow_id != workflow_id:
            raise _error("chat_turn_not_found", "Chat turn was not found.")

        if self._conversations.has_committed_storyboard_materialization(turn_id):
            raise _error(
                "chat_turn_not_retryable",
                "Committed Storyboard materialization cannot be retried as a Turn.",
            )

        if source.status == "superseded":
            raise _error(
                "chat_turn_not_retryable",
                "Superseded chat turns cannot be retried.",
            )
        if source.status != "failed":
            raise _error("chat_turn_not_failed", "Only a failed chat turn can be retried.")
        if not source.retryable:
            raise _error(
                "chat_turn_not_retryable",
                "This chat turn failure is not retryable.",
            )
        if (
            source.actionable_failure is None
            or source.actionable_failure.retry_scope != "turn"
            or source.actionable_failure.user_action != "retry"
        ):
            raise _error(
                "chat_turn_not_retryable",
                "This failure must use its operation-specific recovery authority.",
            )

        workflow = self._workflows.get_workflow(workflow_id)
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        raw_snapshot = self._conversations.get_retry_snapshot(source.turn_id)
        continuation = self._continuations.get_for_turn(source.turn_id)
        is_typed = continuation is not None and continuation.operation in {
            "next_action",
            "capability_command",
        }
        if not is_typed:
            return self._validate_ordinary_snapshot(
                source,
                raw_snapshot,
                workflow_revision=workflow.revision,
                session=session,
                request=request,
            )
        if not explicit_turn_retryable(source.error_code or ""):
            raise _error(
                "chat_turn_not_retryable",
                "This typed Agent failure is not eligible for explicit retry.",
            )
        try:
            snapshot = ContinuationTurnRetrySnapshotV1.model_validate(raw_snapshot)
        except ValueError as error:
            raise _stale_error() from error
        current_session_revision = session.revision if session is not None else 0
        has_journey_fingerprint = (
            snapshot.journey_node_revisions is not None
            and snapshot.journey_binding_digest is not None
        )
        if (
            request.expected_workflow_revision != workflow.revision
            or request.expected_session_revision != current_session_revision
            or snapshot.workflow_id != workflow_id
            or snapshot.conversation_id != source.conversation_id
            or (not has_journey_fingerprint and snapshot.workflow_revision != workflow.revision)
            or snapshot.session_revision != current_session_revision
        ):
            raise _stale_error()

        journey = session.journey if session is not None else None
        if journey is not None and (
            snapshot.session_id != session.session_id
            or snapshot.journey_stage != journey.stage
            or snapshot.journey_stage_revision != journey.stage_revision
            or journey.active_action is None
            or snapshot.logical_action_id != journey.active_action.action_id
        ):
            raise _stale_error()

        current_nodes = {node.node_id: node.revision for node in workflow.nodes}
        if has_journey_fingerprint:
            journey_node_revisions, journey_binding_digest = journey_fingerprint(
                workflow.nodes, workflow.bindings
            )
            if (
                snapshot.journey_node_revisions != journey_node_revisions
                or snapshot.journey_binding_digest != journey_binding_digest
                or snapshot.node_revisions != journey_node_revisions
            ):
                raise _stale_error()
        elif any(
            current_nodes.get(str(node_id)) != revision
            for node_id, revision in snapshot.node_revisions.items()
        ):
            raise _stale_error()
        if snapshot.referenced_node_revisions is not None and any(
            current_nodes.get(str(node_id)) != revision
            for node_id, revision in snapshot.referenced_node_revisions.items()
        ):
            raise _stale_error()

        requirement = self._requirements.get_current(workflow_id)
        if (
            requirement.revision_id != snapshot.requirement_revision_id
            or requirement.digest != snapshot.requirement_digest
        ):
            raise _stale_error()
        if self._asset_resolver is not None:
            try:
                for asset_id in snapshot.asset_ids:
                    self._asset_resolver(str(asset_id))
            except V2PersistenceError as error:
                raise _stale_error() from error

        if (
            continuation is None
            or continuation.operation != snapshot.operation
            or continuation.envelope_id != snapshot.envelope_id
        ):
            raise _stale_error()
        envelope = self._envelopes.get(snapshot.envelope_id)
        if repair_envelope_digest is not None and (
            operation_envelope_digest(envelope) != repair_envelope_digest
            or matches_operation_envelope_digest(envelope, snapshot.envelope_digest)
        ):
            raise _stale_error()
        if envelope.workflow_id != workflow_id or not matches_operation_envelope_digest(
            envelope, repair_envelope_digest or snapshot.envelope_digest
        ):
            raise _stale_error()
        if isinstance(envelope, CapabilityCommandEnvelopeV2):
            policy_digest = hashlib.sha256(
                json.dumps(
                    {
                        "capability_id": envelope.capability_id,
                        "result_contract_name": envelope.result_contract_name,
                        "candidate_count": envelope.candidate_count,
                        "reference_plan_digest": envelope.reference_plan.digest,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            skill_digest = (
                hashlib.sha256(envelope.style_skill_run_id.encode("utf-8")).hexdigest()
                if envelope.style_skill_run_id is not None
                else None
            )
            if (
                snapshot.policy_identity_digest != policy_digest
                or snapshot.skill_identity_digest != skill_digest
            ):
                raise _stale_error()
        active = self._continuations.list_nonterminal_for_workflow(workflow_id)
        if active:
            raise _error(
                "active_continuation_conflict",
                "Another continuation already owns this workflow.",
            )

        return source, snapshot.model_dump(mode="json")

    def _validate_ordinary_snapshot(
        self,
        source: ChatTurnV2,
        snapshot: dict[str, object],
        *,
        workflow_revision: int,
        session,
        request: ChatTurnRetryRequestV1,
    ) -> tuple[ChatTurnV2, dict[str, object]]:
        session_revision = session.revision if session is not None else 0
        has_journey_fingerprint = (
            snapshot.get("journey_node_revisions") is not None
            and snapshot.get("journey_binding_digest") is not None
        )
        if (
            request.expected_workflow_revision != workflow_revision
            or request.expected_session_revision != session_revision
            or (
                not has_journey_fingerprint
                and snapshot.get("workflow_revision") != workflow_revision
            )
            or snapshot.get("session_revision") != session_revision
        ):
            raise _stale_error()
        journey = session.journey if session is not None else None
        if journey is not None and (
            snapshot.get("journey_stage") != journey.stage
            or snapshot.get("journey_stage_revision") != journey.stage_revision
        ):
            raise _stale_error()
        workflow = self._workflows.get_workflow(source.workflow_id)
        current_nodes = {node.node_id: node.revision for node in workflow.nodes}
        if has_journey_fingerprint:
            journey_node_revisions, journey_binding_digest = journey_fingerprint(
                workflow.nodes, workflow.bindings
            )
            if (
                snapshot.get("journey_node_revisions") != journey_node_revisions
                or snapshot.get("journey_binding_digest") != journey_binding_digest
            ):
                raise _stale_error()
        node_revisions = snapshot.get("node_revisions")
        if not isinstance(node_revisions, dict) or any(
            current_nodes.get(str(node_id)) != revision
            for node_id, revision in node_revisions.items()
        ):
            raise _stale_error()
        asset_ids = snapshot.get("asset_ids")
        if not isinstance(asset_ids, list):
            raise _stale_error()
        if self._asset_resolver is not None:
            try:
                for asset_id in asset_ids:
                    self._asset_resolver(str(asset_id))
            except V2PersistenceError as error:
                raise _stale_error() from error
        return source, snapshot


def _stale_error() -> V2PersistenceError:
    return _error(
        "chat_turn_retry_stale",
        "The failed chat turn snapshot no longer matches current authoring state.",
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="chat_turn_retry_service")
